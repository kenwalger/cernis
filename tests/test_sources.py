"""Tests for URL sources (cernis.sources) and the commands that use them."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fetch_support import FIXED_NOW, FakeResolver, Reply, Site, make_fetcher, respond
from parse_support import fixture

from cernis import cli
from cernis.audit import RunFetches
from cernis.cli import main
from cernis.fetch import FetchConfig, Fetcher
from cernis.sources import DEV_API, SourceError, from_dev_user, from_sitemap

JSON = {"content-type": "application/json"}
XML = {"content-type": "application/xml"}
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
ORIGIN = "https://blog.example.com"
ORIGINAL = f"{ORIGIN}/2026/10/a-synthetic-post/"


def api(page: int, per_page: int, user: str = "example") -> str:
    """Name one page of DEV's articles API.

    :param page: The page number.
    :param per_page: The page size.
    :param user: The username.
    :return: The URL.
    """
    return f"{DEV_API}?username={user}&page={page}&per_page={per_page}"


def article(slug: str, canonical: str | None = None, published: bool = True) -> dict[str, Any]:
    """Write one article as DEV's API returns it (the fields Cernis reads).

    :param slug: The article's slug.
    :param canonical: Its canonical_url; the DEV URL itself if ``None``.
    :param published: Whether it is published.
    :return: The JSON object.
    """
    url = f"https://dev.to/example/{slug}"
    return {
        "type_of": "article",
        "title": slug,
        "url": url,
        "canonical_url": canonical or url,
        "published_at": "2026-10-01T00:00:00Z" if published else None,
    }


def answer(items: list[dict[str, Any]]) -> Reply:
    """Build an API reply.

    :param items: The articles.
    :return: The reply.
    """
    return respond(200, json.dumps(items).encode(), JSON)


def fetches(site: Site, tmp_path: Path) -> RunFetches:
    """Make a run's fetches on a scripted web.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :return: The fetches.
    """
    return RunFetches(make_fetcher(site, tmp_path, min_interval=0))


# DEV


def test_dev_api_pages_are_read_until_a_short_page(tmp_path: Path) -> None:
    """Page 1 is full, page 2 is short, so reading stops; each request is a receipt."""
    site = Site()
    first = [article(f"a{n}", canonical=f"{ORIGIN}/a{n}/") for n in range(100)]
    site.add(api(1, 100), answer(first))
    site.add(api(2, 100), answer([article("last"), article("draft", published=False)]))

    run = fetches(site, tmp_path)
    listing = from_dev_user(run, "example")

    assert len(listing.articles) == 101
    assert [u for u in site.urls() if "api" in u] == [api(1, 100), api(2, 100)]
    assert [run.receipts[r].requested_url for r in listing.source.receipt_ids] == [
        "https://dev.to/robots.txt",
        api(1, 100),
        api(2, 100),
    ]
    assert listing.articles[0].original == f"{ORIGIN}/a0/"
    (note,) = listing.source.notes
    assert note.url == "https://dev.to/example/last"
    assert note.note.startswith("not cross-posted: its canonical URL is on DEV")


def test_the_limit_stops_reading(tmp_path: Path) -> None:
    """A limit of 2 asks for 2 per page and reads one page."""
    site = Site()
    site.add(api(1, 2), answer([article("a"), article("b")]))

    listing = from_dev_user(fetches(site, tmp_path), "example", limit=2)

    assert listing.source.listed == ("https://dev.to/example/a", "https://dev.to/example/b")
    assert api(2, 2) not in site.urls()


def test_a_failed_page_stops_the_listing_with_a_note(tmp_path: Path) -> None:
    """A short listing is never mistaken for a complete one."""
    site = Site()
    site.add(api(1, 100), answer([article(f"a{n}") for n in range(100)]))
    site.add(api(2, 100), respond(500))

    listing = from_dev_user(fetches(site, tmp_path), "example")

    assert len(listing.source.listed) == 100
    assert any(
        "the listing stops here: the server answered 500" in n.note for n in listing.source.notes
    )


def test_articles_off_dev_or_without_dev_urls_are_ignored(tmp_path: Path) -> None:
    """Only published articles at dev.to URLs are listed; a bad canonical is no canonical."""
    site = Site()
    items = [
        {**article("a"), "url": "https://evil.example/a"},
        {**article("b"), "canonical_url": "javascript:alert(1)"},
        {"type_of": "podcast_episode", "url": "https://dev.to/p", "published_at": "x"},
    ]
    site.add(api(1, 100), answer(items))

    listing = from_dev_user(fetches(site, tmp_path), "example")

    (only,) = listing.articles
    assert (only.url, only.canonical_url, only.original) == ("https://dev.to/example/b", None, None)


@pytest.mark.parametrize("name", ["", "a b", "../etc", "a&page=9"])
def test_a_bad_username_is_refused_before_any_request(tmp_path: Path, name: str) -> None:
    """The username goes into a URL, so it must be a DEV username."""
    site = Site()
    with pytest.raises(SourceError, match="not a DEV username"):
        from_dev_user(fetches(site, tmp_path), name)
    assert site.requests == []


# Sitemaps


def urlset(*locs: str) -> bytes:
    """Write a <urlset>.

    :param *locs: The page URLs.
    :return: The XML.
    """
    rows = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f"<urlset {NS}>{rows}</urlset>".encode()


def test_a_sitemap_lists_pages_under_a_prefix_up_to_a_limit(tmp_path: Path) -> None:
    """--include-prefix keeps whole path segments; --limit stops the list."""
    site = Site()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(
            200,
            urlset(
                f"{ORIGIN}/blog/a/",
                f"{ORIGIN}/blogger/x/",
                f"{ORIGIN}/blog/b/",
                f"{ORIGIN}/blog/c/",
            ),
            XML,
        ),
    )

    listing = from_sitemap(
        fetches(site, tmp_path), f"{ORIGIN}/sitemap.xml", include_prefix=f"{ORIGIN}/blog/", limit=2
    )

    assert listing.source.listed == (f"{ORIGIN}/blog/a/", f"{ORIGIN}/blog/b/")


def test_a_missing_sitemap_is_noted(tmp_path: Path) -> None:
    """Nothing listed, and the note says why."""
    listing = from_sitemap(fetches(Site(), tmp_path), f"{ORIGIN}/sitemap.xml")

    assert listing.source.listed == ()
    assert listing.source.notes[0].note == "no sitemap here: it answered 404"


# The commands


def scripted(monkeypatch: pytest.MonkeyPatch, site: Site) -> None:
    """Make the CLI fetch from a scripted web without pacing waits.

    :param monkeypatch: Used to replace the CLI's fetcher.
    :param site: The scripted web.
    """

    def build(config: FetchConfig) -> Fetcher:
        return Fetcher(
            config,
            transport=httpx.MockTransport(site.handler),
            sleep=lambda seconds: None,
            now=lambda: FIXED_NOW,
            resolver=FakeResolver(),
        )

    monkeypatch.setattr(cli, "Fetcher", build)


def dev_site() -> Site:
    """Script a DEV user with one cross-post and one article that is not.

    :return: The scripted web.
    """
    site = Site()
    copy = "https://dev.to/example-author/a-synthetic-post-1a2b"
    site.add(
        api(1, 100, "example_author"),
        answer([{**article("x"), "url": copy, "canonical_url": ORIGINAL}, article("solo")]),
    )
    html = {"content-type": "text/html"}
    site.add(ORIGINAL, respond(200, fixture("wordpress-entry"), html))
    site.add(copy, respond(200, fixture("dev-article"), html))
    return site


def test_pairs_from_dev_user_list_only_stops_after_the_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    isolated_store: Path,
) -> None:
    """--list-only prints the pairs and the requests, audits nothing, and opens no store."""
    site = dev_site()
    scripted(monkeypatch, site)

    code = main(
        ["pairs", "--from-dev-user", "example_author", "--list-only", "--cache-dir", str(tmp_path)]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Source: DEV user example_author" in out
    assert f"- original {ORIGINAL}; copy https://dev.to/example-author/a-synthetic-post-1a2b" in out
    assert "not cross-posted" in out
    assert ORIGINAL not in site.urls()
    assert not isolated_store.exists()


def test_pairs_from_dev_user_audits_each_cross_post(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The canonical is the original, the DEV URL the copy; the report records the source."""
    scripted(monkeypatch, dev_site())

    code = main(
        [
            "pairs",
            "--from-dev-user",
            "example_author",
            "--format",
            "json",
            "--cache-dir",
            str(tmp_path),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["pairs"] == [
        {"original": ORIGINAL, "copy": "https://dev.to/example-author/a-synthetic-post-1a2b"}
    ]
    (source,) = report["sources"]
    assert (source["kind"], source["query"]) == ("dev-user", "example_author")
    assert source["notes"][-1]["note"].startswith("not cross-posted")


def test_audit_from_sitemap_list_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The listing names each URL and each request's receipt."""
    site = Site()
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, urlset(f"{ORIGIN}/a/", f"{ORIGIN}/b/"), XML))
    scripted(monkeypatch, site)

    code = main(
        [
            "audit",
            "--from-sitemap",
            f"{ORIGIN}/sitemap.xml",
            "--list-only",
            "--limit",
            "1",
            "--cache-dir",
            str(tmp_path),
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert f"URLs (1):\n\n- {ORIGIN}/a/\n" in out
    assert f"- r-002: {ORIGIN}/sitemap.xml (200)" in out
    assert f"{ORIGIN}/a/" not in site.urls()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["audit"], "exactly one"),
        (["audit", ORIGINAL, "--from-dev-user", "x"], "exactly one"),
        (["audit", ORIGINAL, "--list-only"], "need a source"),
        (["audit", "--include-prefix", ORIGIN, "--from-dev-user", "x"], "needs --from-sitemap"),
        (["pairs"], "give --map or --from-dev-user"),
        (["audit", "--from-dev-user", "not valid!"], "not a DEV username"),
    ],
)
def test_conflicting_arguments_exit_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    """Each mistake is named."""
    scripted(monkeypatch, Site())

    assert main(argv) == 2
    assert message in capsys.readouterr().err


def test_a_zero_limit_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """--limit must be at least 1."""
    with pytest.raises(SystemExit):
        main(["pairs", "--from-dev-user", "x", "--limit", "0"])
    assert "at least 1" in capsys.readouterr().err


# Session 5b audit (aud_gwCSZD5Y6S) regressions


def test_a_sitemap_lists_only_its_own_hosts_pages(tmp_path: Path) -> None:
    """V3 f13: pages on other hosts are left out, and the note says how many."""
    site = Site()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(200, urlset(f"{ORIGIN}/a/", "https://elsewhere.example/b/"), XML),
    )

    listing = from_sitemap(fetches(site, tmp_path), f"{ORIGIN}/sitemap.xml")

    assert listing.source.listed == (f"{ORIGIN}/a/",)
    assert any("1 listed pages on other hosts" in n.note for n in listing.source.notes)


@pytest.mark.parametrize(
    "argv",
    [
        ["audit", "--from-dev-user", "x", "--allow-loopback"],
        ["audit", "--from-sitemap", f"{ORIGIN}/sitemap.xml", "--allow-loopback"],
        ["pairs", "--from-dev-user", "x", "--allow-loopback"],
    ],
)
def test_loopback_is_refused_with_a_url_source(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    """V3 f6: pages Cernis did not choose must not reach this machine's services."""
    site = Site()
    scripted(monkeypatch, site)

    assert main(argv) == 2
    assert "--allow-loopback cannot be combined" in capsys.readouterr().err
    assert site.requests == []
