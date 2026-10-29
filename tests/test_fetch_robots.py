"""Tests for robots.txt handling: RFC 9309 status rules, once per origin, and redirects."""

import ssl
from pathlib import Path

import httpx
import pytest
from fetch_support import Site, make_fetcher, redirect, respond

from cernis.fetch import RobotsBasis
from cernis.fetch.rfc9309 import MATCHER_VERSION
from cernis.fetch.robots import product_token, robots_url_for
from cernis.model import ErrorKind

ROBOTS = "https://example.com/robots.txt"
PAGE = "https://example.com/post"
PRIVATE = "https://example.com/private/post"


def _tls_failure(request: httpx.Request) -> httpx.Response:
    """Fail the way httpx does on a bad certificate.

    :param request: The request.
    :return: Never returns.
    :raises ssl.SSLCertVerificationError: Raised and caught inside, as the cause.
    :raises httpx.ConnectError: Always, caused by an SSL error.
    """
    try:
        raise ssl.SSLCertVerificationError("certificate verify failed")
    except ssl.SSLError as exc:
        raise httpx.ConnectError(str(exc)) from exc


def test_rules_are_applied_and_a_disallowed_url_is_not_fetched(tmp_path: Path) -> None:
    """A disallowed URL is never requested; the result says so and cites the robots receipt."""
    site = Site()
    site.add(ROBOTS, respond(200, b"User-agent: *\nDisallow: /private/\n"))
    site.add(PRIVATE, respond(200))

    result = make_fetcher(site, tmp_path).fetch(PRIVATE)

    assert result.receipts == ()
    assert result.final is None
    assert result.body is None
    assert result.disallowed_url == PRIVATE
    assert site.urls() == [ROBOTS]
    (robots_receipt,) = result.robots_receipts
    assert (robots_receipt.requested_url, robots_receipt.status_code) == (ROBOTS, 200)
    (decision,) = result.robots
    assert (decision.url, decision.robots_url, decision.allowed) == (PRIVATE, ROBOTS, False)
    assert (decision.basis, decision.receipt_id) == (RobotsBasis.RULES, robots_receipt.id)


def test_an_allowed_url_is_fetched_with_its_decision(tmp_path: Path) -> None:
    """An allowed URL is fetched, and the decision is recorded."""
    site = Site()
    site.add(ROBOTS, respond(200, b"User-agent: *\nDisallow: /private/\n"))
    site.add(PAGE, respond(200))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert [r.status_code for r in result.receipts] == [200]
    assert [(d.allowed, d.basis) for d in result.robots] == [(True, RobotsBasis.RULES)]
    assert result.disallowed_url is None


@pytest.mark.parametrize(
    ("rules", "allowed"),
    [
        (b"User-agent: Cernis\nDisallow: /\n\nUser-agent: *\nAllow: /\n", False),
        (b"User-agent: cernis\nDisallow: /\n", False),
        (b"User-agent: OtherBot\nDisallow: /\n", True),
        (b"User-agent: *\nDisallow: /\n\nUser-agent: Cernis\nAllow: /\n", True),
        (b"", True),
        (b"\xef\xbb\xbfUser-agent: *\nDisallow: /\n", False),
        (b"User-agent: *\r\nDisallow: /post\r\n", False),
    ],
)
def test_rules_apply_to_cernis_own_user_agent(tmp_path: Path, rules: bytes, allowed: bool) -> None:
    """The Cernis product token is matched, case-insensitively; a BOM and CRLF are tolerated."""
    site = Site()
    site.add(ROBOTS, respond(200, rules))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.robots[0].allowed is allowed
    assert (result.disallowed_url is None) is allowed


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 451])
def test_a_4xx_robots_txt_allows_everything(tmp_path: Path, status: int) -> None:
    """RFC 9309 section 2.3.1.3: an unavailable robots.txt allows everything."""
    site = Site()
    site.add(ROBOTS, respond(status))
    site.add(PAGE, respond(200))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert [(d.allowed, d.basis) for d in result.robots] == [(True, RobotsBasis.UNAVAILABLE)]
    assert [r.status_code for r in result.receipts] == [200]


@pytest.mark.parametrize(
    ("reply", "attempts"),
    [
        (respond(500), 1),
        (respond(502), 1),
        (respond(503), 3),
        (respond(429), 3),
        (httpx.ConnectTimeout("slow"), 1),
        (httpx.ConnectError("refused"), 1),
        (_tls_failure, 1),
    ],
)
def test_an_unreachable_robots_txt_disallows_everything(
    tmp_path: Path, reply: httpx.Response | Exception, attempts: int
) -> None:
    """RFC 9309 section 2.3.1.4: 5xx or no answer disallows everything; so does a lasting 429."""
    site = Site()
    site.add(ROBOTS, reply)  # type: ignore[arg-type]
    site.add(PAGE, respond(200))

    result = make_fetcher(site, tmp_path, min_interval=0).fetch(PAGE)

    assert result.receipts == ()
    assert result.disallowed_url == PAGE
    assert PAGE not in site.urls()
    assert [(d.allowed, d.basis) for d in result.robots] == [(False, RobotsBasis.UNREACHABLE)]
    assert len(result.robots_receipts) == attempts
    assert result.robots[0].receipt_id == result.robots_receipts[-1].id


def test_robots_txt_failure_kinds_are_on_its_receipt(tmp_path: Path) -> None:
    """The robots.txt receipt says why it was unreachable."""
    site = Site()
    site.add(ROBOTS, _tls_failure)

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.robots_receipts[0].error_kind is ErrorKind.TLS


def test_a_robots_txt_503_that_clears_on_retry_is_used(tmp_path: Path) -> None:
    """robots.txt is retried like any fetch; the decision rests on the last attempt."""
    site = Site()
    site.add(ROBOTS, respond(503), respond(200, b"User-agent: *\nDisallow: /\n"))

    result = make_fetcher(site, tmp_path, min_interval=0).fetch(PAGE)

    assert [r.status_code for r in result.robots_receipts] == [503, 200]
    assert result.robots[0].receipt_id == result.robots_receipts[1].id
    assert result.robots[0].basis is RobotsBasis.RULES


def test_a_redirected_robots_txt_is_followed(tmp_path: Path) -> None:
    """RFC 9309 section 2.3.1.2: robots.txt redirects are followed."""
    site = Site()
    site.add(ROBOTS, redirect("https://cdn.example/robots.txt"))
    site.add("https://cdn.example/robots.txt", respond(200, b"User-agent: *\nDisallow: /\n"))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    (receipt,) = result.robots_receipts
    assert receipt.redirect_chain == (ROBOTS,)
    assert result.disallowed_url == PAGE


def test_a_robots_txt_redirect_to_a_page_is_not_followed(tmp_path: Path) -> None:
    """A robots.txt redirect is followed only to another /robots.txt, never to a page."""
    site = Site()
    site.add(ROBOTS, redirect("https://other.example/secret"))
    site.add(PAGE, respond(200))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert "https://other.example/secret" not in site.urls()
    assert result.robots_receipts[0].status_code == 301
    assert result.robots[0].basis is RobotsBasis.UNREACHABLE
    assert result.disallowed_url == PAGE


def test_a_robots_txt_with_too_many_redirects_disallows_everything(tmp_path: Path) -> None:
    """A robots.txt redirect loop is unreachable."""
    site = Site()
    site.add(ROBOTS, redirect(ROBOTS))

    result = make_fetcher(site, tmp_path, min_interval=0).fetch(PAGE)

    assert result.robots_receipts[0].error_kind is ErrorKind.TOO_MANY_REDIRECTS
    assert result.robots[0].basis is RobotsBasis.UNREACHABLE


def test_a_robots_txt_redirect_that_cannot_be_followed_disallows_everything(
    tmp_path: Path,
) -> None:
    """A 3xx robots.txt with no usable Location is neither rules nor a 4xx."""
    site = Site()
    site.add(ROBOTS, respond(302))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.robots[0].basis is RobotsBasis.UNREACHABLE


def test_robots_txt_is_fetched_once_per_origin_per_run(tmp_path: Path) -> None:
    """Two pages on one origin share one robots.txt fetch; another origin gets its own."""
    site = Site()
    fetcher = make_fetcher(site, tmp_path)

    fetcher.fetch(PAGE)
    fetcher.fetch("https://example.com/other")
    fetcher.fetch("http://example.com/post")
    fetcher.fetch("https://example.com:8443/post")

    robots_requests = [url for url in site.urls() if url.endswith("/robots.txt")]
    assert robots_requests == [
        ROBOTS,
        "http://example.com/robots.txt",
        "https://example.com:8443/robots.txt",
    ]


def test_a_new_run_fetches_robots_txt_again(tmp_path: Path) -> None:
    """Once per run: a new fetcher does not reuse the last run's decision."""
    site = Site()

    make_fetcher(site, tmp_path).fetch(PAGE)
    make_fetcher(site, tmp_path).fetch(PAGE)

    assert site.urls().count(ROBOTS) == 2


def test_a_redirect_to_a_disallowed_url_is_not_followed(tmp_path: Path) -> None:
    """Each redirect target is checked against its own origin's robots.txt first."""
    site = Site()
    target = "https://other.example/private"
    site.add(PAGE, redirect(target))
    site.add("https://other.example/robots.txt", respond(200, b"User-agent: *\nDisallow: /\n"))
    site.add(target, respond(200))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    (receipt,) = result.receipts
    assert (receipt.status_code, receipt.final_url, receipt.redirect_chain) == (301, PAGE, ())
    assert result.disallowed_url == target
    assert target not in site.urls()
    assert [(d.url, d.allowed) for d in result.robots] == [(PAGE, True), (target, False)]
    assert [r.requested_url for r in result.robots_receipts] == [
        ROBOTS,
        "https://other.example/robots.txt",
    ]


def test_a_line_cut_off_at_the_limit_is_not_a_rule(tmp_path: Path) -> None:
    """When robots.txt is cut off, its last, partial line is dropped before parsing."""
    site = Site()
    rules = b"User-agent: *\nDisallow: /a\nDisallow: /post-archive\n"
    site.add(ROBOTS, respond(200, rules))
    cut = len(b"User-agent: *\nDisallow: /a\nDisallow: /po")

    result = make_fetcher(site, tmp_path, max_body_bytes=cut).fetch(PAGE)

    assert result.robots_receipts[0].body_truncated_at == cut
    assert result.robots[0].allowed


def test_an_oversized_robots_txt_is_applied_up_to_the_limit(tmp_path: Path) -> None:
    """RFC 9309 section 2.5: rules within the size limit apply; the rest may be ignored."""
    site = Site()
    rules = b"User-agent: *\nDisallow: /post\n" + b"# padding\n" * 50
    site.add(ROBOTS, respond(200, rules))

    result = make_fetcher(site, tmp_path, max_body_bytes=64).fetch(PAGE)

    assert result.robots_receipts[0].body_truncated_at == 64
    assert result.robots[0].basis is RobotsBasis.RULES
    assert result.disallowed_url == PAGE


@pytest.mark.parametrize(
    ("url", "robots_url"),
    [
        ("https://example.com/a/b?q=1#frag", "https://example.com/robots.txt"),
        ("http://EXAMPLE.com/a", "http://example.com/robots.txt"),
        ("https://example.com:8443/a", "https://example.com:8443/robots.txt"),
        ("https://example.com:443/a", "https://example.com/robots.txt"),
        ("https://user:pw@example.com/a", "https://example.com/robots.txt"),
    ],
)
def test_robots_url_is_per_origin(url: str, robots_url: str) -> None:
    """robots.txt lives at the root of each scheme, host, and port."""
    assert robots_url_for(url) == robots_url


# Matching is Cernis's own (rfc9309.py), so these give the same answer on
# every supported Python. tests/test_fetch_rfc9309.py covers the matcher in
# detail; these check the fetcher uses it.


def test_the_longest_match_wins(tmp_path: Path) -> None:
    """RFC 9309: the most specific rule wins, so a longer Allow beats a shorter Disallow."""
    site = Site()
    site.add(ROBOTS, respond(200, b"User-agent: *\nDisallow: /\nAllow: /post\n"))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.robots[0].allowed
    assert result.robots[0].rule == "Allow: /post"


@pytest.mark.parametrize(
    ("rule", "url"),
    [("/*st", PAGE), ("/*.pdf$", "https://example.com/paper.pdf")],
)
def test_wildcards_are_honored(tmp_path: Path, rule: str, url: str) -> None:
    """RFC 9309: ``*`` matches any sequence of characters, and ``$`` ends the pattern."""
    site = Site()
    site.add(ROBOTS, respond(200, f"User-agent: *\nDisallow: {rule}\n".encode()))

    result = make_fetcher(site, tmp_path).fetch(url)

    assert not result.robots[0].allowed


def test_a_substring_of_cernis_is_not_cernis(tmp_path: Path) -> None:
    """A group for ``e`` does not apply to Cernis (urllib.robotparser matched substrings)."""
    site = Site()
    site.add(ROBOTS, respond(200, b"User-agent: e\nDisallow: /\n"))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.robots[0].allowed


def test_rules_match_the_path_as_sent(tmp_path: Path) -> None:
    """A rule for an encoded path matches the URL httpx sends, however it was typed."""
    site = Site()
    site.add(ROBOTS, respond(200, "User-agent: *\nDisallow: /caf\u00e9\n".encode()))

    result = make_fetcher(site, tmp_path).fetch("https://example.com/caf%C3%A9/menu")

    assert not result.robots[0].allowed
    assert result.robots[0].rule == "Disallow: /caf\u00e9"


def test_each_decision_carries_the_matcher_version(tmp_path: Path) -> None:
    """A decision says which matcher version made it, so a matcher change is visible."""
    site = Site()
    site.add(ROBOTS, respond(200, b"User-agent: *\nDisallow: /private\n"))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.robots[0].matcher_version == MATCHER_VERSION
    assert result.robots[0].rule is None


def test_the_product_token_is_the_user_agent_before_the_slash() -> None:
    """Cernis's product token is ``Cernis``."""
    assert product_token("Cernis/0.1.0 (+https://github.com/kenwalger/cernis)") == "Cernis"


def test_a_429_robots_txt_disallows_everything(tmp_path: Path) -> None:
    """ADR-006: a robots.txt still answering 429 after retries is unreachable, not unavailable.

    RFC 9309 would allow everything for any 4xx; Cernis departs from it here, on purpose.
    """
    site = Site()
    site.add(ROBOTS, respond(429, headers={"retry-after": "1"}))
    site.add(PAGE, respond(200))

    result = make_fetcher(site, tmp_path, min_interval=0).fetch(PAGE)

    assert [r.status_code for r in result.robots_receipts] == [429, 429, 429]
    assert [r.header("retry-after") for r in result.robots_receipts] == ["1", "1", "1"]
    assert [(d.allowed, d.basis) for d in result.robots] == [(False, RobotsBasis.UNREACHABLE)]
    assert result.disallowed_url == PAGE
    assert PAGE not in site.urls()
