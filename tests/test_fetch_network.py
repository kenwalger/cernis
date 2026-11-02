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
from cernis.fetch.network import AddressRefusedError, GuardedBackend, RunNetwork, SocketOption
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
    :param read_timeouts: Where each read's timeout is recorded.
    :param handshakes: Where each TLS handshake's hostname and timeout are
        recorded; ``None`` refuses TLS.
    :param sent: The request bytes written so far.
    :param position: How many response bytes have been read.
    """

    responses: dict[str, bytes]
    time: FakeTime
    bytes_per_read: int
    seconds_per_read: float
    read_timeouts: list[float | None] = field(default_factory=list)
    handshakes: list[tuple[str | None, float | None]] | None = None
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
        :param timeout: Recorded, so tests can check the deadline shrank it.
        :return: The bytes.
        """
        self.read_timeouts.append(timeout)
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
        """Record a TLS handshake and stay in plain text, or refuse TLS.

        :param ssl_context: Unused.
        :param server_hostname: Recorded: the name the certificate must match.
        :param timeout: Recorded: the handshake timeout.
        :return: This stream, standing in for the TLS one.
        :raises httpcore.ConnectError: When the backend refuses TLS.
        """
        if self.handshakes is None:
            raise httpcore.ConnectError("no TLS in the fake network")
        self.handshakes.append((server_hostname, timeout))
        return self

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
    :param seconds_per_connect: How long each connection attempt takes.
    :param tls: Whether TLS handshakes succeed (they are recorded, not real).
    :param connects: Every ``(address, port)`` dialed, in order.
    :param connect_timeouts: Each connection attempt's timeout, in order.
    :param read_timeouts: Each read's timeout, across connections, in order.
    :param handshakes: Each TLS handshake's hostname and timeout, in order.
    """

    time: FakeTime
    responses: dict[str, bytes] = field(default_factory=dict)
    bytes_per_read: int = 65536
    seconds_per_read: float = 0.0
    refuse: set[str] = field(default_factory=set)
    seconds_per_connect: float = 0.0
    tls: bool = False
    connects: list[tuple[str, int]] = field(default_factory=list)
    connect_timeouts: list[float | None] = field(default_factory=list)
    read_timeouts: list[float | None] = field(default_factory=list)
    handshakes: list[tuple[str | None, float | None]] = field(default_factory=list)

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
        :param timeout: Recorded: the connect timeout.
        :param local_address: Unused.
        :param socket_options: Unused.
        :return: The stream.
        :raises httpcore.ConnectError: For an address in ``refuse``.
        """
        self.connects.append((host, port))
        self.connect_timeouts.append(timeout)
        self.time.now += self.seconds_per_connect
        if host in self.refuse:
            raise httpcore.ConnectError(f"{host} refused")
        return FakeStream(
            self.responses,
            self.time,
            self.bytes_per_read,
            self.seconds_per_read,
            self.read_timeouts,
            self.handshakes if self.tls else None,
        )

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


def test_an_ipv6_address_is_pinned_and_dialed(tmp_path: Path) -> None:
    """A host that resolves to IPv6 is connected through its screened IPv6 address."""
    backend = FakeBackend(FakeTime(), {"/post": OK})
    resolver = FakeResolver({"example.com": ["2606:4700::6810:84e5"]})

    result = _fetcher(backend, tmp_path, resolver).fetch(PAGE)

    assert result.receipts[0].status_code == 200
    assert backend.connects == [("2606:4700::6810:84e5", 80), ("2606:4700::6810:84e5", 80)]


def test_an_ipv6_literal_url_is_pinned_and_dialed(tmp_path: Path) -> None:
    """A URL naming an IPv6 address is screened and connected under the same name."""
    backend = FakeBackend(FakeTime(), {"/post": OK})

    result = _fetcher(backend, tmp_path).fetch("http://[2606:4700::6810:84e5]/post")

    assert result.receipts[0].status_code == 200
    assert {address for address, _ in backend.connects} == {"2606:4700::6810:84e5"}


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


def test_bounded_shrinks_a_timeout_to_the_time_left() -> None:
    """With no deadline a timeout is unchanged; with one, it is cut to what is left, then raises."""
    time = FakeTime()
    network = RunNetwork(clock=time.clock)

    assert network.bounded(5.0, httpcore.ReadTimeout) == 5.0
    network.deadline = time.now + 2
    assert network.bounded(5.0, httpcore.ReadTimeout) == 2
    assert network.bounded(None, httpcore.ReadTimeout) == 2
    time.now += 3
    with pytest.raises(httpcore.ReadTimeout):
        network.bounded(5.0, httpcore.ReadTimeout)


@pytest.mark.parametrize("seconds_per_read", [0.0, 1.0], ids=["answered", "timed-out"])
def test_the_deadline_is_cleared_between_requests(tmp_path: Path, seconds_per_read: float) -> None:
    """After a request, answered or timed out, no deadline is left for the next one."""
    backend = FakeBackend(
        FakeTime(), {"/post": OK}, bytes_per_read=1, seconds_per_read=seconds_per_read
    )
    fetcher = _fetcher(backend, tmp_path, total_timeout=10)

    result = fetcher.fetch(PAGE)

    timed_out = result.robots_receipts[0].error_kind is ErrorKind.TIMEOUT
    assert timed_out is (seconds_per_read > 0)
    assert fetcher._network.deadline is None


def test_https_dials_the_pinned_address_and_verifies_the_hostname(tmp_path: Path) -> None:
    """The socket goes to the screened address; the TLS handshake is given the hostname."""
    backend = FakeBackend(FakeTime(), {"/post": OK}, tls=True)

    result = _fetcher(backend, tmp_path).fetch("https://example.com/post")

    assert result.receipts[0].status_code == 200
    assert backend.connects == [(PUBLIC_ADDRESS, 443), (PUBLIC_ADDRESS, 443)]
    assert [hostname for hostname, _ in backend.handshakes] == ["example.com", "example.com"]


def test_each_read_waits_no_longer_than_the_time_left(tmp_path: Path) -> None:
    """A read timeout longer than the deadline is cut to the time left, read by read."""
    backend = FakeBackend(FakeTime(), {"/post": OK}, bytes_per_read=1, seconds_per_read=1.0)

    _fetcher(backend, tmp_path, total_timeout=10, read_timeout=20).fetch(PAGE)

    # robots.txt trickles one byte a second; each read gets one second less.
    assert backend.read_timeouts == [float(10 - n) for n in range(10)]


def test_the_deadline_bounds_connecting_across_pinned_addresses(tmp_path: Path) -> None:
    """Each address gets only the time left; when none is left, the next is not dialed."""
    addresses = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    backend = FakeBackend(FakeTime(), refuse=set(addresses[:2]), seconds_per_connect=6.0)
    resolver = FakeResolver({"example.com": addresses})

    result = _fetcher(backend, tmp_path, resolver, total_timeout=10).fetch(PAGE)

    assert result.robots_receipts[0].error_kind is ErrorKind.TIMEOUT
    assert backend.connects == [(addresses[0], 80), (addresses[1], 80)]
    assert backend.connect_timeouts == [10.0, 4.0]


def test_the_deadline_bounds_the_tls_handshake(tmp_path: Path) -> None:
    """The handshake is given the time left, not its own full timeout."""
    backend = FakeBackend(FakeTime(), {"/post": OK}, tls=True, seconds_per_connect=4.0)

    _fetcher(backend, tmp_path, total_timeout=10, connect_timeout=30).fetch(
        "https://example.com/post"
    )

    assert [timeout for _, timeout in backend.handshakes] == [6.0, 6.0]


def test_a_body_trickled_past_the_deadline_is_timeout_with_its_status(tmp_path: Path) -> None:
    """Headers in time, the body too slow: TIMEOUT, keeping the status that arrived (ADR-004)."""
    slow = b"HTTP/1.1 200 OK\r\nContent-Length: 200\r\nConnection: close\r\n\r\n" + b"x" * 200
    backend = FakeBackend(FakeTime(), {"/post": slow}, bytes_per_read=16, seconds_per_read=1.0)

    result = _fetcher(backend, tmp_path, total_timeout=10).fetch(PAGE)

    (receipt,) = result.receipts
    assert (receipt.error_kind, receipt.status_code) == (ErrorKind.TIMEOUT, 200)


def test_unix_sockets_are_refused() -> None:
    """The backend never opens a Unix socket."""
    backend = GuardedBackend(RunNetwork(clock=FakeTime().clock), FakeBackend(FakeTime()))

    with pytest.raises(AddressRefusedError, match="Unix sockets"):
        backend.connect_unix_socket("/var/run/docker.sock")
