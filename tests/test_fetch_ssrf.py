"""Tests for the address screen in the fetcher: every hop, a receipt, and a reason (ADR-005)."""

from pathlib import Path

import pytest
from fetch_support import PUBLIC_ADDRESS, FakeResolver, Site, make_fetcher, redirect, respond

from cernis.fetch import FetchConfig
from cernis.model import ErrorKind

PAGE = "https://example.com/post"
ROBOTS = "https://example.com/robots.txt"


@pytest.mark.parametrize(
    ("address", "named"),
    [
        ("127.0.0.1", "loopback"),
        ("10.0.0.5", "private"),
        ("192.168.1.1", "private"),
        ("169.254.169.254", "link-local"),
        ("100.64.0.1", "carrier-grade NAT"),
        ("::1", "loopback"),
        ("fd00::1", "unique local"),
        ("::ffff:169.254.169.254", "link-local"),
    ],
)
def test_a_host_that_resolves_to_a_non_public_address_is_refused(
    tmp_path: Path, address: str, named: str
) -> None:
    """Nothing is sent, robots.txt included; the receipt says ADDRESS_REFUSED, with a reason."""
    site = Site()
    resolver = FakeResolver({"example.com": [address]})

    result = make_fetcher(site, tmp_path, resolver=resolver).fetch(PAGE)

    assert site.requests == []
    assert result.robots_receipts == ()
    (receipt,) = result.receipts
    assert (receipt.error_kind, receipt.final_url, receipt.status_code) == (
        ErrorKind.ADDRESS_REFUSED,
        PAGE,
        None,
    )
    (refusal,) = result.refusals
    assert (refusal.receipt_id, refusal.url) == (receipt.id, PAGE)
    assert refusal.reason.startswith(f"example.com resolves to {address} is ")
    assert named in refusal.reason


def test_one_non_public_address_among_public_ones_refuses_the_host(tmp_path: Path) -> None:
    """Every address must be public, or a resolver could hand back a private one second."""
    site = Site()
    resolver = FakeResolver({"example.com": [PUBLIC_ADDRESS, "10.0.0.1"]})

    result = make_fetcher(site, tmp_path, resolver=resolver).fetch(PAGE)

    assert result.receipts[0].error_kind is ErrorKind.ADDRESS_REFUSED
    assert "10.0.0.1" in result.refusals[0].reason
    assert site.requests == []


@pytest.mark.parametrize(
    "target",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8080/admin",
        "http://[::1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://internal.example/",
    ],
)
def test_a_redirect_to_a_non_public_address_is_refused(tmp_path: Path, target: str) -> None:
    """Each redirect target is screened before anything is sent to it, robots.txt included."""
    site = Site()
    site.add(PAGE, redirect(target))
    resolver = FakeResolver({"internal.example": ["192.168.0.10"]})

    result = make_fetcher(site, tmp_path, resolver=resolver).fetch(PAGE)

    (receipt,) = result.receipts
    assert receipt.error_kind is ErrorKind.ADDRESS_REFUSED
    assert receipt.redirect_chain == (PAGE,)
    assert receipt.final_url == target
    assert site.urls() == [ROBOTS, PAGE]
    assert [refusal.url for refusal in result.refusals] == [target]


def test_every_hop_is_screened_in_order(tmp_path: Path) -> None:
    """The page, its robots.txt, a redirect target, and that origin's robots.txt each resolve."""
    site = Site()
    site.add(PAGE, redirect("https://other.example/post"))
    site.add("https://other.example/post", respond(200))
    resolver = FakeResolver()

    make_fetcher(site, tmp_path, resolver=resolver).fetch(PAGE)

    # The page, example.com's robots.txt, the redirect target, then
    # other.example's robots.txt: one lookup each, before each is requested.
    assert resolver.lookups == [
        ("example.com", 443),
        ("example.com", 443),
        ("other.example", 443),
        ("other.example", 443),
    ]


def test_a_robots_txt_redirect_to_a_refused_host_makes_robots_unreachable(
    tmp_path: Path,
) -> None:
    """A refused robots.txt hop is a refusal, and robots.txt then counts as unreachable."""
    site = Site()
    site.add(ROBOTS, redirect("https://private.example/robots.txt"))
    resolver = FakeResolver({"private.example": ["10.1.1.1"]})

    result = make_fetcher(site, tmp_path, resolver=resolver).fetch(PAGE)

    (robots_receipt,) = result.robots_receipts
    assert robots_receipt.error_kind is ErrorKind.ADDRESS_REFUSED
    assert result.disallowed_url == PAGE
    assert [refusal.receipt_id for refusal in result.refusals] == [robots_receipt.id]
    assert "https://private.example/robots.txt" not in site.urls()


def test_a_host_that_does_not_resolve_is_connection(tmp_path: Path) -> None:
    """A name with no addresses is a CONNECTION failure naming the URL, not a refusal."""
    site = Site()
    resolver = FakeResolver({"example.com": []})

    result = make_fetcher(site, tmp_path, resolver=resolver).fetch(PAGE)

    (receipt,) = result.receipts
    assert (receipt.error_kind, receipt.final_url) == (ErrorKind.CONNECTION, PAGE)
    assert result.refusals == ()


def test_the_opt_in_allows_loopback(tmp_path: Path) -> None:
    """allow_loopback reaches 127.0.0.1, for testing against a local server."""
    site = Site()
    site.add("http://127.0.0.1:8000/post", respond(200))

    result = make_fetcher(site, tmp_path, allow_loopback=True).fetch("http://127.0.0.1:8000/post")

    assert result.receipts[0].status_code == 200


def test_the_opt_in_allows_loopback_only(tmp_path: Path) -> None:
    """allow_loopback does not open private or metadata addresses."""
    site = Site()
    site.add(PAGE, redirect("http://169.254.169.254/"))

    result = make_fetcher(site, tmp_path, allow_loopback=True).fetch(PAGE)

    assert result.receipts[0].error_kind is ErrorKind.ADDRESS_REFUSED


def test_loopback_is_refused_by_default() -> None:
    """The safe setting is the default."""
    assert FetchConfig().allow_loopback is False


def test_each_retry_is_screened_again(tmp_path: Path) -> None:
    """A retried attempt resolves again, so a host that turns private is refused then."""
    site = Site()
    site.add(PAGE, respond(429), respond(200))

    class Turning(FakeResolver):
        """Public for the first attempt and its robots.txt, private after."""

        def __call__(self, host: str, port: int) -> list[str]:
            """Resolve, turning private on the third lookup.

            :param host: The host.
            :param port: The port.
            :return: Its addresses.
            """
            self.lookups.append((host, port))
            return [PUBLIC_ADDRESS] if len(self.lookups) <= 2 else ["10.0.0.1"]

    result = make_fetcher(site, tmp_path, resolver=Turning(), min_interval=0).fetch(PAGE)

    assert [(r.error_kind, r.status_code) for r in result.receipts] == [
        (ErrorKind.NONE, 429),
        (ErrorKind.ADDRESS_REFUSED, None),
    ]
