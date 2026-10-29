"""Tests for the non-public address screen (ADR-005)."""

import pytest

from cernis.fetch.addresses import refusal_reason


@pytest.mark.parametrize(
    ("address", "named"),
    [
        ("127.0.0.1", "loopback"),
        ("127.255.0.9", "loopback"),
        ("10.1.2.3", "private"),
        ("172.16.0.1", "private"),
        ("172.31.255.254", "private"),
        ("192.168.1.10", "private"),
        ("169.254.169.254", "link-local"),
        ("169.254.0.1", "link-local"),
        ("100.64.0.1", "carrier-grade NAT"),
        ("100.127.255.254", "carrier-grade NAT"),
        ("0.0.0.0", "unspecified"),
        ("0.1.2.3", "unspecified"),
        ("255.255.255.255", "broadcast"),
        ("224.0.0.1", "multicast"),
        ("240.0.0.1", "reserved"),
        ("::1", "loopback"),
        ("::", "unspecified"),
        ("fc00::1", "unique local"),
        ("fd12:3456::1", "unique local"),
        ("fe80::1", "link-local"),
        ("fe80::1%eth0", "link-local"),
        ("febf::1", "link-local"),
        ("ff02::1", "multicast"),
        ("::ffff:127.0.0.1", "loopback"),
        ("::ffff:169.254.169.254", "link-local"),
        ("::ffff:10.0.0.1", "private"),
        ("64:ff9b::a9fe:a9fe", "link-local"),
        ("2002:c0a8:0101::1", "private"),
        ("::127.0.0.1", "loopback"),
    ],
)
def test_non_public_addresses_are_refused_with_a_named_reason(address: str, named: str) -> None:
    """Each refused address says which kind of non-public address it is."""
    reason = refusal_reason(address, allow_loopback=False)

    assert reason is not None
    assert named in reason
    assert address.split("%")[0] in reason


@pytest.mark.parametrize(
    "address",
    [
        "93.184.215.14",
        "203.0.113.10",
        "8.8.8.8",
        "172.15.255.255",
        "172.32.0.0",
        "100.63.255.255",
        "100.128.0.0",
        "169.253.255.255",
        "2606:4700::6810:84e5",
        "2001:db8::1",
        "::ffff:8.8.8.8",
        "2002:0808:0808::1",
    ],
)
def test_public_addresses_are_allowed(address: str) -> None:
    """Addresses outside every refused range, including just past their edges, pass."""
    assert refusal_reason(address, allow_loopback=False) is None


@pytest.mark.parametrize("address", ["127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1"])
def test_the_opt_in_allows_loopback(address: str) -> None:
    """allow_loopback lets tests reach a server on this machine."""
    assert refusal_reason(address, allow_loopback=True) is None


@pytest.mark.parametrize("address", ["10.0.0.1", "169.254.169.254", "fe80::1", "::"])
def test_the_opt_in_allows_loopback_only(address: str) -> None:
    """The opt-in never opens private, link-local, or unspecified addresses."""
    assert refusal_reason(address, allow_loopback=True) is not None


@pytest.mark.parametrize("address", ["", "localhost", "999.1.1.1", "not an address"])
def test_something_that_is_not_an_address_is_refused(address: str) -> None:
    """The screen fails closed on anything it cannot read as an IP address."""
    assert refusal_reason(address, allow_loopback=True) is not None
