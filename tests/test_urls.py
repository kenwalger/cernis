"""Tests for the one URL normalization and the shared URL comparison (DESIGN.md section 3)."""

from datetime import UTC, datetime

import pytest

from cernis.model import ErrorKind, Receipt
from cernis.urls import (
    UrlMatch,
    compare_urls,
    is_absolute_http_url,
    normalize_percent_encoding,
    normalize_url,
)


def receipt(requested: str, chain: tuple[str, ...], final: str | None) -> Receipt:
    """Build a receipt for a fetch that followed redirects.

    :param requested: The requested URL.
    :param chain: The URLs that redirected.
    :param final: The URL that answered.
    :return: The receipt.
    """
    return Receipt(
        id="r-007",
        requested_url=requested,
        final_url=final,
        redirect_chain=chain,
        status_code=200,
        error_kind=ErrorKind.NONE,
        fetched_at=datetime(2026, 10, 30, tzinfo=UTC),
        body_sha256=None,
        cernis_version="0.1.0.dev0",
        user_agent="Cernis/0.1.0.dev0 (+https://github.com/kenwalger/cernis)",
    )


# IDENTICAL


def test_identical_strings_are_identical() -> None:
    """The strings match exactly, so there is nothing to explain."""
    result = compare_urls("https://example.com/a?b=1#c", "https://example.com/a?b=1#c")
    assert (result.outcome, result.reasons, result.receipt_id) == (UrlMatch.IDENTICAL, (), None)


def test_identical_even_when_neither_is_absolute() -> None:
    """Exact equality needs no parsing."""
    assert compare_urls("/a", "/a").outcome is UrlMatch.IDENTICAL


# EQUIVALENT, one normalization at a time


@pytest.mark.parametrize(
    ("a", "b", "reason"),
    [
        ("HTTPS://example.com/a", "https://example.com/a", "scheme case"),
        ("https://EXAMPLE.com/a", "https://example.com/a", "host case"),
        ("https://Example.COM/a", "https://example.com/a", "host case"),
        ("https://example.com:443/a", "https://example.com/a", "default port"),
        ("http://example.com:80/a", "http://example.com/a", "default port"),
        ("https://example.com:/a", "https://example.com/a", "default port"),
        ("https://example.com/a#top", "https://example.com/a", "fragment"),
        ("https://example.com/a#top", "https://example.com/a#bottom", "fragment"),
        ("https://example.com/a/", "https://example.com/a", "trailing slash"),
        ("https://example.com", "https://example.com/", "empty path"),
        ("https://example.com/%7Euser", "https://example.com/~user", "percent-encoding"),
        ("https://example.com/a%2fb", "https://example.com/a%2Fb", "percent-encoding"),
        ("https://example.com/caf\u00e9", "https://example.com/caf%C3%A9", "percent-encoding"),
        ("https://example.com/a b", "https://example.com/a%20b", "percent-encoding"),
        ("https://example.com/a/../b", "https://example.com/b", "dot segments"),
        ("https://example.com/./a", "https://example.com/a", "dot segments"),
        ("https://b\u00fccher.de/a", "https://xn--bcher-kva.de/a", "internationalized host"),
        ("https://B\u00dcCHER.de/a", "https://xn--bcher-kva.de/a", "internationalized host"),
        (" https://example.com/a ", "https://example.com/a", "surrounding whitespace"),
        ("https://example.com/cafe\u0301", "https://example.com/caf\u00e9", "Unicode NFC"),
    ],
)
def test_each_cosmetic_difference_is_equivalent_and_named(a: str, b: str, reason: str) -> None:
    """Each normalization in DESIGN.md section 3 makes the pair EQUIVALENT, and says which."""
    result = compare_urls(a, b)

    assert result.outcome is UrlMatch.EQUIVALENT
    assert reason in result.reasons


def test_several_differences_are_all_named_in_order() -> None:
    """Every normalization that mattered is listed, in a fixed order."""
    result = compare_urls("HTTPS://EXAMPLE.com:443/a/#x", "https://example.com/a")

    assert result.reasons == (
        "scheme case",
        "host case",
        "default port",
        "trailing slash",
        "fragment",
    )


def test_a_normalization_both_sides_share_is_not_a_reason() -> None:
    """Two URLs with the same uppercase host differ only by their fragment."""
    result = compare_urls("https://EXAMPLE.com/a#x", "https://EXAMPLE.com/a")

    assert result.reasons == ("fragment",)


def test_comparison_is_symmetric() -> None:
    """compare(a, b) and compare(b, a) agree."""
    a, b = "https://Example.com:443/p/", "https://example.com/p"
    assert compare_urls(a, b) == compare_urls(b, a)


# DIFFERENT


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("http://example.com/a", "https://example.com/a"),
        ("https://example.com/a", "https://www.example.com/a"),
        ("https://example.com/a", "https://example.com/b"),
        ("https://example.com/A", "https://example.com/a"),
        ("https://example.com:8443/a", "https://example.com/a"),
        ("https://example.com/a?x=1", "https://example.com/a"),
        ("https://example.com/a?x=1", "https://example.com/a?X=1"),
        ("https://example.com/a?x=1&y=2", "https://example.com/a?y=2&x=1"),
        ("https://example.com/a?utm_source=dev", "https://example.com/a"),
        ("https://example.com/a?", "https://example.com/a"),
        ("https://example.com/a?x=%41", "https://example.com/a?x=A"),
        ("https://example.com/a%2Fb", "https://example.com/a/b"),
        ("https://example.com/a//", "https://example.com/a"),
        ("https://user@example.com/a", "https://example.com/a"),
        ("https://example.com/a", "/a"),
        ("ftp://example.com/a", "https://example.com/a"),
    ],
)
def test_real_differences_are_different(a: str, b: str) -> None:
    """Scheme, host, path, port, query (exactly), user information, and relative URLs differ."""
    result = compare_urls(a, b)

    assert result.outcome is UrlMatch.DIFFERENT
    assert result.reasons == ()


def test_a_url_that_does_not_parse_is_only_ever_identical() -> None:
    """An unparseable URL is compared as a string: identical to itself, different from others."""
    assert compare_urls("http://[::1/a", "http://[::1/a").outcome is UrlMatch.IDENTICAL
    assert compare_urls("http://[::1/a", "http://[::1]/a").outcome is UrlMatch.DIFFERENT
    assert compare_urls("https://example.com:99999/", "https://example.com/").outcome is (
        UrlMatch.DIFFERENT
    )


# Redirects


def test_a_redirect_makes_two_urls_equivalent_with_its_receipt() -> None:
    """One URL redirecting to the other is EQUIVALENT, citing the redirect receipt."""
    redirect = receipt(
        "https://example.com/old", ("https://example.com/old",), "https://example.com/new"
    )

    result = compare_urls(
        "https://example.com/old", "https://example.com/new", redirects=[redirect]
    )

    assert result.outcome is UrlMatch.EQUIVALENT
    assert result.reasons == ("redirect",)
    assert result.receipt_id == "r-007"


def test_a_redirect_works_in_either_direction_and_through_a_chain() -> None:
    """The later URL may be the first argument, and the hops may be several."""
    chain = ("http://example.com/a", "https://example.com/a")
    redirect = receipt("http://example.com/a", chain, "https://example.com/b/")

    result = compare_urls("https://example.com/b", "http://example.com/a", redirects=[redirect])

    assert (result.outcome, result.receipt_id) == (UrlMatch.EQUIVALENT, "r-007")


def test_a_receipt_with_no_redirect_proves_nothing() -> None:
    """A receipt that did not redirect cannot make two URLs equivalent."""
    plain = receipt("https://example.com/new", (), "https://example.com/new")

    result = compare_urls("https://example.com/old", "https://example.com/new", redirects=[plain])

    assert result.outcome is UrlMatch.DIFFERENT


def test_an_unrelated_redirect_proves_nothing() -> None:
    """A redirect between other URLs does not count."""
    other = receipt("https://example.com/x", ("https://example.com/x",), "https://example.com/y")

    result = compare_urls("https://example.com/old", "https://example.com/new", redirects=[other])

    assert result.outcome is UrlMatch.DIFFERENT


# normalize_url


@pytest.mark.parametrize(
    ("url", "normalized"),
    [
        ("HTTPS://Example.COM:443/a/./b/../c/?q=Z#f", "https://example.com/a/c?q=Z"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/?", "https://example.com/?"),
        ("https://b\u00fccher.de/caf\u00e9", "https://xn--bcher-kva.de/caf%C3%A9"),
        ("https://[::1]:8080/x", "https://[::1]:8080/x"),
        ("https://my_host.example/x", "https://my_host.example/x"),
    ],
)
def test_normalize_url(url: str, normalized: str) -> None:
    """The normalized form is what EQUIVALENT compares, and what finding keys hash."""
    assert normalize_url(url) == normalized


@pytest.mark.parametrize("url", ["/relative", "og:image", "mailto:me@example.com", "http://[::1/x"])
def test_normalize_url_leaves_anything_else_as_nfc_text(url: str) -> None:
    """A string that is not an absolute http(s) URL comes back unchanged, apart from NFC."""
    assert normalize_url(url) == url


def test_normalize_url_is_idempotent() -> None:
    """Normalizing twice changes nothing more."""
    once = normalize_url("HTTPS://B\u00fccher.de:443/a/../caf\u00e9/#x")
    assert normalize_url(once) == once


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/a", True),
        ("HTTP://example.com", True),
        ("/a", False),
        ("og:image", False),
        ("mailto:me@example.com", False),
        ("https:///a", False),
        ("http://[::1/", False),
    ],
)
def test_is_absolute_http_url(url: str, expected: bool) -> None:
    """Only absolute http and https URLs with a host count."""
    assert is_absolute_http_url(url) is expected


# The shared percent-encoding normalization


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        ("/%7e%41%5F", "/~A_"),
        ("/%2f%3a", "/%2F%3A"),
        ("/caf\u00e9", "/caf%C3%A9"),
        ("/a b<c>", "/a%20b%3Cc%3E"),
        ("/100%", "/100%25"),
        ("/%zz", "/%25zz"),
        ("/a*b$c", "/a*b$c"),
    ],
)
def test_normalize_percent_encoding(text: str, normalized: str) -> None:
    """Unreserved octets are decoded, others uppercased, the rest encoded as UTF-8."""
    assert normalize_percent_encoding(text) == normalized


def test_percent_encoding_can_map_literal_characters() -> None:
    """The robots matcher maps literal ``*`` and ``$`` through the same function."""
    assert normalize_percent_encoding("/a*b$", literal={"*": "%2A", "$": "%24"}) == "/a%2Ab%24"
    assert normalize_percent_encoding("/a%2Ab", literal={"*": "%2A"}) == "/a%2Ab"
