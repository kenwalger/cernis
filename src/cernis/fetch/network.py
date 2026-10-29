"""The network layer under httpx: screened addresses and an overall deadline.

Two jobs that httpx's own transport cannot do (ADR-005, DESIGN.md section 6):

- **Connect only to screened addresses.** The fetcher resolves each hop's
  host and screens every address (:mod:`cernis.fetch.addresses`) before it
  sends anything, then pins those addresses. :class:`GuardedBackend`
  connects to the pinned addresses and nothing else, so the addresses that
  were checked are the addresses connected to, and a second DNS answer
  (DNS rebinding) never reaches a socket. TLS is still verified against the
  hostname, because httpcore passes the hostname to ``start_tls``
  separately. A host with no pins is refused, never resolved here.
- **Bound the whole request.** Every socket operation's timeout is the
  smaller of its own timeout and the time left before the request's
  deadline, so a server that trickles its headers a byte at a time cannot
  hold a request open past ``total_timeout``.

:class:`GuardedTransport` is httpx's ``HTTPTransport`` with its connection
pool rebuilt on this backend. httpx 0.28 has no public way to pass a network
backend, so this replaces the transport's ``_pool`` attribute, and
``pyproject.toml`` holds httpx below 0.29. The localhost tests exercise this
path end to end.
"""

import socket
import ssl
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import httpcore
import httpx

Resolver = Callable[[str, int], Sequence[str]]
"""Resolves a host and port to IP addresses, as text."""

SocketOption = (
    tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
)
"""A socket option, in httpcore's form."""


class AddressRefusedError(Exception):
    """Raised by the backend for a host the fetcher did not screen and pin."""


def system_resolve(host: str, port: int) -> list[str]:
    """Resolve a host with the system resolver.

    :param host: A hostname or an IP address.
    :param port: The port, which some resolvers need.
    :return: The distinct addresses, in the resolver's order. A host that
        cannot be resolved raises :class:`socket.gaierror`, an
        :class:`OSError`, which the fetcher records as ``CONNECTION``.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


@dataclass
class RunNetwork:
    """The state the fetcher and its backend share for one run.

    The fetcher is single-threaded, so one deadline at a time is enough.

    :param clock: A monotonic clock, in seconds.
    :param pins: The screened addresses for each host, set before each hop.
    :param deadline: When the current request must end, on ``clock``, or
        ``None`` between requests.
    """

    clock: Callable[[], float]
    pins: dict[str, tuple[str, ...]] = field(default_factory=dict)
    deadline: float | None = None

    def bounded(self, timeout: float | None, error: type[Exception]) -> float | None:
        """Shrink a timeout to the time left before the deadline.

        :param timeout: The operation's own timeout, or ``None`` for none.
        :param error: The httpcore timeout to raise when no time is left.
        :return: The timeout to use.
        :raises error: If the deadline has passed.
        """
        if self.deadline is None:
            return timeout
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise error("the request's overall deadline passed")
        return remaining if timeout is None else min(timeout, remaining)


class DeadlineStream(httpcore.NetworkStream):
    """A network stream whose every operation respects the run's deadline.

    :param inner: The stream that does the I/O.
    :param network: The run's shared state.
    """

    def __init__(self, inner: httpcore.NetworkStream, network: RunNetwork) -> None:
        self._inner = inner
        self._network = network

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        """Read, within the deadline.

        :param max_bytes: The most bytes to read.
        :param timeout: The read timeout.
        :return: The bytes read.
        """
        return self._inner.read(max_bytes, self._network.bounded(timeout, httpcore.ReadTimeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        """Write, within the deadline.

        :param buffer: The bytes to write.
        :param timeout: The write timeout.
        """
        self._inner.write(buffer, self._network.bounded(timeout, httpcore.WriteTimeout))

    def close(self) -> None:
        """Close the stream."""
        self._inner.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        """Upgrade to TLS, within the deadline.

        :param ssl_context: The TLS settings.
        :param server_hostname: The hostname the certificate must match.
        :param timeout: The handshake timeout.
        :return: The TLS stream, still bound by the deadline.
        """
        bounded = self._network.bounded(timeout, httpcore.ConnectTimeout)
        upgraded = self._inner.start_tls(ssl_context, server_hostname, bounded)
        return DeadlineStream(upgraded, self._network)

    def get_extra_info(self, info: str) -> object:
        """Pass through a stream detail, such as the TLS object.

        :param info: The detail's name.
        :return: The detail.
        """
        return self._inner.get_extra_info(info)


class GuardedBackend(httpcore.NetworkBackend):
    """Connects only to the addresses the fetcher screened, within the deadline.

    :param network: The run's shared state.
    :param inner: The backend that opens sockets; tests pass a fake.
    """

    def __init__(self, network: RunNetwork, inner: httpcore.NetworkBackend) -> None:
        self._network = network
        self._inner = inner

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.NetworkStream:
        """Connect to the first pinned address for ``host`` that answers.

        :param host: The host, as the URL names it.
        :param port: The port.
        :param timeout: The connect timeout.
        :param local_address: The local address to bind, if any.
        :param socket_options: Socket options.
        :return: The connected stream.
        :raises AddressRefusedError: If ``host`` has no screened addresses.
        :raises failure: The last address's connect error or timeout, if none
            accepts.
        """
        addresses = self._network.pins.get(host)
        if not addresses:
            raise AddressRefusedError(f"{host} was not screened before connecting")
        options = list(socket_options) if socket_options is not None else None
        failure: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for address in addresses:
            bounded = self._network.bounded(timeout, httpcore.ConnectTimeout)
            try:
                stream = self._inner.connect_tcp(address, port, bounded, local_address, options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                failure = exc
                continue
            return DeadlineStream(stream, self._network)
        assert failure is not None  # addresses is not empty
        raise failure

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.NetworkStream:
        """Refuse Unix sockets, which Cernis never uses.

        :param path: The socket path.
        :param timeout: The connect timeout.
        :param socket_options: Socket options.
        :return: Never returns.
        :raises AddressRefusedError: Always.
        """
        raise AddressRefusedError("Unix sockets are not used")

    def sleep(self, seconds: float) -> None:
        """Sleep, for httpcore's connection retries.

        :param seconds: How long.
        """
        self._inner.sleep(seconds)


class GuardedTransport(httpx.HTTPTransport):
    """httpx's transport, connecting through a :class:`GuardedBackend`.

    TLS uses the system's default trust store, with nothing read from the
    environment, as for the rest of the fetcher.

    :param network: The run's shared state.
    :param inner_backend: The backend that opens sockets; ``None`` uses
        httpcore's own.
    """

    def __init__(
        self, network: RunNetwork, inner_backend: httpcore.NetworkBackend | None = None
    ) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            network_backend=GuardedBackend(network, inner_backend or httpcore.SyncBackend()),
        )
