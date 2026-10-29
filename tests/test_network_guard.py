"""Tests for the network guard in conftest.py: no test can reach the internet."""

import socket
from pathlib import Path

import pytest
from conftest import NetworkBlockedError, NetworkGuard, is_local_host


@pytest.mark.parametrize(
    "host",
    ["localhost", "LOCALHOST", "app.localhost", "127.0.0.1", "127.8.9.1", "::1", b"127.0.0.1"],
)
def test_loopback_hosts_are_local(host: object) -> None:
    """The name localhost and loopback addresses are allowed."""
    assert is_local_host(host)


@pytest.mark.parametrize(
    "host", ["example.com", "192.0.2.1", "10.0.0.1", "0.0.0.0", "localhost.example.com", None]
)
def test_other_hosts_are_not_local(host: object) -> None:
    """Anything else, private addresses included, is the network."""
    assert not is_local_host(host)


def test_a_connection_to_the_internet_is_blocked_and_recorded(network_guard: NetworkGuard) -> None:
    """The guard raises, and records the attempt so teardown can fail the test."""
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)

    assert network_guard.blocked
    network_guard.blocked.clear()


def test_a_lookup_of_an_internet_name_is_blocked(network_guard: NetworkGuard) -> None:
    """Name lookups are network traffic too."""
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyname("example.com")

    assert len(network_guard.blocked) == 2
    network_guard.blocked.clear()


def test_a_loopback_connection_is_allowed() -> None:
    """Tests may use a server on 127.0.0.1."""
    listener = socket.create_server(("127.0.0.1", 0))
    try:
        client = socket.create_connection(listener.getsockname(), timeout=1)
        client.close()
    finally:
        listener.close()


def test_a_test_that_swallows_the_error_still_fails(pytester: pytest.Pytester) -> None:
    """A test still fails when httpx turns the guard's error into its own and it is caught."""
    pytester.makeconftest((Path(__file__).parent / "conftest.py").read_text(encoding="utf-8"))
    pytester.makepyfile(
        """
        import httpx

        def test_reaches_out():
            try:
                httpx.get("http://192.0.2.1/", timeout=0.1)
            except Exception:
                pass
        """
    )

    outcome = pytester.runpytest_subprocess("-p", "no:cacheprovider")

    outcome.assert_outcomes(passed=1, errors=1)
    outcome.stdout.fnmatch_lines(["*test tried to reach the network*192.0.2.1*"])
