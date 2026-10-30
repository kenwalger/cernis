"""Tests for extraction from a receipt's body: what is found, and what could not be read."""

import dataclasses

import pytest
from parse_support import DEV_URL, fixture, receipt_for

from cernis.parse import ParsedPage, parse_page
from cernis.parse.html import decode_body, normalize_text


def page(name: str, url: str = "https://blog.example.com/p/") -> ParsedPage:
    """Parse a fixture.

    :param name: The fixture name.
    :param url: Its URL.
    :return: The parsed page.
    """
    body = fixture(name)
    return parse_page(receipt_for(body, url), body)


def test_a_dev_article_is_read_whole() -> None:
    """Title, lang, canonical, description, og:*, JSON-LD, and body links."""
    body = fixture("dev-article")
    parsed = parse_page(receipt_for(body, DEV_URL), body)

    assert parsed.receipt_id == "r-001"
    assert parsed.titles == ("A Synthetic Post About Fixtures - DEV Community",)
    assert parsed.lang == "en"
    assert [(c.href, c.in_head) for c in parsed.canonicals] == [
        ("https://blog.example.com/2026/10/a-synthetic-post/", True)
    ]
    assert parsed.descriptions == (
        "A hand-written page that imitates a DEV article, for Cernis's tests.",
    )
    assert [(t.attribute, t.content) for t in parsed.og("og:url")] == [
        ("property", "https://dev.to/example-author/a-synthetic-post-1a2b")
    ]
    (block,) = parsed.json_ld
    assert (block.parsed, block.types, block.error) == (True, ("Article",), None)
    assert isinstance(block.value, dict)
    assert block.value["headline"] == "A Synthetic Post About Fixtures"
    assert '"@type": "Article"' in block.raw
    assert [link.href for link in parsed.links][:3] == [
        "/",
        "/example-author",
        "https://www.example.org/paper",
    ]
    assert parsed.problems == ()


def test_a_wordpress_entry_is_read_whole() -> None:
    """Single-quoted attributes and entities are read as a browser reads them."""
    parsed = page("wordpress-entry")

    assert parsed.titles == ("A Synthetic Post About Fixtures \u2013 Example Blog",)
    assert parsed.lang == "en-US"
    assert parsed.descriptions == (
        "A hand-written page that imitates a WordPress entry, for Cernis's tests.",
    )
    assert parsed.json_ld[0].types == ("Article", "WebPage")
    assert parsed.problems == ()


def test_a_missing_canonical_is_an_empty_list() -> None:
    """Absence is recorded as absence: no canonicals, and nothing went wrong."""
    parsed = page("missing-canonical")

    assert parsed.canonicals == ()
    assert parsed.problems == ()


def test_every_canonical_is_kept_in_order() -> None:
    """Two canonicals are both recorded; rel is matched without regard to case."""
    parsed = page("two-canonicals")

    assert [c.href for c in parsed.canonicals] == [
        "https://blog.example.com/two-canonicals/",
        "https://dev.to/example-author/two-canonicals-5e6f",
    ]


def test_a_relative_canonical_is_recorded_as_written() -> None:
    """The parser does not resolve URLs; checks decide what a relative canonical means."""
    assert [c.href for c in page("relative-canonical").canonicals] == [
        "/2026/10/relative-canonical/"
    ]


def test_missing_and_odd_open_graph_tags_are_recorded_as_they_are() -> None:
    """An og property in name= is kept and labeled; an empty content is a value, not absence."""
    parsed = page("missing-og")

    assert parsed.og("og:url") == ()
    assert parsed.descriptions == ()
    assert parsed.lang is None
    assert [(t.attribute, t.content) for t in parsed.og("og:description")] == [
        ("name", "Written with name= instead of property=.")
    ]
    assert [t.content for t in parsed.og("og:image")] == [""]
    assert [t.content for t in parsed.og("OG:TITLE")] == ["A Post With Only Some Open Graph Tags"]


def test_broken_json_ld_is_recorded_with_its_raw_text_and_the_error() -> None:
    """Every block is kept: raw text, whether it parsed, its types, and why it failed."""
    parsed = page("broken-jsonld")

    summary = [(b.index, b.parsed, b.types) for b in parsed.json_ld]
    assert summary == [
        (0, True, ("BlogPosting",)),
        (1, False, ()),
        (2, True, ("Article", "NewsArticle", "Person")),
        (3, False, ()),
    ]
    assert parsed.json_ld[1].error == "not valid JSON"
    assert parsed.json_ld[1].detail is not None
    assert "line 1" in parsed.json_ld[1].detail
    assert parsed.json_ld[1].raw.endswith('"Missing brace"')
    assert parsed.json_ld[3].error == "the block is empty"
    assert [p for p in parsed.problems if p.startswith("JSON-LD")] == [
        f"JSON-LD block 1: not valid JSON ({parsed.json_ld[1].detail})",
        "JSON-LD block 3: the block is empty",
    ]


def test_malformed_html_is_read_without_raising() -> None:
    """Missing head and body tags, unquoted and misnested markup, and stray elements."""
    parsed = page("malformed")

    assert parsed.lang == "fr"
    assert parsed.titles == ("Une page mal form\u00e9e",)
    assert [c.href for c in parsed.canonicals] == ["https://blog.example.com/mal-formee/", None]
    assert "a canonical link has no href" in parsed.problems
    assert parsed.descriptions == ("Sans guillemets ni balises fermantes",)
    assert [t.content for t in parsed.og("og:title")] == [None]
    assert [(t.content, t.in_head) for t in parsed.og("og:image")] == [
        ("https://blog.example.com/dans-le-corps.png", False)
    ]
    # The unclosed second <a> is an active formatting element, so the parser
    # reopens it after </div>, as a browser does: three links, as a reader sees.
    assert [link.href for link in parsed.links] == [
        "https://www.example.org/lien",
        "/second",
        "/second",
    ]
    assert parsed.json_ld[0].parsed is False


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\x00\xff\xfe garbage",
        b"<" * 10000,
        b"<div>" * 20000,
        b"<html><head><title>x</title></head><body><a href>no value</a></body>",
        b'<script type="application/ld+json">' + b"[" * 100000 + b"</script>",
    ],
)
def test_nothing_makes_extraction_raise(body: bytes) -> None:
    """Empty, binary, pathological, and deeply nested input are all read."""
    parsed = parse_page(receipt_for(body), body)

    assert parsed.receipt_id == "r-001"


def test_a_deeply_nested_json_ld_block_is_recorded_not_raised() -> None:
    """JSON nested past the parser's recursion limit is an error on the block."""
    body = b'<script type="application/ld+json">' + b"[" * 100000 + b"</script>"

    (block,) = parse_page(receipt_for(body), body).json_ld

    assert block.parsed is False
    assert block.error is not None


def test_a_truncated_body_is_parsed_and_says_so() -> None:
    """A body cut off at the size limit is read as far as it goes, with a problem recorded."""
    body = fixture("dev-article")[:500]
    receipt = dataclasses.replace(receipt_for(body), body_sha256=None, body_truncated_at=500)

    parsed = parse_page(receipt, body)

    assert "the body was cut off at 500 bytes; only that much was read" in parsed.problems


def test_an_svg_title_in_the_body_is_not_the_page_title() -> None:
    """Only <title> elements in <head> are the page's title."""
    body = b"<html><head><title>Page</title></head><body><svg><title>Icon</title></svg></body>"

    assert parse_page(receipt_for(body), body).titles == ("Page",)


# Decoding


@pytest.mark.parametrize(
    ("body", "content_type", "text", "source"),
    [
        (b"\xef\xbb\xbfcaf\xc3\xa9", "text/html; charset=windows-1252", "caf\u00e9", "BOM"),
        (b"caf\xe9", "text/html; charset=ISO-8859-1", "caf\u00e9", "content-type"),
        (b"caf\xe9 \x80", "text/html; charset=latin1", "caf\u00e9 \u20ac", "content-type"),
        (
            b'<meta charset="windows-1252">caf\xe9',
            None,
            '<meta charset="windows-1252">caf\u00e9',
            "meta",
        ),
        (b"caf\xc3\xa9", None, "caf\u00e9", "default"),
        (b"caf\xc3\xa9", "text/html", "caf\u00e9", "default"),
    ],
)
def test_the_encoding_is_chosen_like_a_browser(
    body: bytes, content_type: str | None, text: str, source: str
) -> None:
    """BOM, then Content-Type, then <meta charset>, then UTF-8; Latin-1 means windows-1252."""
    decoded = decode_body(body, content_type)

    assert (decoded.text, decoded.source) == (text, source)
    assert decoded.problems == ()


def test_undecodable_bytes_are_replaced_and_recorded() -> None:
    """Invalid UTF-8 becomes U+FFFD, and the page says so."""
    decoded = decode_body(b"caf\xe9", "text/html; charset=utf-8")

    assert decoded.text == "caf\ufffd"
    assert decoded.problems == ("the body is not valid utf-8; undecodable bytes became U+FFFD",)


def test_an_unknown_charset_falls_back_and_is_recorded() -> None:
    """A charset Python does not know is skipped, with a problem."""
    decoded = decode_body(b"abc", "text/html; charset=x-nonexistent")

    assert (decoded.encoding, decoded.source) == ("utf-8", "default")
    assert decoded.problems == (
        "unknown charset 'x-nonexistent' in content-type; tried the next source",
    )


def test_normalize_text() -> None:
    """NFC, and every run of whitespace (including non-breaking space) is one space."""
    assert normalize_text("  cafe\u0301 \u00a0\n\t  bar  ") == "caf\u00e9 bar"


def test_json_ld_errors_are_worded_the_same_on_every_python() -> None:
    """The decoder's message differs between Python 3.12 and 3.13; Cernis's wording does not.

    The trailing comma below is reported as "Expecting property name" at one
    column on 3.12 and "Illegal trailing comma" at another on 3.13 and later.
    """
    body = b'<script type="application/ld+json">{"a": 1, }</script>'

    (block,) = parse_page(receipt_for(body), body).json_ld

    assert (block.parsed, block.error) == (False, "not valid JSON")
    assert block.detail is not None
