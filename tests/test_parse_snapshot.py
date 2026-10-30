"""Tests for snapshots: what each hash covers, and what it ignores (DESIGN.md section 3).

The volatile-token fixtures are two captures of one page; every other test
edits one thing in a fixture and checks which hash moved.
"""

import dataclasses
import hashlib
import json

import pytest
from parse_support import DEV_URL, WORDPRESS_URL, fixture, receipt_for
from selectolax.lexbor import LexborHTMLParser

from cernis.model import ErrorKind, Snapshot
from cernis.parse import (
    NORMALIZATION_VERSION,
    SiteType,
    SnapshotError,
    build_snapshot,
    read_article,
)
from cernis.parse.snapshot import defingerprint

VOLATILE_URL = "https://dev.to/example-author/volatile-tokens-7g8h"


def snap(body: bytes, url: str = VOLATILE_URL, site: SiteType | None = None) -> Snapshot:
    """Snapshot a body as the receipt of a 200 from ``url``.

    :param body: The body.
    :param url: The URL that answered.
    :param site: The declared site type.
    :return: The snapshot.
    """
    return build_snapshot(receipt_for(body, url), body, site=site)


def edited(name: str, old: str, new: str) -> bytes:
    """Return a fixture with one exact edit.

    :param name: The fixture name.
    :param old: Text that must occur in it.
    :param new: Its replacement.
    :return: The edited body.
    """
    text = fixture(name).decode("utf-8")
    assert old in text, old
    return text.replace(old, new).encode("utf-8")


def moved(a: Snapshot, b: Snapshot) -> set[str]:
    """Name the hashes that differ between two snapshots.

    :param a: One snapshot.
    :param b: The other.
    :return: A subset of ``{"content", "head", "frame"}``.
    """
    return {
        name
        for name in ("content", "head", "frame")
        if getattr(a, f"{name}_sha256") != getattr(b, f"{name}_sha256")
    }


# Volatile tokens


def test_two_captures_differing_only_in_volatile_tokens_hash_the_same() -> None:
    """The acceptance test: CSRF values, nonces, and asset hashes change nothing."""
    a, b = fixture("volatile-a"), fixture("volatile-b")
    assert a != b

    assert moved(snap(a), snap(b)) == set()
    assert snap(a).content_sha256 is not None


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQQ">\n  <link', 'changed">\n  <link'),
        ('nonce="bm9uY2UtYWFhYWFhYWE"></script>\n</head>', 'nonce="other"></script>\n</head>'),
        ('integrity="sha384-QUFB', 'integrity="sha384-CCCC'),
        (
            "crayons-1111111111111111111111111111111111111111111111111111111111111111.css",
            "crayons-ffffffff.css",
        ),
        ("application-a1b2c3d4e5f6a7b8.js", "application-0000000000000000.js"),
        ("?ver=6.6.1", "?ver=7.0"),
        ('data-csrf="QUFB', 'data-csrf="ZZZZ'),
        ('value="dG9rZW4tYWFhYWFhYWFhYWFhYWFh"', 'value="something-else"'),
        ('value="aaaaaaaaaa"', 'value="zzzzzzzzzz"'),
        ("logo.3f2a9c1b.png 1x", "logo.00000000.png 1x"),
        ('window.csrfToken = "QUFB', 'window.csrfToken = "ZZZZ'),
    ],
)
def test_each_volatile_token_rule_holds_on_its_own(old: str, new: str) -> None:
    """Each kind of volatile token can change without moving any hash."""
    base = fixture("volatile-a")

    assert moved(snap(base), snap(edited("volatile-a", old, new))) == set()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("application-a1b2c3d4e5f6a7b8.js", "application-a1b2c3d.js"),
        ('name="q">', 'name="q" value="typed">'),
        ('alt="DEV"', 'alt="DEV Community"'),
        ('<form action="/search"', '<form action="/find"'),
        ('/images/logo.3f2a9c1b.png"', '/images/brand.3f2a9c1b.png"'),
    ],
)
def test_changes_that_are_not_volatile_move_the_frame(old: str, new: str) -> None:
    """Near misses are real changes: a short hex run, a visible input, alt text, a path."""
    base = fixture("volatile-a")

    assert moved(snap(base), snap(edited("volatile-a", old, new))) == {"frame"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/assets/base-0f1e2d3c4b5a6978.js", "/assets/base-~.js"),
        ("/img/logo.3f2a9c1b.png", "/img/logo.~.png"),
        ("/a/b_deadbeef00/c", "/a/b_~/c"),
        ("/style.css?ver=6.6.2&x=1", "/style.css?ver=~&x=1"),
        ("/s.js?v=12&cb=99#f", "/s.js?v=~&cb=~#f"),
        ("a.1234abcd.png 1x, b.5678ef01.png 2x", "a.~.png 1x, b.~.png 2x"),
        ("/posts/2026/10/a-synthetic-post/", "/posts/2026/10/a-synthetic-post/"),
        ("/a-1a2b3c4/", "/a-1a2b3c4/"),
        ("/page?version-history=1", "/page?version-history=1"),
    ],
)
def test_defingerprint(url: str, expected: str) -> None:
    """Fingerprints of 8 or more hex digits and cache-busting values are replaced; nothing else."""
    assert defingerprint(url) == expected


# What each hash covers


def test_an_article_edit_moves_only_the_content_hash() -> None:
    """The author changed the article text."""
    base = fixture("dev-article")
    changed = edited("dev-article", "written by hand", "written by a hand")

    assert moved(snap(base, DEV_URL), snap(changed, DEV_URL)) == {"content"}


def test_a_metadata_edit_moves_only_the_head_hash() -> None:
    """The author changed a description."""
    base = fixture("dev-article")
    changed = edited(
        "dev-article",
        'content="A hand-written page that imitates a DEV article."',
        'content="New."',
    )

    assert moved(snap(base, DEV_URL), snap(changed, DEV_URL)) == {"head"}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('<html lang="en">', '<html lang="en-GB">'),
        (
            "<title>A Synthetic Post About Fixtures - DEV Community</title>",
            "<title>Renamed</title>",
        ),
        (
            'href="https://blog.example.com/2026/10/a-synthetic-post/"',
            'href="https://blog.example.com/other/"',
        ),
        ('"datePublished": "2026-10-20T12:00:00Z"', '"datePublished": "2026-10-21T12:00:00Z"'),
        ('<meta name="keywords" content="testing, fixtures, synthetic">', ""),
    ],
)
def test_each_kind_of_metadata_is_in_the_head_hash(old: str, new: str) -> None:
    """lang, title, canonical, JSON-LD, and meta all count."""
    base = fixture("dev-article")

    assert moved(snap(base, DEV_URL), snap(edited("dev-article", old, new), DEV_URL)) == {"head"}


def test_a_template_edit_moves_only_the_frame_hash() -> None:
    """The platform changed its footer."""
    base = fixture("dev-article")
    changed = edited("dev-article", "Privacy Policy", "Privacy")

    assert moved(snap(base, DEV_URL), snap(changed, DEV_URL)) == {"frame"}


def test_a_stylesheet_change_is_a_frame_change() -> None:
    """Non-metadata elements in <head> belong to the frame."""
    base = fixture("dev-article")
    changed = edited("dev-article", 'media="all"', 'media="print"')

    assert moved(snap(base, DEV_URL), snap(changed, DEV_URL)) == {"frame"}


def test_json_ld_in_the_body_counts_as_metadata() -> None:
    """A JSON-LD block outside <head> is in the head hash, not lost with the frame's scripts."""
    body = (
        b'<html><head></head><body><script type="application/ld+json">{"a": 1}</script>'
        b"</body></html>"
    )
    changed = body.replace(b'{"a": 1}', b'{"a": 2}')

    assert moved(snap(body), snap(changed)) == {"head"}


# Normalization


def test_whitespace_does_not_matter() -> None:
    """Reflowing the source changes no hash."""
    base = fixture("dev-article")
    reflowed = base.replace(b"\n  ", b"\n\t\t    ").replace(b"> <", b">\n<")

    assert moved(snap(base, DEV_URL), snap(reflowed, DEV_URL)) == set()


def test_attribute_order_does_not_matter() -> None:
    """Reordering attributes changes no hash."""
    base = fixture("dev-article")
    reordered = edited(
        "dev-article",
        '<a href="/" class="site-logo" aria-label="DEV Community Home">',
        '<a aria-label="DEV Community Home" class="site-logo" href="/">',
    )
    reordered = reordered.replace(
        b'<meta property="og:type" content="article">',
        b'<meta content="article" property="og:type">',
    )

    assert moved(snap(base, DEV_URL), snap(reordered, DEV_URL)) == set()


def test_metadata_order_does_not_matter() -> None:
    """The head hash is over a sorted list."""
    base = fixture("dev-article")
    title = b'  <meta property="og:title" content="A Synthetic Post About Fixtures">\n'
    swapped = base.replace(title, b"").replace(
        b'  <meta name="twitter:card"', title + b'  <meta name="twitter:card"'
    )

    assert moved(snap(base, DEV_URL), snap(swapped, DEV_URL)) == set()


def test_json_ld_key_order_does_not_matter() -> None:
    """JSON-LD is compared by value, not by spelling."""
    start = b'<html><head><script type="application/ld+json">'
    end = b"</script></head></html>"
    one = start + b'{"a": 1, "b": [2, 3]}' + end
    two = start + b'{ "b": [2,3],\n "a": 1 }' + end

    assert moved(snap(one), snap(two)) == set()


def test_unicode_nfc_does_not_matter() -> None:
    """Composed and decomposed accents are the same text."""
    base = edited("dev-article", "This page is written by hand.", "Caf\u00e9 page.")
    decomposed = edited("dev-article", "This page is written by hand.", "Cafe\u0301 page.")

    assert moved(snap(base, DEV_URL), snap(decomposed, DEV_URL)) == set()


def test_comments_do_not_matter() -> None:
    """HTML comments are not content, metadata, or frame."""
    base = fixture("dev-article")
    commented = base.replace(b"<footer", b"<!-- build 1234 --><footer")

    assert moved(snap(base, DEV_URL), snap(commented, DEV_URL)) == set()


# Extractors on the snapshot


def test_the_snapshot_records_the_extractor_and_normalization_versions() -> None:
    """A change to either shows in history as a CHECKER change."""
    snapshot = snap(fixture("dev-article"), DEV_URL)

    assert (snapshot.extractor_id, snapshot.extractor_version) == (
        "dev.article",
        f"1+n{NORMALIZATION_VERSION}",
    )
    assert snapshot.receipt_id == "r-001"


def test_a_page_with_no_extractor_has_no_content_hash() -> None:
    """The generic extractor finds no body, so content_sha256 is None (UNCLASSIFIED in history)."""
    snapshot = snap(fixture("wordpress-entry"), WORDPRESS_URL)

    assert (snapshot.extractor_id, snapshot.content_sha256) == ("generic", None)


def test_a_declared_wordpress_page_has_a_content_hash() -> None:
    """Declaring the site type picks wordpress.entry."""
    snapshot = snap(fixture("wordpress-entry"), WORDPRESS_URL, SiteType.WORDPRESS)

    assert snapshot.extractor_id == "wordpress.entry"
    assert snapshot.content_sha256 is not None


def test_an_ambiguous_body_has_no_content_hash() -> None:
    """Two candidate bodies: no guess."""
    snapshot = snap(fixture("malformed"), WORDPRESS_URL, SiteType.WORDPRESS)

    assert snapshot.content_sha256 is None


def test_the_hashes_of_a_fixture_are_pinned() -> None:
    """Any change to the normalization rules must bump NORMALIZATION_VERSION and these pins."""
    snapshot = snap(fixture("dev-article"), DEV_URL)

    assert NORMALIZATION_VERSION == "1"
    assert (snapshot.content_sha256, snapshot.head_sha256, snapshot.frame_sha256) == (
        "aee4cd69e2100ae79104d70f6d9a27d936266149ba2accabd8c5d20fd69a659e",
        "66984af10743c8f50832ed06cc679014f30f3da0c4f64cf2a38e471b7b95c002",
        "a7d26c8ffb8b6904420e6b485b4bb71ed059263b73fddfcd55c418417a3fa2d4",
    )


# What a snapshot is never made from


def test_a_body_cut_off_at_the_limit_is_never_snapshotted() -> None:
    """ADR-003: no snapshot from part of a page."""
    body = fixture("dev-article")
    receipt = dataclasses.replace(receipt_for(body), body_sha256=None, body_truncated_at=100)

    with pytest.raises(SnapshotError, match="no whole body"):
        build_snapshot(receipt, body[:100])


def test_a_failed_fetch_is_never_snapshotted() -> None:
    """A TIMEOUT receipt has no body to snapshot."""
    body = fixture("dev-article")
    receipt = dataclasses.replace(receipt_for(body), error_kind=ErrorKind.TIMEOUT, body_sha256=None)

    with pytest.raises(SnapshotError, match="no whole body"):
        build_snapshot(receipt, body)


def test_a_body_that_is_not_the_receipts_is_refused() -> None:
    """The body must hash to the receipt's body_sha256."""
    body = fixture("dev-article")

    with pytest.raises(SnapshotError, match="not the body"):
        build_snapshot(receipt_for(body), body + b" ")


def test_a_304_is_snapshotted_from_the_cached_body() -> None:
    """A 304's body_sha256 is the cached body's, so the cached body snapshots like a 200."""
    body = fixture("dev-article")
    not_modified = dataclasses.replace(receipt_for(body, DEV_URL), status_code=304)

    assert build_snapshot(not_modified, body) == snap(body, DEV_URL)
    assert hashlib.sha256(body).hexdigest() == not_modified.body_sha256


def test_the_content_hash_is_the_hash_of_the_article_text() -> None:
    """content_sha256 is SHA-256 over the JSON string of the normalized article text."""
    body = fixture("dev-article")
    article = read_article(LexborHTMLParser(body.decode("utf-8")), DEV_URL)
    assert article.text is not None

    expected = hashlib.sha256(json.dumps(article.text, ensure_ascii=False).encode("utf-8"))

    assert snap(body, DEV_URL).content_sha256 == expected.hexdigest()
