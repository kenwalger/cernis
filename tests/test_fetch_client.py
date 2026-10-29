"""Tests for the fetcher: receipts, redirects, retries, errors, body limits, and pacing."""

import gzip
import hashlib
import itertools
import re
import ssl
import zlib
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest
from fetch_support import FIXED_NOW, ChunkStream, FakeTime, Site, make_fetcher, redirect, respond

from cernis import REPOSITORY_URL, __version__
from cernis.fetch import USER_AGENT, FetchConfig, Fetcher, FetchError
from cernis.fetch.client import parse_retry_after
from cernis.model import ErrorKind

PAGE = "https://example.com/post"
OTHER = "https://other.example/post"


def sha(data: bytes) -> str:
    """Hash bytes the way receipts do.

    :param data: The bytes.
    :return: The lowercase hex SHA-256.
    """
    return hashlib.sha256(data).hexdigest()


# A plain fetch


def test_200_produces_a_receipt_with_the_raw_facts(tmp_path: Path) -> None:
    """A 200 records the URL, status, time, body hash, recorded headers, version, and agent."""
    site = Site()
    body = b"<html>post</html>"
    site.add(PAGE, respond(200, body, {"content-type": "text/html", "server": "nginx"}))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    (receipt,) = result.receipts
    assert receipt.requested_url == PAGE
    assert receipt.final_url == PAGE
    assert receipt.redirect_chain == ()
    assert receipt.status_code == 200
    assert receipt.error_kind is ErrorKind.NONE
    assert receipt.fetched_at == FIXED_NOW
    assert receipt.body_sha256 == sha(body)
    assert receipt.body_truncated_at is None
    assert receipt.headers == (("content-type", "text/html"),)
    assert receipt.cernis_version == __version__
    assert receipt.user_agent == USER_AGENT
    assert result.body == body
    assert result.final is receipt
    assert result.disallowed_url is None


def test_user_agent_is_honest_and_sent_on_every_request(tmp_path: Path) -> None:
    """The user agent names Cernis, its version, and the repository, on robots.txt too."""
    site = Site()
    site.add(PAGE, respond(200))

    make_fetcher(site, tmp_path).fetch(PAGE)

    assert f"Cernis/{__version__} (+{REPOSITORY_URL})" == USER_AGENT
    assert re.fullmatch(r"Cernis/\S+ \(\+https://github\.com/kenwalger/cernis\)", USER_AGENT)
    assert site.urls() == ["https://example.com/robots.txt", PAGE]
    assert [request.headers["user-agent"] for request in site.requests] == [USER_AGENT] * 2


def test_only_the_recorded_headers_are_kept_and_repeats_are_combined(tmp_path: Path) -> None:
    """The receipt keeps the DESIGN.md header subset, joining a repeated header's values."""
    site = Site()
    headers = [
        ("Content-Type", "text/html"),
        ("ETag", '"v1"'),
        ("Last-Modified", "Wed, 28 Oct 2026 10:00:00 GMT"),
        ("X-Robots-Tag", "noindex"),
        ("X-Robots-Tag", "nofollow"),
        ("Set-Cookie", "session=1"),
        ("Server", "nginx"),
    ]
    site.add(PAGE, respond(200, b"x", headers))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert receipt.headers == (
        ("content-type", "text/html"),
        ("etag", '"v1"'),
        ("last-modified", "Wed, 28 Oct 2026 10:00:00 GMT"),
        ("x-robots-tag", "noindex, nofollow"),
    )


def test_receipt_ids_are_unique_within_a_run(tmp_path: Path) -> None:
    """Receipt ids count up across fetches, robots.txt included."""
    site = Site()
    site.add(PAGE, respond(200))
    site.add(PAGE + "/2", respond(200))
    fetcher = make_fetcher(site, tmp_path)

    first = fetcher.fetch(PAGE)
    second = fetcher.fetch(PAGE + "/2")

    assert [r.id for r in first.robots_receipts + first.receipts] == ["r-001", "r-002"]
    assert [r.id for r in second.receipts] == ["r-003"]
    assert second.robots_receipts == first.robots_receipts


@pytest.mark.parametrize("status", [401, 403, 404, 410, 500, 502])
def test_error_statuses_are_one_receipt_with_the_body_hashed(tmp_path: Path, status: int) -> None:
    """A 4xx or 5xx (other than 429 and 503) is a response: recorded once, not retried."""
    site = Site()
    site.add(PAGE, respond(status, b"nope"))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    (receipt,) = result.receipts
    assert (receipt.status_code, receipt.error_kind) == (status, ErrorKind.NONE)
    assert receipt.body_sha256 == sha(b"nope")
    assert not result.rate_limited


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/post",
        "example.com/post",
        "/post",
        "https://user:secret@example.com/post",
        "https://[::1/",
    ],
)
def test_urls_that_cannot_be_fetched_are_refused_before_any_request(
    tmp_path: Path, url: str
) -> None:
    """Only absolute http or https URLs with no credentials are fetched."""
    site = Site()

    with pytest.raises(FetchError):
        make_fetcher(site, tmp_path).fetch(url)

    assert site.requests == []


def test_cookies_are_never_stored_or_sent(tmp_path: Path) -> None:
    """A cookie set by one response is not sent with the next request."""
    site = Site()
    site.add(PAGE, respond(200, headers={"set-cookie": "session=abc; Path=/"}))
    fetcher = make_fetcher(site, tmp_path)

    fetcher.fetch(PAGE)
    fetcher.fetch(PAGE)

    assert all("cookie" not in request.headers for request in site.requests)


def test_proxy_and_netrc_settings_from_the_environment_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With proxy variables set, requests still go straight to the transport."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    netrc = tmp_path / "netrc"
    netrc.write_text("machine example.com login me password secret\n", encoding="utf-8")
    monkeypatch.setenv("NETRC", str(netrc))
    site = Site()
    site.add(PAGE, respond(200))

    receipt = make_fetcher(site, tmp_path / "cache").fetch(PAGE).receipts[0]

    assert receipt.status_code == 200
    assert all("authorization" not in request.headers for request in site.requests)


# Redirects


def test_redirect_chain_records_every_hop(tmp_path: Path) -> None:
    """Each URL that redirected is in the chain, in order; relative targets are resolved."""
    site = Site()
    site.add(PAGE, redirect("https://example.com/post/"))
    site.add("https://example.com/post/", redirect("/final", 302))
    site.add("https://example.com/final", respond(200, b"done"))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    (receipt,) = result.receipts
    assert receipt.redirect_chain == (PAGE, "https://example.com/post/")
    assert receipt.final_url == "https://example.com/final"
    assert receipt.status_code == 200
    assert receipt.body_sha256 == sha(b"done")
    assert result.body == b"done"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_redirect_status_is_followed(tmp_path: Path, status: int) -> None:
    """301, 302, 303, 307, and 308 are all followed."""
    site = Site()
    site.add(PAGE, redirect("https://example.com/new", status))
    site.add("https://example.com/new", respond(200))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert (receipt.redirect_chain, receipt.status_code) == ((PAGE,), 200)


def _redirect_ladder(site: Site, steps: int) -> str:
    """Route a chain of ``steps`` redirects ending in a 200.

    :param site: The scripted web.
    :param steps: How many redirects.
    :return: The last URL, which answers 200.
    """
    urls = [f"https://example.com/{n}" for n in range(steps + 1)]
    for here, there in itertools.pairwise(urls):
        site.add(here, redirect(there))
    site.add(urls[-1], respond(200))
    return urls[-1]


def test_ten_redirects_are_followed(tmp_path: Path) -> None:
    """The default limit allows exactly ten redirects."""
    site = Site()
    last = _redirect_ladder(site, 10)

    receipt = make_fetcher(site, tmp_path).fetch("https://example.com/0").receipts[0]

    assert receipt.final_url == last
    assert len(receipt.redirect_chain) == 10


def test_an_eleventh_redirect_is_too_many(tmp_path: Path) -> None:
    """One redirect past the limit ends the attempt with the whole chain and no response."""
    site = Site()
    _redirect_ladder(site, 11)

    receipt = make_fetcher(site, tmp_path).fetch("https://example.com/0").receipts[0]

    assert receipt.error_kind is ErrorKind.TOO_MANY_REDIRECTS
    assert receipt.redirect_chain == tuple(f"https://example.com/{n}" for n in range(11))
    assert (receipt.status_code, receipt.final_url, receipt.body_sha256) == (None, None, None)
    assert "https://example.com/11" not in site.urls()


def test_redirect_limit_is_configurable_and_catches_loops(tmp_path: Path) -> None:
    """A loop stops at the configured limit."""
    site = Site()
    site.add(PAGE, redirect(PAGE + "/"))
    site.add(PAGE + "/", redirect(PAGE))

    receipt = make_fetcher(site, tmp_path, max_redirects=2).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.TOO_MANY_REDIRECTS
    assert receipt.redirect_chain == (PAGE, PAGE + "/", PAGE)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"location": "   "},
        {"location": "ftp://example.com/file"},
        {"location": "mailto:me@example.com"},
        {"location": "https://user:pw@example.com/"},
        {"location": "https://[::1/"},
    ],
)
def test_a_redirect_that_cannot_be_followed_is_the_final_response(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    """A missing, unusable, or credential-bearing Location is recorded, not followed."""
    site = Site()
    site.add(PAGE, respond(302, headers=headers))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert (receipt.status_code, receipt.final_url, receipt.redirect_chain) == (302, PAGE, ())
    assert site.urls() == ["https://example.com/robots.txt", PAGE]


def test_a_redirect_with_two_locations_is_not_followed(tmp_path: Path) -> None:
    """Two Location headers are ambiguous, so neither is followed."""
    site = Site()
    site.add(PAGE, respond(301, headers=[("location", "/a"), ("location", "/b")]))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert (receipt.status_code, receipt.redirect_chain) == (301, ())


def test_an_error_after_a_redirect_keeps_the_chain(tmp_path: Path) -> None:
    """A hop that fails still leaves the hops before it on the receipt."""
    site = Site()
    site.add(PAGE, redirect(OTHER))
    site.add(OTHER, httpx.ConnectTimeout("slow"))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.TIMEOUT
    assert receipt.redirect_chain == (PAGE,)
    assert receipt.final_url == OTHER


# Errors with no response


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("connect"),
        httpx.ReadTimeout("read"),
        httpx.WriteTimeout("write"),
        httpx.PoolTimeout("pool"),
    ],
)
def test_timeouts_are_timeout(tmp_path: Path, error: Exception) -> None:
    """Every httpx timeout is TIMEOUT, naming the URL, with no status, headers, or hash."""
    site = Site()
    site.add(PAGE, error)

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.TIMEOUT
    assert (receipt.status_code, receipt.headers, receipt.body_sha256) == (None, (), None)
    assert receipt.final_url == PAGE


def test_a_timeout_while_reading_the_body_is_timeout(tmp_path: Path) -> None:
    """A body that stops arriving is TIMEOUT, keeping the status and headers that did arrive."""
    site = Site()
    stream = ChunkStream([b"part"], fail_with=httpx.ReadTimeout("stalled"))
    site.add(
        PAGE,
        lambda request: httpx.Response(
            200, stream=stream, headers={"content-type": "text/html"}, request=request
        ),
    )

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.TIMEOUT
    assert (receipt.status_code, receipt.final_url, receipt.body_sha256) == (200, PAGE, None)
    assert receipt.header("content-type") == "text/html"


def test_a_connection_reset_while_reading_the_body_keeps_the_status(tmp_path: Path) -> None:
    """A body cut off by the connection is CONNECTION, with the status that arrived."""
    site = Site()
    stream = ChunkStream([b"part"], fail_with=httpx.ReadError("reset"))
    site.add(PAGE, lambda request: httpx.Response(404, stream=stream, request=request))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert (receipt.error_kind, receipt.status_code) == (ErrorKind.CONNECTION, 404)


def test_total_timeout_is_checked_once_the_headers_arrive(tmp_path: Path) -> None:
    """A redirect whose headers took longer than total_timeout is TIMEOUT, not followed."""
    site = Site()
    time = FakeTime()

    def slow_redirect(request: httpx.Request) -> httpx.Response:
        time.now += 100
        return httpx.Response(301, headers={"location": OTHER}, request=request)

    site.add(PAGE, slow_redirect)

    result = make_fetcher(site, tmp_path, time, total_timeout=30).fetch(PAGE)

    (receipt,) = result.receipts
    assert (receipt.error_kind, receipt.status_code, receipt.final_url) == (
        ErrorKind.TIMEOUT,
        301,
        PAGE,
    )
    assert OTHER not in site.urls()


def test_a_body_slower_than_the_total_timeout_is_timeout(tmp_path: Path) -> None:
    """A server that keeps sending, slowly, cannot hold a request past total_timeout."""
    site = Site()
    time = FakeTime()

    def tick() -> None:
        time.now += 10

    stream = ChunkStream([b"a"] * 20, before_chunk=tick)
    site.add(PAGE, lambda request: httpx.Response(200, stream=stream, request=request))

    receipt = make_fetcher(site, tmp_path, time, total_timeout=30).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.TIMEOUT
    assert stream.delivered < 20


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("refused"),
        httpx.ReadError("reset"),
        httpx.RemoteProtocolError("garbage"),
        httpx.DecodingError("bad gzip"),
    ],
)
def test_connection_failures_are_connection(tmp_path: Path, error: Exception) -> None:
    """A failure to get or read a response, other than a timeout or TLS, is CONNECTION."""
    site = Site()
    site.add(PAGE, error)

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.CONNECTION


@pytest.mark.parametrize(
    "cause",
    [
        ssl.SSLCertVerificationError("certificate verify failed"),
        ssl.SSLError("wrong version number"),
        ssl.SSLEOFError("eof"),
    ],
)
def test_tls_failures_are_tls(tmp_path: Path, cause: ssl.SSLError) -> None:
    """A failure caused by an SSL error, as httpx chains it, is TLS."""
    site = Site()

    def fail(request: httpx.Request) -> httpx.Response:
        try:
            raise cause
        except ssl.SSLError as exc:
            raise httpx.ConnectError(str(exc)) from exc

    site.add(PAGE, fail)

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert receipt.error_kind is ErrorKind.TLS


# Body size


def test_a_body_over_the_limit_has_no_hash_and_records_the_limit(tmp_path: Path) -> None:
    """ADR-003: reading stops at the limit; the receipt says so and claims no hash."""
    site = Site()
    site.add(PAGE, respond(200, b"x" * 11))

    result = make_fetcher(site, tmp_path, max_body_bytes=10).fetch(PAGE)

    (receipt,) = result.receipts
    assert (receipt.status_code, receipt.body_sha256, receipt.body_truncated_at) == (200, None, 10)
    assert result.body == b"x" * 10


def test_a_body_exactly_at_the_limit_is_read_whole(tmp_path: Path) -> None:
    """A body of exactly max_body_bytes is hashed."""
    site = Site()
    site.add(PAGE, respond(200, b"x" * 10))

    receipt = make_fetcher(site, tmp_path, max_body_bytes=10).fetch(PAGE).receipts[0]

    assert (receipt.body_sha256, receipt.body_truncated_at) == (sha(b"x" * 10), None)


def test_reading_stops_at_the_limit(tmp_path: Path) -> None:
    """The rest of an oversized body is never read."""
    site = Site()
    stream = ChunkStream([b"x" * 4] * 100)
    site.add(PAGE, lambda request: httpx.Response(200, stream=stream, request=request))

    make_fetcher(site, tmp_path, max_body_bytes=10).fetch(PAGE)

    assert stream.delivered == 3


def test_the_default_body_limit_is_five_megabytes() -> None:
    """DESIGN.md Session 3: the default maximum body is 5 MB."""
    assert FetchConfig().max_body_bytes == 5 * 1024 * 1024


# Retries


def test_a_429_is_retried_with_backoff(tmp_path: Path) -> None:
    """A 429 with no Retry-After waits backoff_base, then tries again; each attempt is a receipt."""
    site = Site()
    site.add(PAGE, respond(429), respond(200, b"ok"))
    time = FakeTime()

    result = make_fetcher(site, tmp_path, time, min_interval=0).fetch(PAGE)

    assert [r.status_code for r in result.receipts] == [429, 200]
    assert [r.id for r in result.receipts] == ["r-002", "r-003"]
    assert time.sleeps == [1.0]
    assert result.body == b"ok"
    assert not result.rate_limited


def test_a_429_that_never_clears_is_rate_limited_after_three_attempts(tmp_path: Path) -> None:
    """Three attempts in all, with exponential backoff; the result is the input to RATE_LIMITED."""
    site = Site()
    site.add(PAGE, respond(429))
    time = FakeTime()

    result = make_fetcher(site, tmp_path, time, min_interval=0).fetch(PAGE)

    assert [r.status_code for r in result.receipts] == [429, 429, 429]
    assert time.sleeps == [1.0, 2.0]
    assert result.rate_limited


def test_backoff_is_capped(tmp_path: Path) -> None:
    """The computed wait never exceeds backoff_cap."""
    site = Site()
    site.add(PAGE, respond(429))
    time = FakeTime()

    make_fetcher(
        site, tmp_path, time, min_interval=0, backoff_base=40, backoff_cap=60, max_attempts=4
    ).fetch(PAGE)

    assert time.sleeps == [40.0, 60.0, 60.0]


@pytest.mark.parametrize(
    ("retry_after", "wait"),
    [
        ("5", 5.0),
        ("0", 0.0),
        (format_datetime(FIXED_NOW + timedelta(seconds=30), usegmt=True), 30.0),
        (format_datetime(FIXED_NOW - timedelta(seconds=30), usegmt=True), 0.0),
    ],
)
def test_retry_after_is_honored(tmp_path: Path, retry_after: str, wait: float) -> None:
    """Retry-After, in seconds or as an HTTP date, sets the wait."""
    site = Site()
    site.add(PAGE, respond(429, headers={"retry-after": retry_after}), respond(200))
    time = FakeTime()

    result = make_fetcher(site, tmp_path, time, min_interval=0).fetch(PAGE)

    assert time.sleeps == [wait]
    assert result.receipts[0].header("retry-after") == retry_after


@pytest.mark.parametrize("retry_after", ["61", "99999999999999999999999", "1" * 5000])
def test_a_retry_after_beyond_the_cap_stops_at_once(tmp_path: Path, retry_after: str) -> None:
    """A Retry-After longer than backoff_cap is not waited for; the 429 stands."""
    site = Site()
    site.add(PAGE, respond(429, headers={"retry-after": retry_after}), respond(200))
    time = FakeTime()

    result = make_fetcher(site, tmp_path, time, min_interval=0).fetch(PAGE)

    assert [r.status_code for r in result.receipts] == [429]
    assert time.sleeps == []
    assert result.rate_limited


def test_an_unreadable_retry_after_falls_back_to_backoff(tmp_path: Path) -> None:
    """A Retry-After that is neither seconds nor a date is ignored."""
    site = Site()
    site.add(PAGE, respond(429, headers={"retry-after": "soon"}), respond(200))
    time = FakeTime()

    make_fetcher(site, tmp_path, time, min_interval=0).fetch(PAGE)

    assert time.sleeps == [1.0]


def test_a_503_is_retried_and_one_that_never_clears_is_not_rate_limited(tmp_path: Path) -> None:
    """503 is retried like 429, but a lasting 503 is a server failure, not rate limiting."""
    site = Site()
    site.add(PAGE, respond(503, headers={"retry-after": "2"}))
    time = FakeTime()

    result = make_fetcher(site, tmp_path, time, min_interval=0).fetch(PAGE)

    assert [r.status_code for r in result.receipts] == [503, 503, 503]
    assert time.sleeps == [2.0, 2.0]
    assert not result.rate_limited


def test_a_retry_starts_again_from_the_requested_url(tmp_path: Path) -> None:
    """Each attempt follows the redirects again, so each receipt stands alone."""
    site = Site()
    site.add(PAGE, redirect(PAGE + "/"))
    site.add(PAGE + "/", respond(429), respond(200))

    result = make_fetcher(site, tmp_path, min_interval=0).fetch(PAGE)

    assert [(r.redirect_chain, r.status_code) for r in result.receipts] == [
        ((PAGE,), 429),
        ((PAGE,), 200),
    ]


def test_max_attempts_one_never_retries(tmp_path: Path) -> None:
    """max_attempts counts the first attempt."""
    site = Site()
    site.add(PAGE, respond(429))

    result = make_fetcher(site, tmp_path, max_attempts=1).fetch(PAGE)

    assert len(result.receipts) == 1


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        (None, None),
        ("", None),
        ("soon", None),
        ("-5", None),
        ("1.5", None),
        (" 7 ", 7.0),
        ("Thu, 29 Oct 2026 12:01:00 GMT", 60.0),
        ("Thu, 29 Oct 2026 11:00:00 GMT", 0.0),
    ],
)
def test_parse_retry_after(value: str | None, seconds: float | None) -> None:
    """Retry-After is delay seconds or an HTTP date; anything else is unusable."""
    assert parse_retry_after(value, FIXED_NOW) == seconds


# Pacing


def test_requests_to_one_host_are_paced(tmp_path: Path) -> None:
    """robots.txt and the page are a second apart by default."""
    site = Site()
    site.add(PAGE, respond(200))
    time = FakeTime()

    make_fetcher(site, tmp_path, time).fetch(PAGE)

    assert time.sleeps == [1.0]


def test_requests_to_different_hosts_are_not_paced_against_each_other(tmp_path: Path) -> None:
    """Pacing is per host."""
    site = Site()
    site.add(PAGE, redirect(OTHER))
    site.add(OTHER, respond(200))
    time = FakeTime()
    fetcher = make_fetcher(site, tmp_path, time)

    fetcher.fetch(PAGE)

    # example.com: robots.txt, then the page (one wait); other.example:
    # robots.txt, then the page (one wait). No wait between the hosts.
    assert time.sleeps == [1.0, 1.0]


def test_pacing_interval_is_configurable(tmp_path: Path) -> None:
    """min_interval sets the gap; zero turns pacing off."""
    site = Site()
    site.add(PAGE, respond(200))
    slow, off = FakeTime(), FakeTime()

    make_fetcher(site, tmp_path, slow, min_interval=2.5).fetch(PAGE)
    make_fetcher(site, tmp_path, off, min_interval=0).fetch(PAGE)

    assert slow.sleeps == [2.5]
    assert off.sleeps == []


def test_a_retry_wait_counts_toward_pacing(tmp_path: Path) -> None:
    """After a retry wait at least as long as the interval, no extra pacing wait is added."""
    site = Site()
    site.add(PAGE, respond(429, headers={"retry-after": "3"}), respond(200))
    time = FakeTime()

    make_fetcher(site, tmp_path, time).fetch(PAGE)

    assert time.sleeps == [1.0, 3.0]


# Configuration


@pytest.mark.parametrize(
    "setting",
    [
        {"connect_timeout": 0},
        {"read_timeout": -1},
        {"total_timeout": 0},
        {"max_body_bytes": 0},
        {"max_redirects": -1},
        {"min_interval": -0.1},
        {"max_attempts": 0},
        {"backoff_base": -1},
        {"backoff_cap": -1},
    ],
)
def test_out_of_range_settings_are_rejected(setting: dict[str, float]) -> None:
    """Each setting is checked when the configuration is built."""
    with pytest.raises(ValueError, match=next(iter(setting))):
        FetchConfig(**setting)  # type: ignore[arg-type]


def test_the_fetcher_closes_as_a_context_manager(tmp_path: Path) -> None:
    """Leaving the with block closes the HTTP client."""
    site = Site()
    with make_fetcher(site, tmp_path) as fetcher:
        pass

    with pytest.raises(RuntimeError):
        fetcher.fetch(PAGE)


def test_fetched_at_is_when_the_first_request_was_sent_after_pacing(tmp_path: Path) -> None:
    """The time on a receipt comes after the pacing wait, not before it."""
    site = Site()
    site.add(PAGE, respond(200))
    time = FakeTime()
    fetcher = Fetcher(
        FetchConfig(cache_dir=tmp_path),
        transport=httpx.MockTransport(site.handler),
        clock=time.clock,
        sleep=time.sleep,
        now=lambda: FIXED_NOW + timedelta(seconds=time.now),
    )

    result = fetcher.fetch(PAGE)

    gap = result.receipts[0].fetched_at - result.robots_receipts[0].fetched_at
    assert gap == timedelta(seconds=1)


def test_the_url_is_requested_and_recorded_in_its_normalized_form(tmp_path: Path) -> None:
    """Robots.txt, the request, and the receipt all use the URL httpx sends."""
    site = Site()
    site.add("https://example.com/robots.txt", respond(200, b"User-agent: *\nDisallow: /private\n"))

    result = make_fetcher(site, tmp_path).fetch("https://EXAMPLE.com/a/../private/x")

    assert result.requested_url == "https://example.com/private/x"
    assert result.disallowed_url == "https://example.com/private/x"
    assert site.urls() == ["https://example.com/robots.txt"]


# Content coding


def test_a_gzip_body_is_decoded_and_hashed_decoded(tmp_path: Path) -> None:
    """The hash is of the body with the content coding removed."""
    site = Site()
    site.add(PAGE, respond(200, gzip.compress(b"hello"), {"content-encoding": "gzip"}))

    result = make_fetcher(site, tmp_path).fetch(PAGE)

    assert result.body == b"hello"
    assert result.receipts[0].body_sha256 == sha(b"hello")


@pytest.mark.parametrize("wbits", [zlib.MAX_WBITS, -zlib.MAX_WBITS])
def test_a_deflate_body_is_decoded_wrapped_or_raw(tmp_path: Path, wbits: int) -> None:
    """Deflate is accepted as a zlib stream or, as some servers send it, raw."""
    compressor = zlib.compressobj(wbits=wbits)
    data = compressor.compress(b"hello") + compressor.flush()
    site = Site()
    site.add(PAGE, respond(200, data, {"content-encoding": "deflate"}))

    assert make_fetcher(site, tmp_path).fetch(PAGE).body == b"hello"


def test_a_compressed_body_is_never_decoded_past_the_limit(tmp_path: Path) -> None:
    """A small gzip that expands hugely stops at the limit, with no hash."""
    site = Site()
    bomb = gzip.compress(b"\0" * 20_000_000)
    site.add(PAGE, respond(200, bomb, {"content-encoding": "gzip"}))

    result = make_fetcher(site, tmp_path, max_body_bytes=1000).fetch(PAGE)

    assert result.body == b"\0" * 1000
    assert (result.receipts[0].body_sha256, result.receipts[0].body_truncated_at) == (None, 1000)


@pytest.mark.parametrize("coding", ["gzip, gzip", "br", "zstd", "compress"])
def test_a_body_in_an_unsupported_coding_is_unreadable(tmp_path: Path, coding: str) -> None:
    """Stacked or unrequested codings are not decoded: CONNECTION, with the status kept."""
    site = Site()
    site.add(PAGE, respond(200, b"x", {"content-encoding": coding}))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert (receipt.error_kind, receipt.status_code, receipt.body_sha256) == (
        ErrorKind.CONNECTION,
        200,
        None,
    )


def test_a_corrupt_gzip_body_is_unreadable(tmp_path: Path) -> None:
    """A body that does not decode is CONNECTION, with the status kept."""
    site = Site()
    site.add(PAGE, respond(200, b"not gzip at all", {"content-encoding": "gzip"}))

    receipt = make_fetcher(site, tmp_path).fetch(PAGE).receipts[0]

    assert (receipt.error_kind, receipt.status_code) == (ErrorKind.CONNECTION, 200)


def test_only_gzip_and_deflate_are_offered(tmp_path: Path) -> None:
    """Accept-Encoding is fixed, so what Cernis asks for does not depend on installed packages."""
    site = Site()
    site.add(PAGE, respond(200))

    make_fetcher(site, tmp_path).fetch(PAGE)

    assert {request.headers["accept-encoding"] for request in site.requests} == {"gzip, deflate"}
