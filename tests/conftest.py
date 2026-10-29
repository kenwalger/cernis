"""Shared test configuration: no test may reach the internet.

Every test runs under a network guard. A connection or name lookup for
anything but a loopback address or ``localhost`` raises
:class:`NetworkBlockedError`, and is also recorded, so a test still fails in
teardown when library code catches the error (httpx turns most socket errors
into its own). Subprocesses a test starts are not covered; none of them
fetch.
"""

import ipaddress
import socket
from collections.abc import Iterator

import pytest

pytest_plugins = ["pytester"]


class NetworkBlockedError(RuntimeError):
    """Raised when a test tries to reach a host other than localhost."""


def is_local_host(host: object) -> bool:
    """Tell whether a host names this machine.

    :param host: A host from a socket address or a name lookup.
    :return: Whether it is ``localhost``, a ``.localhost`` name, or a
        loopback IP address.
    """
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if not isinstance(host, str):
        return False
    name = host.lower().rstrip(".")
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


class NetworkGuard:
    """Records and refuses connections and lookups that would leave the machine."""

    def __init__(self) -> None:
        self.blocked: list[str] = []

    def refuse_unless_local(self, host: object, what: str) -> None:
        """Raise and record unless ``host`` is local.

        :param host: The host about to be reached or looked up.
        :param what: What was attempted, for the message.
        :raises NetworkBlockedError: If the host is not local.
        """
        if not is_local_host(host):
            attempt = f"{what} {host!r}"
            self.blocked.append(attempt)
            raise NetworkBlockedError(f"tests may not reach the network: {attempt}")

    def refuse_address(self, address: object, what: str) -> None:
        """Check a socket address: ``(host, port, ...)`` for IP, a path for AF_UNIX.

        :param address: The address passed to ``connect``.
        :param what: What was attempted, for the message.
        """
        if isinstance(address, tuple) and address:
            self.refuse_unless_local(address[0], what)


@pytest.fixture(autouse=True)
def network_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[NetworkGuard]:
    """Block, and fail the test on, any attempt to reach a host other than localhost.

    :param monkeypatch: Used to patch :mod:`socket` for the test.
    :yield: The guard, so a test can inspect what it blocked.
    """
    guard = NetworkGuard()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname

    def connect(self: socket.socket, address: object) -> None:
        guard.refuse_address(address, "connect to")
        real_connect(self, address)  # type: ignore[arg-type]

    def connect_ex(self: socket.socket, address: object) -> int:
        guard.refuse_address(address, "connect to")
        return real_connect_ex(self, address)  # type: ignore[arg-type]

    def getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        guard.refuse_unless_local(host, "look up")
        return real_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    def gethostbyname(host: str) -> str:
        guard.refuse_unless_local(host, "look up")
        return real_gethostbyname(host)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", gethostbyname)
    yield guard
    if guard.blocked:
        pytest.fail(f"test tried to reach the network: {', '.join(guard.blocked)}")
