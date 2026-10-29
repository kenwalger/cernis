"""Fakes for the fetcher tests: a scripted web, and time that passes only on demand."""

import ipaddress
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, Unpack

import httpx

from cernis.fetch import FetchConfig, Fetcher

FIXED_NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
"""The wall-clock time every fake fetch happens at."""

PUBLIC_ADDRESS = "203.0.113.10"
"""What every fake host resolves to unless a test says otherwise (TEST-NET-3, public)."""


class ConfigOverrides(TypedDict, total=False):
    """FetchConfig settings a test may override (everything but ``cache_dir``)."""

    connect_timeout: float
    read_timeout: float
    total_timeout: float
    max_body_bytes: int
    max_redirects: int
    min_interval: float
    max_attempts: int
    backoff_base: float
    backoff_cap: float
    allow_loopback: bool


Reply = Callable[[httpx.Request], httpx.Response] | BaseException


def respond(
    status: int = 200,
    content: bytes = b"",
    headers: dict[str, str] | list[tuple[str, str]] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a reply that answers with a fresh, streamed response each time.

    The body is a stream, as from a real transport; httpx reads a ``content=``
    body eagerly, which the fetcher's raw reads would refuse.

    :param status: The status code.
    :param content: The body.
    :param headers: The response headers.
    :return: The reply.
    """

    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, stream=httpx.ByteStream(content), headers=headers, request=request
        )

    return reply


def redirect(location: str, status: int = 301) -> Callable[[httpx.Request], httpx.Response]:
    """Build a reply that redirects.

    :param location: The ``Location`` header.
    :param status: The redirect status.
    :return: The reply.
    """
    return respond(status, headers={"location": location})


class ChunkStream(httpx.SyncByteStream):
    """A response body delivered in chunks, optionally failing partway.

    :param chunks: The chunks to deliver.
    :param fail_with: An exception to raise after the chunks, if any.
    :param before_chunk: Called before each chunk is delivered.
    """

    def __init__(
        self,
        chunks: list[bytes],
        fail_with: BaseException | None = None,
        before_chunk: Callable[[], None] | None = None,
    ) -> None:
        self.chunks = chunks
        self.fail_with = fail_with
        self.before_chunk = before_chunk
        self.delivered = 0

    def __iter__(self) -> Iterator[bytes]:
        """Deliver the chunks.

        :yield: Each chunk.
        :raises self.fail_with: After the chunks, if set.
        """
        for chunk in self.chunks:
            if self.before_chunk is not None:
                self.before_chunk()
            self.delivered += 1
            yield chunk
        if self.fail_with is not None:
            raise self.fail_with


@dataclass
class Site:
    """A scripted web for :class:`httpx.MockTransport`.

    Each URL has a queue of replies. A reply is used once and removed, except
    the last, which answers every later request. A URL with no route answers
    ``404``, so robots.txt is "unavailable" (everything allowed) unless a
    test routes it.

    :param routes: Replies by exact URL.
    :param requests: Every request received, in order.
    """

    routes: dict[str, list[Reply]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def add(self, url: str, *replies: Reply) -> None:
        """Route ``url`` to ``replies``, in order.

        :param url: The exact request URL.
        :param *replies: The replies.
        """
        self.routes[url] = list(replies)

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Answer one request.

        :param request: The request.
        :return: The scripted response.
        :raises reply: The scripted exception, when the reply is one.
        """
        self.requests.append(request)
        queue = self.routes.get(str(request.url))
        if not queue:
            return httpx.Response(404, stream=httpx.ByteStream(b""), request=request)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply(request)

    def urls(self) -> list[str]:
        """Return the URLs requested, in order.

        :return: The URLs.
        """
        return [str(request.url) for request in self.requests]


@dataclass
class FakeResolver:
    """A resolver for the address screen that never touches DNS.

    :param addresses: Addresses by host. An IP literal resolves to itself and
        any other host to :data:`PUBLIC_ADDRESS`, unless listed here. An empty
        list means the host does not resolve.
    :param lookups: Every ``(host, port)`` looked up, in order.
    """

    addresses: dict[str, list[str]] = field(default_factory=dict)
    lookups: list[tuple[str, int]] = field(default_factory=list)

    def __call__(self, host: str, port: int) -> list[str]:
        """Resolve a host.

        :param host: The host.
        :param port: The port.
        :return: Its addresses.
        :raises OSError: If the host is mapped to no addresses.
        """
        self.lookups.append((host, port))
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return self.addresses.get(host, [host])
        found = self.addresses.get(host, [PUBLIC_ADDRESS])
        if not found:
            raise OSError(f"{host} does not resolve")
        return found


@dataclass
class FakeTime:
    """A monotonic clock that moves only when something sleeps or a test advances it.

    :param now: The current reading, in seconds.
    :param sleeps: Every sleep requested, in order.
    """

    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def clock(self) -> float:
        """Read the clock.

        :return: The current reading.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """Sleep instantly, advancing the clock.

        :param seconds: How long to sleep.
        """
        self.sleeps.append(seconds)
        self.now += seconds


def make_fetcher(
    site: Site,
    cache_dir: Path | None,
    time: FakeTime | None = None,
    resolver: FakeResolver | None = None,
    **config: Unpack[ConfigOverrides],
) -> Fetcher:
    """Build a fetcher on a scripted web with fake time.

    :param site: The scripted web.
    :param cache_dir: The cache directory, or ``None`` for no cache.
    :param time: The fake time; a new one if ``None``.
    :param resolver: The fake resolver; a new one if ``None``.
    :param **config: Other :class:`FetchConfig` settings.
    :return: The fetcher.
    """
    time = time or FakeTime()
    return Fetcher(
        replace(FetchConfig(cache_dir=cache_dir), **config),
        transport=httpx.MockTransport(site.handler),
        clock=time.clock,
        sleep=time.sleep,
        now=lambda: FIXED_NOW,
        resolver=resolver or FakeResolver(),
    )
