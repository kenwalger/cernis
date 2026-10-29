"""Tests for the cache: conditional requests, 304 receipts, and a damaged cache."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fetch_support import Site, make_fetcher, respond

from cernis.fetch.cache import DEFAULT_CACHE_DIR, Cache

PAGE = "https://example.com/post"
BODY = b"<html>cached</html>"
ETAG = '"v1"'
LAST_MODIFIED = "Wed, 28 Oct 2026 10:00:00 GMT"
REPO_ROOT = Path(__file__).resolve().parents[1]


def page_requests(site: Site) -> list[httpx.Request]:
    """Return the requests for the page, leaving out robots.txt.

    :param site: The scripted web.
    :return: The page requests.
    """
    return [request for request in site.requests if str(request.url) == PAGE]


def test_a_304_is_recorded_with_the_cached_body_hash(tmp_path: Path) -> None:
    """The next run asks with If-None-Match, and a 304 links to the cached body by its hash."""
    site = Site()
    site.add(PAGE, respond(200, BODY, {"etag": ETAG}))
    first = make_fetcher(site, tmp_path).fetch(PAGE)
    site.add(PAGE, respond(304, headers={"etag": ETAG}))

    second = make_fetcher(site, tmp_path).fetch(PAGE)

    (receipt,) = second.receipts
    assert receipt.status_code == 304
    assert receipt.body_sha256 == first.receipts[0].body_sha256 == hashlib.sha256(BODY).hexdigest()
    assert second.body == BODY
    assert page_requests(site)[1].headers["if-none-match"] == ETAG


def test_last_modified_is_sent_as_if_modified_since(tmp_path: Path) -> None:
    """A cached Last-Modified becomes If-Modified-Since."""
    site = Site()
    site.add(PAGE, respond(200, BODY, {"last-modified": LAST_MODIFIED}))
    make_fetcher(site, tmp_path).fetch(PAGE)

    make_fetcher(site, tmp_path).fetch(PAGE)

    second = page_requests(site)[1]
    assert second.headers["if-modified-since"] == LAST_MODIFIED
    assert "if-none-match" not in second.headers


def test_a_changed_page_replaces_the_cached_body(tmp_path: Path) -> None:
    """A 200 to a conditional request is a new body, cached in place of the old."""
    site = Site()
    site.add(PAGE, respond(200, BODY, {"etag": ETAG}))
    make_fetcher(site, tmp_path).fetch(PAGE)
    site.add(PAGE, respond(200, b"new", {"etag": '"v2"'}))
    make_fetcher(site, tmp_path).fetch(PAGE)

    entry = Cache(tmp_path).lookup(PAGE)

    assert entry is not None
    assert (entry.etag, entry.body) == ('"v2"', b"new")


def test_a_304_with_a_new_validator_updates_the_entry(tmp_path: Path) -> None:
    """A 304 that carries a new ETag refreshes the stored one."""
    site = Site()
    site.add(PAGE, respond(200, BODY, {"etag": ETAG}))
    make_fetcher(site, tmp_path).fetch(PAGE)
    site.add(PAGE, respond(304, headers={"etag": '"v1b"'}))
    make_fetcher(site, tmp_path).fetch(PAGE)

    entry = Cache(tmp_path).lookup(PAGE)

    assert entry is not None
    assert (entry.etag, entry.body) == ('"v1b"', BODY)


def test_a_response_without_validators_is_not_cached(tmp_path: Path) -> None:
    """Without ETag or Last-Modified there is nothing to revalidate, so nothing is kept."""
    site = Site()
    site.add(PAGE, respond(200, BODY))
    make_fetcher(site, tmp_path).fetch(PAGE)

    make_fetcher(site, tmp_path).fetch(PAGE)

    assert Cache(tmp_path).lookup(PAGE) is None
    assert "if-none-match" not in page_requests(site)[1].headers


def test_an_oversized_body_is_not_cached(tmp_path: Path) -> None:
    """A body cut off at the limit is not a body to revalidate."""
    site = Site()
    site.add(PAGE, respond(200, BODY, {"etag": ETAG}))

    make_fetcher(site, tmp_path, max_body_bytes=4).fetch(PAGE)

    assert Cache(tmp_path).lookup(PAGE) is None


def test_only_a_200_is_cached(tmp_path: Path) -> None:
    """A 404 with an ETag is not cached."""
    site = Site()
    site.add(PAGE, respond(404, BODY, {"etag": ETAG}))

    make_fetcher(site, tmp_path).fetch(PAGE)

    assert Cache(tmp_path).lookup(PAGE) is None


def test_an_unrequested_304_has_no_body_and_no_hash(tmp_path: Path) -> None:
    """A 304 Cernis did not ask for validates nothing, so it links to nothing."""
    site = Site()
    site.add(PAGE, respond(304))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert (result.receipts[0].status_code, result.receipts[0].body_sha256) == (304, None)
    assert result.body is None


def _cache_one(tmp_path: Path) -> Cache:
    """Cache BODY for PAGE with an ETag.

    :param tmp_path: The cache directory.
    :return: The cache.
    """
    cache = Cache(tmp_path)
    cache.store(PAGE, etag=ETAG, last_modified=None, body=BODY)
    assert cache.lookup(PAGE) is not None
    return cache


def test_a_damaged_body_is_a_miss(tmp_path: Path) -> None:
    """A body whose hash no longer matches is never used; the request is unconditional."""
    _cache_one(tmp_path)
    (tmp_path / "bodies" / hashlib.sha256(BODY).hexdigest()).write_bytes(b"tampered")
    site = Site()
    site.add(PAGE, respond(304))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert "if-none-match" not in page_requests(site)[0].headers
    assert result.receipts[0].body_sha256 is None


@pytest.mark.parametrize(
    "damage",
    [
        "not json",
        json.dumps([1, 2]),
        json.dumps({"url": "https://elsewhere.example/", "etag": ETAG, "body_sha256": "a" * 64}),
        json.dumps({"url": PAGE, "etag": '"v1"\r\nX-Injected: 1', "body_sha256": "a" * 64}),
        json.dumps({"url": PAGE, "etag": ETAG, "body_sha256": "../../escape"}),
        json.dumps({"url": PAGE, "etag": None, "last_modified": None, "body_sha256": "a" * 64}),
    ],
)
def test_a_damaged_entry_is_a_miss(tmp_path: Path, damage: str) -> None:
    """An entry that is unreadable, for another URL, or unsafe to send back is ignored."""
    _cache_one(tmp_path)
    (entry,) = (tmp_path / "entries").iterdir()
    entry.write_text(damage, encoding="utf-8")

    assert Cache(tmp_path).lookup(PAGE) is None


def test_a_cached_body_over_the_limit_is_a_miss(tmp_path: Path) -> None:
    """A body cached under a larger limit is not reused, so a 304 cannot bring it back."""
    Cache(tmp_path, max_body_bytes=100).store(PAGE, etag=ETAG, last_modified=None, body=BODY)
    site = Site()
    site.add(PAGE, respond(304))

    make_fetcher(site, tmp_path, max_body_bytes=4).fetch(PAGE)

    assert "if-none-match" not in page_requests(site)[0].headers


def test_a_deeply_nested_entry_is_a_miss(tmp_path: Path) -> None:
    """An entry that would exhaust the JSON parser's recursion is a miss, not a crash."""
    cache = _cache_one(tmp_path)
    (entry,) = (tmp_path / "entries").iterdir()
    entry.write_text("[" * 50_000, encoding="utf-8")

    assert cache.lookup(PAGE) is None


def test_an_entry_too_large_to_be_one_is_a_miss(tmp_path: Path) -> None:
    """Entries are small; an oversized one is not read."""
    cache = _cache_one(tmp_path)
    (entry,) = (tmp_path / "entries").iterdir()
    entry.write_text(" " * 100_000 + "{}", encoding="utf-8")

    assert cache.lookup(PAGE) is None


def test_a_body_that_is_not_a_regular_file_is_a_miss(tmp_path: Path) -> None:
    """Only a regular file is read as a body."""
    cache = _cache_one(tmp_path)
    body = tmp_path / "bodies" / hashlib.sha256(BODY).hexdigest()
    body.unlink()
    body.mkdir()

    assert cache.lookup(PAGE) is None


def test_a_damaged_body_is_rewritten_on_the_next_store(tmp_path: Path) -> None:
    """Storing the same body again repairs a damaged copy."""
    cache = _cache_one(tmp_path)
    (tmp_path / "bodies" / hashlib.sha256(BODY).hexdigest()).write_bytes(b"tampered")

    cache.store(PAGE, etag=ETAG, last_modified=None, body=BODY)

    assert cache.lookup(PAGE) is not None


def test_an_existing_directory_gets_no_gitignore(tmp_path: Path) -> None:
    """A .gitignore that ignores everything is written only into a directory Cernis creates."""
    Cache(tmp_path).store(PAGE, etag=ETAG, last_modified=None, body=BODY)

    assert not (tmp_path / ".gitignore").exists()


def test_a_cache_that_cannot_be_written_does_not_stop_a_fetch(tmp_path: Path) -> None:
    """A cache directory that is really a file is a miss, not a failure."""
    blocker = tmp_path / "cache"
    blocker.write_text("not a directory", encoding="utf-8")
    site = Site()
    site.add(PAGE, respond(200, BODY, {"etag": ETAG}))

    result = make_fetcher(site, blocker).fetch(PAGE)

    assert result.receipts[0].status_code == 200


def test_the_cache_directory_ignores_itself(tmp_path: Path) -> None:
    """A cache placed anywhere carries a .gitignore that ignores everything in it."""
    _cache_one(tmp_path / "cache")

    lines = (tmp_path / "cache" / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "*" in lines


def test_no_cache_directory_means_no_files_and_no_conditional_requests(tmp_path: Path) -> None:
    """With cache_dir None, nothing is written and nothing is revalidated."""
    site = Site()
    site.add(PAGE, respond(200, BODY, {"etag": ETAG}))

    make_fetcher(site, None).fetch(PAGE)
    make_fetcher(site, None).fetch(PAGE)

    assert "if-none-match" not in page_requests(site)[1].headers
    assert list(tmp_path.iterdir()) == []


def test_the_default_cache_directory_is_git_ignored() -> None:
    """DESIGN.md section 6: the cache is in a git-ignored directory."""
    assert Path(".cernis-cache") == DEFAULT_CACHE_DIR
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".cernis-cache/" in ignored
