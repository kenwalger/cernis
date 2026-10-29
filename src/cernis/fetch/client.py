"""The fetcher: polite HTTP fetches that produce receipts (DESIGN.md sections 3 and 6).

One call to :meth:`Fetcher.fetch` checks robots.txt, follows redirects by
hand so every hop is recorded, retries ``429`` and ``503``, and returns a
:class:`FetchResult` holding one :class:`~cernis.model.Receipt` per attempt.
Nothing is parsed here except robots.txt.

- **Redirects** (``301``, ``302``, ``303``, ``307``, ``308``) are followed up
  to ``max_redirects``; one more is ``TOO_MANY_REDIRECTS``. A redirect whose
  ``Location`` is missing, malformed, not http or https, or carries user
  information, or appears more than once, is not followed, and is the final
  response. Each redirect target is checked against its own origin's
  robots.txt before it is requested; a disallowed target is not requested,
  the redirect is the final response, and :attr:`FetchResult.disallowed_url`
  names the target. While fetching robots.txt itself, a redirect is followed
  only to another ``/robots.txt``; any other target is not requested.
- **URLs** are requested, checked against robots.txt, and recorded in the
  normalized form httpx sends (host lowercased, dot segments removed,
  percent-encoding applied), so the check and the receipt name the resource
  actually requested.
- **Retries**: an attempt that ends in ``429`` or ``503`` is retried from the
  requested URL, up to ``max_attempts`` attempts in all. The wait is the
  ``Retry-After`` value when there is a usable one, otherwise
  ``backoff_base * 2 ** (attempt - 1)``, capped at ``backoff_cap``. A
  ``Retry-After`` longer than the cap stops the retries at once. Every
  attempt gets its own receipt (SESSION-03.md decision 2).
- **Bodies** are read up to ``max_body_bytes``, counting both the bytes
  received and the bytes after decoding. A longer body is not read further;
  its receipt has no hash and records the limit (ADR-003). Cernis offers only
  ``gzip`` and ``deflate`` and decodes them itself, with bounded output, so a
  small compressed body cannot expand past the limit. The hash is of the
  decoded body.
- **Errors**: a timeout (including ``total_timeout`` for one request, checked
  when the headers arrive and after each chunk of body) is ``TIMEOUT``; a
  failure whose cause is an :class:`ssl.SSLError` is ``TLS``; any other
  failure to get or read a response, including a body in a coding Cernis did
  not offer or that does not decode, is ``CONNECTION``. The receipt names
  the URL whose request failed, and keeps the status and headers when they
  arrived before the body failed (ADR-004).
- **Addresses** (ADR-005): before every hop, robots.txt and redirects
  included, the host is resolved and every address it resolves to is
  screened. Any non-public address refuses the hop: no request is sent, and
  the receipt is ``ADDRESS_REFUSED`` with the reason in
  :attr:`FetchResult.refusals`. With the default transport the connection
  is made only to the screened addresses (:mod:`cernis.fetch.network`).
  ``allow_loopback`` opens loopback only, for testing.
- **Deadline**: ``total_timeout`` bounds the whole request, headers
  included; with the default transport every socket read and write is held
  to the time left.
- **Pacing**: at most one request per ``min_interval`` seconds per host,
  counting robots.txt and every redirect hop.
- **Cache**: a ``200`` with an ``ETag`` or ``Last-Modified`` is cached, and
  the next request for that URL is conditional. A ``304`` is recorded as
  such, with the cached body's hash.
- **No credentials and no state**: no cookies are stored or sent, no
  environment settings (proxies, ``.netrc``) are read, and a URL with user
  information is refused.
"""

import hashlib
import http.cookiejar
import re
import ssl
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import httpcore
import httpx

from cernis import REPOSITORY_URL, __version__
from cernis.fetch.addresses import refusal_reason
from cernis.fetch.cache import DEFAULT_CACHE_DIR, Cache, CacheEntry
from cernis.fetch.network import (
    AddressRefusedError,
    GuardedTransport,
    Resolver,
    RunNetwork,
    system_resolve,
)
from cernis.fetch.pacing import Pacer
from cernis.fetch.robots import RobotsDecision, RobotsPolicy, robots_url_for
from cernis.model import RECORDED_HEADERS, ErrorKind, Receipt

USER_AGENT = f"Cernis/{__version__} (+{REPOSITORY_URL})"
"""The user agent Cernis sends, and the one robots.txt rules are applied to."""

REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})
"""Statuses whose ``Location`` the fetcher follows."""

RETRY_STATUSES: frozenset[int] = frozenset({429, 503})
"""Statuses the fetcher retries."""

ACCEPT_ENCODING = "gzip, deflate"
"""The content codings Cernis offers, fixed so requests do not depend on installed packages."""

_DELTA_SECONDS = re.compile(r"[0-9]+")


class FetchError(ValueError):
    """Raised when a URL cannot be fetched at all, before any request is made."""


@dataclass(frozen=True, kw_only=True)
class FetchConfig:
    """Settings for a :class:`Fetcher`. The defaults are the polite ones.

    :param connect_timeout: Seconds to wait for a connection.
    :param read_timeout: Seconds to wait for each read from the server.
    :param total_timeout: Seconds one request may take, from sending it to
        the end of its body, so a server that sends slowly cannot hold a run.
    :param max_body_bytes: The most body bytes read from one response.
    :param max_redirects: The most redirects followed in one attempt.
    :param min_interval: The minimum seconds between requests to one host.
    :param max_attempts: The most attempts for one URL, the first included.
    :param backoff_base: Seconds to wait before the first retry when there is
        no usable ``Retry-After``; doubled for each later retry.
    :param backoff_cap: The longest wait before a retry. A longer
        ``Retry-After`` stops the retries.
    :param cache_dir: The cache directory, or ``None`` for no cache.
    :param allow_loopback: Allow loopback addresses (``127.0.0.0/8``,
        ``::1``), for testing against a local server. Every other non-public
        address is refused regardless (ADR-005).
    :raises ValueError: If a setting is out of range.
    """

    connect_timeout: float = 10.0
    read_timeout: float = 20.0
    total_timeout: float = 60.0
    max_body_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 10
    min_interval: float = 1.0
    max_attempts: int = 3
    backoff_base: float = 1.0
    backoff_cap: float = 60.0
    cache_dir: Path | None = field(default=DEFAULT_CACHE_DIR)
    allow_loopback: bool = False

    def __post_init__(self) -> None:
        """Check every setting.

        :raises ValueError: If a setting is out of range.
        """
        for name in ("connect_timeout", "read_timeout", "total_timeout"):
            if not getattr(self, name) > 0:
                raise ValueError(f"FetchConfig: {name} must be positive")
        for name in ("min_interval", "backoff_base", "backoff_cap"):
            if not getattr(self, name) >= 0:
                raise ValueError(f"FetchConfig: {name} must not be negative")
        if self.max_body_bytes < 1:
            raise ValueError("FetchConfig: max_body_bytes must be at least 1")
        if self.max_redirects < 0:
            raise ValueError("FetchConfig: max_redirects must not be negative")
        if self.max_attempts < 1:
            raise ValueError("FetchConfig: max_attempts must be at least 1")


@dataclass(frozen=True, kw_only=True)
class AddressRefusal:
    """Why a hop was refused before anything was sent (ADR-005).

    :param receipt_id: The ``ADDRESS_REFUSED`` receipt.
    :param url: The URL that was refused.
    :param reason: The address and the range it is in, such as
        ``169.254.169.254 is link-local, including cloud metadata
        (169.254.0.0/16)``.
    """

    receipt_id: str
    url: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class FetchResult:
    """Everything one :meth:`Fetcher.fetch` call did.

    :param requested_url: The URL asked for.
    :param receipts: One receipt per attempt, in order; empty if robots.txt
        disallowed the requested URL, so nothing was requested.
    :param robots_receipts: The receipts of every robots.txt fetch the
        decisions rest on, in order. A robots.txt is fetched once per run, so
        a later result can name receipts an earlier one produced.
    :param robots: One decision per URL checked against robots.txt: the
        requested URL, then each redirect target.
    :param disallowed_url: The URL robots.txt disallowed, so Cernis did not
        request it: the requested URL, or a redirect target. ``None`` if
        nothing was disallowed.
    :param body: The last attempt's body as read (at most the size limit);
        for a ``304``, the cached body. ``None`` if there was none.
    :param refusals: The reason for each ``ADDRESS_REFUSED`` receipt in
        ``receipts`` and ``robots_receipts``.
    """

    requested_url: str
    receipts: tuple[Receipt, ...]
    robots_receipts: tuple[Receipt, ...]
    robots: tuple[RobotsDecision, ...]
    disallowed_url: str | None
    body: bytes | None
    refusals: tuple[AddressRefusal, ...] = ()

    @property
    def final(self) -> Receipt | None:
        """The last attempt's receipt, or ``None`` if nothing was requested."""
        return self.receipts[-1] if self.receipts else None

    @property
    def rate_limited(self) -> bool:
        """Whether the last attempt was still refused with ``429`` (the input to RATE_LIMITED)."""
        final = self.final
        return final is not None and final.status_code == 429


@dataclass(frozen=True, kw_only=True)
class _Exchange:
    """One request and its response, or why there was none.

    :param sent_at: When the request was sent, after any pacing wait.
    :param status: The status code, or ``None`` with ``error`` set.
    :param error: Why there was no response, or ``NONE``.
    :param headers: The recorded header subset.
    :param locations: The ``Location`` header values, if any.
    :param body: The body as read, or ``None``.
    :param body_sha256: The hash for the receipt, or ``None``.
    :param truncated: Whether the body was cut off at the limit.
    :param refusal: For ``ADDRESS_REFUSED``, why.
    """

    sent_at: datetime
    status: int | None
    error: ErrorKind
    headers: tuple[tuple[str, str], ...] = ()
    locations: tuple[str, ...] = ()
    body: bytes | None = None
    body_sha256: str | None = None
    truncated: bool = False
    refusal: str | None = None


@dataclass(frozen=True, kw_only=True)
class _Attempt:
    """One attempt at a URL: a receipt, or a disallowed requested URL.

    :param receipt: The receipt, or ``None`` if the requested URL was disallowed.
    :param body: The final response's body, if any.
    :param disallowed_url: The URL robots.txt disallowed, if any.
    """

    receipt: Receipt | None
    body: bytes | None = None
    disallowed_url: str | None = None


_LOCATIONS = "cernis.locations"
"""The response extension holding the ``Location`` values the transport hid."""


class _LocationHidingTransport(httpx.BaseTransport):
    """Moves ``Location`` out of the headers, so only the fetcher follows redirects.

    httpx's client prepares the next request for any redirect response, even
    with ``follow_redirects=False``, and raises on a ``Location`` it cannot
    parse before the fetcher sees the response. Hiding the header keeps every
    redirect decision, and every malformed ``Location``, in the fetcher.

    :param inner: The transport that makes the requests.
    """

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request, and move any ``Location`` headers into an extension.

        :param request: The request.
        :return: The response, without ``Location`` headers.
        """
        response = self._inner.handle_request(request)
        locations = tuple(response.headers.get_list("location"))
        if locations:
            del response.headers["location"]
            response.extensions = {**response.extensions, _LOCATIONS: locations}
        return response

    def close(self) -> None:
        """Close the inner transport."""
        self._inner.close()


class _TotalTimeoutError(Exception):
    """Raised inside a request that has run longer than ``total_timeout``."""


class _UnreadableBodyError(Exception):
    """Raised when a body is in a coding Cernis did not offer, or does not decode."""


class _BodyDecoder:
    """Removes one content coding with bounded output.

    httpx decodes each network chunk in full before the caller sees it, so a
    small compressed chunk can expand without limit. This decoder takes a
    ``room`` argument and never returns more than that.

    :param content_encoding: The ``Content-Encoding`` header values.
    :raises _UnreadableBodyError: For more than one coding, or one other than
        ``gzip`` and ``deflate``.
    """

    def __init__(self, content_encoding: list[str]) -> None:
        codings = [
            part.strip().lower()
            for value in content_encoding
            for part in value.split(",")
            if part.strip() and part.strip().lower() != "identity"
        ]
        if len(codings) > 1 or (codings and codings[0] not in ("gzip", "x-gzip", "deflate")):
            raise _UnreadableBodyError(f"unsupported Content-Encoding: {', '.join(codings)}")
        self._coding = codings[0] if codings else None
        self._inflater: zlib._Decompress | None = None
        if self._coding in ("gzip", "x-gzip"):
            self._inflater = zlib.decompressobj(zlib.MAX_WBITS | 16)
        elif self._coding == "deflate":
            self._inflater = zlib.decompressobj(zlib.MAX_WBITS)
        self._fed = False

    def feed(self, data: bytes, room: int) -> bytes:
        """Decode the next received bytes.

        :param data: Bytes as received.
        :param room: The most decoded bytes to return.
        :return: Decoded bytes, at most ``room`` of them.
        :raises _UnreadableBodyError: If the bytes do not decode.
        """
        if self._inflater is None:
            return data[:room]
        first, self._fed = not self._fed, True
        try:
            return self._inflater.decompress(data, room)
        except zlib.error as exc:
            if not (first and self._coding == "deflate"):
                raise _UnreadableBodyError(str(exc)) from exc
        # Some servers send raw deflate without the zlib wrapper.
        self._inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            return self._inflater.decompress(data, room)
        except zlib.error as exc:
            raise _UnreadableBodyError(str(exc)) from exc


def _url_problem(url: str) -> str | None:
    """Say why Cernis will not fetch a URL it was asked for, if it will not.

    :param url: The URL.
    :return: The reason, or ``None`` if it is an absolute http or https URL
        with no user information.
    """
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        return f"not a valid URL: {url!r} ({exc})"
    if parsed.scheme not in ("http", "https") or not parsed.host:
        return f"not an absolute http or https URL: {url!r}"
    if parsed.userinfo:
        return f"URLs with user information are not fetched: {url!r}"
    return None


def _redirect_target(current: str, locations: tuple[str, ...]) -> str | None:
    """Resolve a ``Location`` header against the URL that sent it.

    :param current: The URL that answered with a redirect.
    :param locations: The ``Location`` header values; exactly one can be followed.
    :return: The absolute target, or ``None`` if it cannot be followed.
    """
    if len(locations) != 1 or not locations[0].strip():
        return None
    location = locations[0]
    try:
        target = httpx.URL(current).join(location.strip())
    except httpx.InvalidURL:
        return None
    if target.scheme not in ("http", "https") or not target.host or target.userinfo:
        return None
    return str(target)


def _is_robots_url(url: str) -> bool:
    """Tell whether a URL is an origin's robots.txt.

    :param url: An absolute URL.
    :return: Whether its path is ``/robots.txt`` with no query.
    """
    parsed = httpx.URL(url)
    return parsed.path == "/robots.txt" and not parsed.query


def _recorded_headers(headers: httpx.Headers) -> tuple[tuple[str, str], ...]:
    """Pick the recorded subset of response headers, combining repeats.

    :param headers: The response headers.
    :return: ``(name, value)`` pairs; a repeated header's values are joined
        with ``", "`` (RFC 9110 section 5.3).
    """
    return tuple(
        (name, ", ".join(headers.get_list(name)))
        for name in sorted(RECORDED_HEADERS)
        if name in headers
    )


def _is_tls_failure(exc: BaseException) -> bool:
    """Tell whether an exception was caused by TLS.

    :param exc: The exception httpx raised.
    :return: Whether an :class:`ssl.SSLError` is in its cause chain.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Read a ``Retry-After`` value as seconds to wait (RFC 9110 section 10.2.3).

    :param value: The header value, if any: delay seconds or an HTTP date.
    :param now: The current time, timezone-aware, for an HTTP date.
    :return: Seconds to wait (zero for a date in the past, infinity for a
        number too long to read), or ``None`` if there is no usable value.
    """
    if value is None:
        return None
    value = value.strip()
    if _DELTA_SECONDS.fullmatch(value):
        return float(int(value)) if len(value) <= 12 else float("inf")
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


class Fetcher:
    """Fetches URLs politely and records receipts. One fetcher is one run.

    robots.txt is fetched once per origin for the fetcher's lifetime, and
    receipt ids (``r-001``, ``r-002``, ...) are unique within it.

    :param config: The settings.
    :param transport: The httpx transport; tests pass an
        :class:`httpx.MockTransport`. ``None`` uses the network.
    :param clock: A monotonic clock, in seconds, for pacing and timeouts.
    :param sleep: Sleeps for the given number of seconds.
    :param now: The current time, timezone-aware, in UTC, for receipts and
        ``Retry-After`` dates.
    :param resolver: Resolves a host to its addresses for the address
        screen; tests pass a fake.
    :param network_backend: The httpcore backend under the default
        transport, which opens sockets; tests pass a fake. Ignored when
        ``transport`` is given.
    """

    def __init__(
        self,
        config: FetchConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        resolver: Resolver = system_resolve,
        network_backend: httpcore.NetworkBackend | None = None,
    ) -> None:
        self.config = config or FetchConfig()
        self._resolve = resolver
        self._network = RunNetwork(clock=clock)
        self._refusals: dict[str, AddressRefusal] = {}
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._pacer = Pacer(self.config.min_interval, clock, sleep)
        self._cache = (
            Cache(self.config.cache_dir, max_body_bytes=self.config.max_body_bytes)
            if self.config.cache_dir is not None
            else None
        )
        # An empty allowed_domains list makes the jar refuse every cookie.
        jar = http.cookiejar.CookieJar(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self._client = httpx.Client(
            transport=_LocationHidingTransport(
                transport or GuardedTransport(self._network, network_backend)
            ),
            timeout=httpx.Timeout(self.config.read_timeout, connect=self.config.connect_timeout),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": ACCEPT_ENCODING},
            cookies=jar,
            trust_env=False,
        )
        self._next_id = 1
        self._robots: dict[str, tuple[RobotsPolicy, tuple[Receipt, ...]]] = {}

    def __enter__(self) -> Self:
        """Use the fetcher as a context manager.

        :return: The fetcher.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the fetcher.

        :param exc_type: The exception type, if one was raised.
        :param exc: The exception, if one was raised.
        :param traceback: Its traceback, if one was raised.
        """
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        """Fetch ``url``, checking robots.txt first.

        :param url: An absolute http or https URL with no user information.
            It is requested and recorded in the normalized form httpx sends.
        :return: What the fetch did, with a receipt per attempt.
        :raises FetchError: If the URL cannot be fetched at all.
        """
        problem = _url_problem(url)
        if problem is not None:
            raise FetchError(problem)
        url = str(httpx.URL(url))
        decisions: list[RobotsDecision] = []
        receipts, body, disallowed = self._attempts(url, decisions)
        robots_receipts: list[Receipt] = []
        for robots_url in dict.fromkeys(decision.robots_url for decision in decisions):
            robots_receipts.extend(self._robots[robots_url][1])
        refusals = tuple(
            self._refusals[receipt.id]
            for receipt in (*robots_receipts, *receipts)
            if receipt.id in self._refusals
        )
        return FetchResult(
            requested_url=url,
            receipts=receipts,
            robots_receipts=tuple(robots_receipts),
            robots=tuple(decisions),
            disallowed_url=disallowed,
            body=body,
            refusals=refusals,
        )

    def _attempts(
        self, url: str, decisions: list[RobotsDecision] | None
    ) -> tuple[tuple[Receipt, ...], bytes | None, str | None]:
        """Fetch ``url`` with retries.

        :param url: The URL.
        :param decisions: Where to record robots decisions, or ``None`` to skip
            robots.txt (for fetching robots.txt itself).
        :return: The receipts, the last body, and the disallowed URL, if any.
        """
        receipts: list[Receipt] = []
        attempt = _Attempt(receipt=None)
        for number in range(1, self.config.max_attempts + 1):
            attempt = self._attempt(url, decisions)
            if attempt.receipt is None:
                break
            receipts.append(attempt.receipt)
            delay = self._retry_delay(attempt.receipt, number)
            if delay is None:
                break
            self._sleep(delay)
        return tuple(receipts), attempt.body, attempt.disallowed_url

    def _retry_delay(self, receipt: Receipt, number: int) -> float | None:
        """Decide whether to retry after an attempt, and how long to wait.

        :param receipt: The attempt's receipt.
        :param number: The attempt's number, starting at 1.
        :return: Seconds to wait before the next attempt, or ``None`` to stop.
        """
        if receipt.status_code not in RETRY_STATUSES or number >= self.config.max_attempts:
            return None
        retry_after = parse_retry_after(receipt.header("retry-after"), self._now())
        if retry_after is not None:
            return retry_after if retry_after <= self.config.backoff_cap else None
        return min(self.config.backoff_cap, self.config.backoff_base * 2.0 ** (number - 1))

    def _allowed(self, url: str, decisions: list[RobotsDecision]) -> bool:
        """Check ``url`` against its origin's robots.txt, fetching that once per run.

        :param url: The URL.
        :param decisions: Where to record the decision; a URL is recorded once.
        :return: Whether Cernis may fetch it.
        """
        robots_url = robots_url_for(url)
        if robots_url not in self._robots:
            receipts, body, _ = self._attempts(robots_url, None)
            self._robots[robots_url] = (RobotsPolicy(robots_url, receipts[-1], body), receipts)
        decision = self._robots[robots_url][0].decide(url, USER_AGENT)
        if all(known.url != url for known in decisions):
            decisions.append(decision)
        return decision.allowed

    def _attempt(self, url: str, decisions: list[RobotsDecision] | None) -> _Attempt:
        """Make one attempt at ``url``, following redirects.

        :param url: The requested URL.
        :param decisions: Where to record robots decisions, or ``None`` to skip
            robots.txt.
        :return: The attempt.
        """
        screened = self._screen(url)
        if screened is not None:
            return _Attempt(receipt=self._receipt(url, screened.sent_at, [], url, screened))
        if decisions is not None and not self._allowed(url, decisions):
            return _Attempt(receipt=None, disallowed_url=url)
        fetched_at: datetime | None = None
        chain: list[str] = []
        current = url
        while True:
            exchange = self._exchange(current)
            fetched_at = fetched_at or exchange.sent_at
            if exchange.error is not ErrorKind.NONE:
                return _Attempt(receipt=self._receipt(url, fetched_at, chain, current, exchange))
            target = None
            if exchange.status in REDIRECT_STATUSES:
                target = _redirect_target(current, exchange.locations)
                # robots.txt redirects lead only to robots.txt (DESIGN.md section 6).
                if decisions is None and target is not None and not _is_robots_url(target):
                    target = None
            if target is None:
                receipt = self._receipt(url, fetched_at, chain, current, exchange)
                return _Attempt(receipt=receipt, body=exchange.body)
            if len(chain) >= self.config.max_redirects:
                too_many = _Exchange(
                    sent_at=exchange.sent_at, status=None, error=ErrorKind.TOO_MANY_REDIRECTS
                )
                receipt = self._receipt(url, fetched_at, [*chain, current], None, too_many)
                return _Attempt(receipt=receipt)
            screened = self._screen(target)
            if screened is not None:
                receipt = self._receipt(url, fetched_at, [*chain, current], target, screened)
                return _Attempt(receipt=receipt)
            if decisions is not None and not self._allowed(target, decisions):
                receipt = self._receipt(url, fetched_at, chain, current, exchange)
                return _Attempt(receipt=receipt, disallowed_url=target)
            chain.append(current)
            current = target

    def _receipt(
        self,
        url: str,
        fetched_at: datetime,
        chain: list[str],
        final_url: str | None,
        exchange: _Exchange,
    ) -> Receipt:
        """Record an attempt as a receipt with the next id.

        :param url: The requested URL.
        :param fetched_at: When the attempt's first request was sent.
        :param chain: The URLs that redirected, in order.
        :param final_url: The URL that gave the final response, or ``None``.
        :param exchange: The final exchange.
        :return: The receipt.
        """
        receipt = Receipt(
            id=f"r-{self._next_id:03d}",
            requested_url=url,
            final_url=final_url,
            redirect_chain=tuple(chain),
            status_code=exchange.status,
            error_kind=exchange.error,
            fetched_at=fetched_at,
            body_sha256=exchange.body_sha256,
            body_truncated_at=self.config.max_body_bytes if exchange.truncated else None,
            headers=exchange.headers,
            cernis_version=__version__,
            user_agent=USER_AGENT,
        )
        self._next_id += 1
        if exchange.refusal is not None and final_url is not None:
            self._refusals[receipt.id] = AddressRefusal(
                receipt_id=receipt.id, url=final_url, reason=exchange.refusal
            )
        return receipt

    def _screen(self, url: str) -> _Exchange | None:
        """Resolve a URL's host and screen every address before anything is sent.

        On success the addresses are pinned for the default transport, so the
        connection goes only to them.

        :param url: The URL about to be requested.
        :return: ``None`` if every address is public (or allowed loopback); an
            ``ADDRESS_REFUSED`` exchange naming the first refused address; or a
            ``CONNECTION`` exchange if the host does not resolve.
        """
        parsed = httpx.URL(url)
        host = parsed.raw_host.decode("ascii")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = tuple(self._resolve(host, port))
        except OSError:
            addresses = ()
        if not addresses:
            return _Exchange(sent_at=self._now(), status=None, error=ErrorKind.CONNECTION)
        for address in addresses:
            reason = refusal_reason(address, allow_loopback=self.config.allow_loopback)
            if reason is not None:
                return _Exchange(
                    sent_at=self._now(),
                    status=None,
                    error=ErrorKind.ADDRESS_REFUSED,
                    refusal=f"{host} resolves to {reason}",
                )
        self._network.pins[host] = addresses
        return None

    def _exchange(self, url: str) -> _Exchange:
        """Make one paced request, conditional when the cache allows.

        :param url: The URL to request.
        :return: The response, or why there was none.
        """
        self._pacer.wait((httpx.URL(url).host or "").lower())
        cached = self._cache.lookup(url) if self._cache is not None else None
        conditional: dict[str, str] = {}
        if cached is not None:
            if cached.etag is not None:
                conditional["If-None-Match"] = cached.etag
            if cached.last_modified is not None:
                conditional["If-Modified-Since"] = cached.last_modified
        sent_at = self._now()
        started = self._clock()
        status: int | None = None
        headers: tuple[tuple[str, str], ...] = ()
        refusal = None
        self._network.deadline = started + self.config.total_timeout
        try:
            with self._client.stream("GET", url, headers=conditional) as response:
                status = response.status_code
                headers = _recorded_headers(response.headers)
                self._check_deadline(started)
                return self._read_response(url, response, cached, sent_at, started)
        except (httpx.TimeoutException, _TotalTimeoutError):
            kind = ErrorKind.TIMEOUT
        except _UnreadableBodyError:
            kind = ErrorKind.CONNECTION
        except AddressRefusedError as exc:
            kind, refusal = ErrorKind.ADDRESS_REFUSED, str(exc)
        except httpx.RequestError as exc:
            kind = ErrorKind.TLS if _is_tls_failure(exc) else ErrorKind.CONNECTION
        finally:
            self._network.deadline = None
        return _Exchange(
            sent_at=sent_at, status=status, error=kind, headers=headers, refusal=refusal
        )

    def _check_deadline(self, started: float) -> None:
        """Stop a request that has run longer than ``total_timeout``.

        :param started: When the request was sent, on the monotonic clock.
        :raises _TotalTimeoutError: If the deadline has passed.
        """
        if self._clock() - started > self.config.total_timeout:
            raise _TotalTimeoutError

    def _read_response(
        self,
        url: str,
        response: httpx.Response,
        cached: CacheEntry | None,
        sent_at: datetime,
        started: float,
    ) -> _Exchange:
        """Turn a streamed response into an exchange, and update the cache.

        :param url: The request URL.
        :param response: The open response.
        :param cached: The cache entry the request was conditional on, if any.
        :param sent_at: When the request was sent, on the wall clock.
        :param started: When the request was sent, on the monotonic clock.
        :return: The exchange. A body that takes longer than ``total_timeout``
            or cannot be decoded raises out of here, so :meth:`_exchange`
            records the failure with the status and headers it already has.
        """
        status = response.status_code
        headers = _recorded_headers(response.headers)
        if status in REDIRECT_STATUSES:
            return _Exchange(
                sent_at=sent_at,
                status=status,
                error=ErrorKind.NONE,
                headers=headers,
                locations=response.extensions.get(_LOCATIONS, ()),
            )
        if status == 304:
            if cached is None or self._cache is None:
                return _Exchange(
                    sent_at=sent_at, status=status, error=ErrorKind.NONE, headers=headers
                )
            self._cache.refresh(
                cached,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            return _Exchange(
                sent_at=sent_at,
                status=status,
                error=ErrorKind.NONE,
                headers=headers,
                body=cached.body,
                body_sha256=cached.body_sha256,
            )
        limit = self.config.max_body_bytes
        decoder = _BodyDecoder(response.headers.get_list("content-encoding"))
        buffer = bytearray()
        received = 0
        truncated = False
        for chunk in response.iter_raw():
            received += len(chunk)
            buffer += decoder.feed(chunk, limit + 1 - len(buffer))
            if len(buffer) > limit or received > limit:
                del buffer[limit:]
                truncated = True
                break
            self._check_deadline(started)
        body = bytes(buffer)
        if status == 200 and self._cache is not None:
            if truncated:
                self._cache.drop(url)
            else:
                self._cache.store(
                    url,
                    etag=response.headers.get("etag"),
                    last_modified=response.headers.get("last-modified"),
                    body=body,
                )
        return _Exchange(
            sent_at=sent_at,
            status=status,
            error=ErrorKind.NONE,
            headers=headers,
            body=body,
            body_sha256=None if truncated else hashlib.sha256(body).hexdigest(),
            truncated=truncated,
        )
