"""The non-public address screen (DESIGN.md section 6, ADR-005).

Cernis refuses to connect to an address that is not on the public internet,
so a page or a redirect cannot point it at this machine, a private network,
or a cloud metadata service. The ranges are listed here explicitly rather
than taken from :mod:`ipaddress`'s ``is_private`` and ``is_global``, whose
answers have changed between Python versions.

An IPv6 address that embeds an IPv4 address (IPv4-mapped ``::ffff:0:0/96``,
IPv4-compatible ``::/96``, NAT64 ``64:ff9b::/96``, and 6to4 ``2002::/16``)
is judged by the IPv4 address inside it.
"""

import ipaddress

IPv4 = ipaddress.IPv4Network
IPv6 = ipaddress.IPv6Network

_REFUSED_V4: tuple[tuple[ipaddress.IPv4Network, str], ...] = (
    (IPv4("0.0.0.0/8"), "unspecified (0.0.0.0/8)"),
    (IPv4("10.0.0.0/8"), "private (RFC 1918, 10.0.0.0/8)"),
    (IPv4("100.64.0.0/10"), "carrier-grade NAT (100.64.0.0/10)"),
    (IPv4("127.0.0.0/8"), "loopback (127.0.0.0/8)"),
    (IPv4("169.254.0.0/16"), "link-local, including cloud metadata (169.254.0.0/16)"),
    (IPv4("172.16.0.0/12"), "private (RFC 1918, 172.16.0.0/12)"),
    (IPv4("192.168.0.0/16"), "private (RFC 1918, 192.168.0.0/16)"),
    (IPv4("224.0.0.0/4"), "multicast (224.0.0.0/4)"),
    (IPv4("255.255.255.255/32"), "broadcast (255.255.255.255)"),
    (IPv4("240.0.0.0/4"), "reserved (240.0.0.0/4)"),
)

_REFUSED_V6: tuple[tuple[ipaddress.IPv6Network, str], ...] = (
    (IPv6("::/128"), "unspecified (::)"),
    (IPv6("::1/128"), "loopback (::1)"),
    (IPv6("fc00::/7"), "unique local (fc00::/7)"),
    (IPv6("fe80::/10"), "link-local (fe80::/10)"),
    (IPv6("fec0::/10"), "site-local (fec0::/10)"),
    (IPv6("ff00::/8"), "multicast (ff00::/8)"),
)

_LOOPBACK_V4 = IPv4("127.0.0.0/8")
_LOOPBACK_V6 = IPv6("::1/128")
_MAPPED = IPv6("::ffff:0:0/96")
_COMPATIBLE = IPv6("::/96")
_NAT64 = IPv6("64:ff9b::/96")


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address an IPv6 address carries, if it carries one.

    :param address: The IPv6 address.
    :return: The embedded IPv4 address, or ``None``.
    """
    if address in _MAPPED or address in _NAT64 or address in _COMPATIBLE:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address.sixtofour


def refusal_reason(address: str, *, allow_loopback: bool) -> str | None:
    """Say why Cernis will not connect to an address, if it will not.

    :param address: An IP address as text, as a resolver returns it; an IPv6
        zone (``%eth0``) is ignored.
    :param allow_loopback: Whether loopback addresses are allowed (the
        opt-in for testing against a local server). Nothing else is.
    :return: The reason, naming the address and its range, or ``None`` if
        the address is public.
    """
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return f"{address!r} is not an IP address"
    checked: ipaddress.IPv4Address | ipaddress.IPv6Address = parsed
    if isinstance(parsed, ipaddress.IPv6Address):
        if parsed in _LOOPBACK_V6:
            return None if allow_loopback else f"{address} is loopback (::1)"
        for network, kind in _REFUSED_V6:
            if parsed in network:
                return f"{address} is {kind}"
        embedded = _embedded_ipv4(parsed)
        if embedded is None:
            return None
        checked = embedded
    if checked in _LOOPBACK_V4:
        return None if allow_loopback else f"{address} is loopback (127.0.0.0/8)"
    for network4, kind in _REFUSED_V4:
        if checked in network4:
            return f"{address} is {kind}"
    return None
