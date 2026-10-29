"""Tests for the network layer: pinned connections and the overall request deadline.

These run Cernis's real transport (httpx and httpcore, with h11 parsing the
bytes) over a fake network backend that opens no sockets, so a server that
trickles its headers one byte at a time can be simulated without waiting.
"""

import ssl
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Unpack

import httpcore
import pytest
from fetch_support import FIXED_NOW, PUBLIC_ADDRESS, ConfigOverrides, FakeResolver, FakeTime

from cernis.fetch import FetchConfig, Fetcher
from cernis.fetch.network import RunNetwork, SocketOption
from cernis.model import ErrorKind

PAGE = "http://example.com/post"
NOT_FOUND = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"


@dataclass
class FakeStream(httpcore.NetworkStream):
    """One fake connection: records the request, then plays back a response.

    :param responses: Response bytes by request path; others get a 404.
    :param time: The fake time; each read advances it by ``seconds_per_read``.
    :param bytes_per_read: The most bytes one read returns.
    :param seconds_per_read: How long each read takes.
    """

    responses: dict[str, bytes]
    time: FakeTime
    bytes_per_read: int
    seconds_per_read: float
    sent: bytearray = field(default_factory=bytearray)
    position: int = 0

    def _response(self) -> bytes:
        """Choose the response for the request written so far.

        :return: The response bytes.
        """
        path = bytes(self.sent).split(b" ", 2)[1].decode("ascii")
        return self.responses.get(path, NOT_FOUND)

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        """Return the next few response bytes, taking fake time.

        :param max_bytes: The most bytes to return.
        :param timeout: Ignored; the deadline is checked before this is called.
        :return: The bytes.
        """
        self.time.now += self.seconds_per_read
        response = self._response()
        chunk = response[self.position : self.position + min(max_bytes, self.bytes_per_read)]
        self.position += len(chunk)
        return chunk

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        """Record request bytes.

        :param buffer: The bytes.
        :param timeout: Ignored.
        """
        self.sent += buffer

    def close(self) -> None:
        """Close nothing."""

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        """Refuse TLS; these tests use http.

        :param ssl_context: Unused.
        :param server_hostname: Unused.
        :param timeout: Unused.
        :return: Never returns.
        :raises httpcore.ConnectError: Always.
        """
        raise httpcore.ConnectError("no TLS in the fake network")

    def get_extra_info(self, info: str) -> object:
        """Report nothing beyond being closed for reuse.

        :param info: The detail's name.
        :return: ``None``, or ``False`` for ``is_readable``.
        """
        return False if info == "is_readable" else None


@dataclass
class FakeBackend(httpcore.NetworkBackend):
    """A network with no sockets: records each connect, serves scripted responses.

    :param time: The fake time.
    :param responses: Response bytes by request path.
    :param bytes_per_read: The most bytes one read returns.
    :param seconds_per_read: How long each read takes.
    :param refuse: Addresses that refuse connections.
    """

    time: FakeTime
    responses: dict[str, bytes] = field(default_factory=dict)
    bytes_per_read: int = 65536
    seconds_per_read: float = 0.0
    refuse: set[str] = field(default_factory=set)
    connects: list[tuple[str, int]] = field(default_factory=list)

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.NetworkStream:
        """Open a fake connection.

        :param host: What to connect to; the guard passes an IP address.
        :param port: The port.
        :param timeout: Unused.
        :param local_address: Unused.
        :param socket_options: Unused.
        :return: The stream.
        :raises httpcore.ConnectError: For an address in ``refuse``.
        """
        self.connects.append((host, port))
        if host in self.refuse:
            raise httpcore.ConnectError(f"{host} refused")
        return FakeStream(self.responses, self.time, self.bytes_per_read, self.seconds_per_read)

    def sleep(self, seconds: float) -> None:
        """Advance fake time.

        :param seconds: How long.
        """
        self.time.now += seconds


def _fetcher(
    backend: FakeBackend,
    tmp_path: Path,
    resolver: FakeResolver | None = None,
    **config: Unpack[ConfigOverrides],
) -> Fetcher:
    """Build a fetcher on the real transport over a fake network.

    :param backend: The fake network.
    :param tmp_path: The cache directory.
    :param resolver: The fake resolver; a new one if ``None``.
    :param **config: Other settings.
    :return: The fetcher.
    """
    return Fetcher(
        replace(FetchConfig(cache_dir=tmp_path, min_interval=0), **config),
        clock=backend.time.clock,
        sleep=backend.time.sleep,
        now=lambda: FIXED_NOW,
        resolver=resolver or FakeResolver(),
        network_backend=backend,
    )


def test_a_response_is_received_through_the_real_transport(tmp_path: Path) -> None:
    """httpx, httpcore, and h11 run over the fake network and give a normal receipt."""
    backend = FakeBackend(FakeTime(), {"/post": OK})

    result = _fetcher(backend, tmp_path).fetch(PAGE)

    assert [r.status_code for r in result.robots_receipts] == [404]
    assert result.receipts[0].status_code == 200
    assert result.body == b"ok"


def test_connections_go_to_the_screened_address_not_the_name(tmp_path: Path) -> None:
    """The backend dials the address that was screened, never the hostname."""
    backend = FakeBackend(FakeTime(), {"/post": OK})

    _fetcher(backend, tmp_path).fetch(PAGE)

    assert backend.connects == [(PUBLIC_ADDRESS, 80), (PUBLIC_ADDRESS, 80)]


def test_a_second_dns_answer_never_reaches_a_socket(tmp_path: Path) -> None:
    """DNS rebinding: the transport never resolves again, so it cannot get a new answer."""
    backend = FakeBackend(FakeTime(), {"/post": OK})

    class Rebinding(FakeResolver):
        """Public for the two lookups the screen makes, then a private address."""

        def __call__(self, host: str, port: int) -> list[str]:
            """Resolve, rebinding to a private address after two lookups.

            :param host: The host.
            :param port: The port.
            :return: Its addresses.
            """
            self.lookups.append((host, port))
            return [PUBLIC_ADDRESS] if len(self.lookups) <= 2 else ["10.0.0.1"]

    resolver = Rebinding()
    _fetcher(backend, tmp_path, resolver).fetch(PAGE)

    # One lookup per hop (page, robots.txt), both by the fetcher's screen;
    # every connection went to what those lookups returned.
    assert len(resolver.lookups) == 2
    assert {address for address, _ in backend.connects} == {PUBLIC_ADDRESS}


def test_the_next_screened_address_is_tried_when_one_refuses(tmp_path: Path) -> None:
    """A host with several public addresses is connected through the first that accepts."""
    backend = FakeBackend(FakeTime(), {"/post": OK}, refuse={"203.0.113.10"})
    resolver = FakeResolver({"example.com": ["203.0.113.10", "203.0.113.11"]})

    result = _fetcher(backend, tmp_path, resolver).fetch(PAGE)

    assert result.receipts[0].status_code == 200
    assert ("203.0.113.11", 80) in backend.connects


def test_every_screened_address_refusing_is_connection(tmp_path: Path) -> None:
    """When no address accepts, the receipt is CONNECTION."""
    backend = FakeBackend(FakeTime(), refuse={PUBLIC_ADDRESS})

    result = _fetcher(backend, tmp_path).fetch(PAGE)

    assert result.robots_receipts[0].error_kind is ErrorKind.CONNECTION


def test_trickled_headers_cannot_hold_a_request_past_its_deadline(tmp_path: Path) -> None:
    """One header byte a second never trips a 20 s read timeout, but trips a 10 s deadline."""
    time = FakeTime()
    backend = FakeBackend(time, {"/post": OK}, bytes_per_read=1, seconds_per_read=1.0)

    result = _fetcher(backend, tmp_path, total_timeout=10, read_timeout=20).fetch(PAGE)

    (robots_receipt,) = result.robots_receipts
    assert robots_receipt.error_kind is ErrorKind.TIMEOUT
    assert robots_receipt.status_code is None
    assert time.now - 1000.0 <= 11


def test_a_slow_but_timely_response_is_received(tmp_path: Path) -> None:
    """The deadline bounds the request, not each byte: a trickle that finishes in time is fine."""
    backend = FakeBackend(FakeTime(), {"/post": OK}, bytes_per_read=8, seconds_per_read=1.0)

    result = _fetcher(backend, tmp_path, total_timeout=60).fetch(PAGE)

    assert result.receipts[0].status_code == 200


def test_the_deadline_is_cleared_between_requests() -> None:
    """Outside a request there is no deadline, so the next one starts with its full budget."""
    time = FakeTime()
    network = RunNetwork(clock=time.clock)

    assert network.bounded(5.0, httpcore.ReadTimeout) == 5.0
    network.deadline = time.now + 2
    assert network.bounded(5.0, httpcore.ReadTimeout) == 2
    assert network.bounded(None, httpcore.ReadTimeout) == 2
    time.now += 3
    with pytest.raises(httpcore.ReadTimeout):
        network.bounded(5.0, httpcore.ReadTimeout)
