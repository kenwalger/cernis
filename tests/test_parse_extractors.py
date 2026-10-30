"""Tests for article-body extractors: selection, what they find, and refusing to guess."""

import pytest
from parse_support import DEV_URL, WORDPRESS_URL, fixture
from selectolax.lexbor import LexborHTMLParser

from cernis.model import ExtractorSelection
from cernis.parse import (
    DEV_ARTICLE,
    EXTRACTORS,
    GENERIC,
    WORDPRESS_ENTRY,
    SitePrefix,
    SiteType,
    choose_extractor,
    prefix_site,
    read_article,
    resolve_site,
    select_extractor,
)


def tree(name: str) -> LexborHTMLParser:
    """Parse a fixture into a tree.

    :param name: The fixture name.
    :return: The tree.
    """
    return LexborHTMLParser(fixture(name).decode("utf-8"))


@pytest.mark.parametrize(
    ("url", "site", "expected"),
    [
        (DEV_URL, None, DEV_ARTICLE),
        ("https://www.dev.to/example-author/post", None, DEV_ARTICLE),
        ("https://DEV.TO/example-author/post", None, DEV_ARTICLE),
        (WORDPRESS_URL, None, GENERIC),
        (WORDPRESS_URL, SiteType.WORDPRESS, WORDPRESS_ENTRY),
        (DEV_URL, SiteType.WORDPRESS, WORDPRESS_ENTRY),
        (WORDPRESS_URL, SiteType.DEV, DEV_ARTICLE),
        ("not a url", None, GENERIC),
        ("http://[::1/", None, GENERIC),
    ],
)
def test_the_extractor_is_chosen_by_declared_site_then_host(
    url: str, site: SiteType | None, expected: object
) -> None:
    """A declared site type wins; dev.to is recognized by host; anything else is generic."""
    assert choose_extractor(url, site) is expected


def test_every_extractor_has_a_unique_id_and_a_version() -> None:
    """Extractor id and version go on every snapshot."""
    assert [(e.id, e.version) for e in EXTRACTORS] == [
        ("dev.article", "1"),
        ("wordpress.entry", "1"),
        ("generic", "1"),
    ]


def test_the_dev_extractor_reads_the_article_body() -> None:
    """#article-body's visible text and links, without the inline script."""
    article = read_article(tree("dev-article"), DEV_URL)

    assert (article.extractor, article.found, article.problem) == (DEV_ARTICLE, True, None)
    assert article.text is not None
    assert article.text.startswith("This page is written by hand.")
    assert "More text, spread across lines." in article.text
    assert "articleBodyLoaded" not in article.text
    assert "Top comments" not in article.text
    assert [link.href for link in article.links] == [
        "https://www.example.org/paper",
        "/example-author/another-post-3c4d",
        "#comments",
    ]
    assert article.links[0].text == "a paper"


def test_the_wordpress_extractor_reads_the_entry_content() -> None:
    """.entry-content, not the header, footer, or comment form."""
    article = read_article(tree("wordpress-entry"), WORDPRESS_URL, SiteType.WORDPRESS)

    assert article.found
    assert article.text is not None
    assert article.text.startswith("This page is written by hand.")
    assert "Posted in" not in article.text
    assert [link.href for link in article.links] == [
        "https://www.example.org/paper",
        "https://blog.example.com/2026/09/an-earlier-post/",
    ]


def test_the_wordpress_extractor_falls_back_to_block_theme_content() -> None:
    """A block theme's .wp-block-post-content is used when there is no .entry-content."""
    page = LexborHTMLParser('<main><div class="wp-block-post-content"><p>Body</p></div></main>')

    article = read_article(page, WORDPRESS_URL, SiteType.WORDPRESS)

    assert (article.found, article.text) == (True, "Body")


def test_two_candidate_bodies_are_ambiguous_and_none_is_chosen() -> None:
    """The extractor never guesses between two matches."""
    article = read_article(tree("malformed"), WORDPRESS_URL, SiteType.WORDPRESS)

    assert (article.found, article.text, article.links) == (False, None, ())
    assert article.problem == (
        "wordpress.entry: 2 elements match '.entry-content', so the article body is ambiguous"
    )


def test_a_missing_body_is_reported() -> None:
    """A declared DEV page without #article-body has no body, and says why."""
    article = read_article(tree("wordpress-entry"), WORDPRESS_URL, SiteType.DEV)

    assert not article.found
    assert article.problem == "dev.article: no element matches '#article-body'"


def test_the_generic_extractor_finds_no_body_by_design() -> None:
    """No body and no problem: history will say UNCLASSIFIED rather than guess."""
    article = read_article(tree("wordpress-entry"), WORDPRESS_URL)

    assert (article.extractor, article.found, article.text, article.problem) == (
        GENERIC,
        False,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("url", "site", "selection"),
    [
        (DEV_URL, None, ExtractorSelection.HOST),
        (DEV_URL, SiteType.DEV, ExtractorSelection.DECLARED),
        (WORDPRESS_URL, SiteType.WORDPRESS, ExtractorSelection.DECLARED),
        (WORDPRESS_URL, None, ExtractorSelection.GENERIC),
    ],
)
def test_selection_says_how_the_extractor_was_chosen(
    url: str, site: SiteType | None, selection: ExtractorSelection
) -> None:
    """Declared, host, or generic (DESIGN.md section 3)."""
    assert select_extractor(url, site)[1] is selection


# Prefix rules (Session 4d)

BLOG = SitePrefix(prefix="https://www.kenwalger.com/blog/", site=SiteType.WORDPRESS)
DEV_BLOG = SitePrefix(prefix="https://www.kenwalger.com/blog/dev-copies", site=SiteType.DEV)
POST = "https://www.kenwalger.com/blog/writing/views-measure-views-nine-years-writing"


@pytest.mark.parametrize(
    ("url", "declared", "prefixes", "expected"),
    [
        (POST, None, [BLOG], (SiteType.WORDPRESS, ExtractorSelection.PREFIX)),
        (POST, SiteType.DEV, [BLOG], (SiteType.DEV, ExtractorSelection.DECLARED)),
        ("https://www.kenwalger.com/about/", None, [BLOG], (None, ExtractorSelection.GENERIC)),
        (DEV_URL, None, [BLOG], (SiteType.DEV, ExtractorSelection.HOST)),
        (
            DEV_URL,
            None,
            [SitePrefix(prefix="https://dev.to/", site=SiteType.WORDPRESS)],
            (SiteType.WORDPRESS, ExtractorSelection.PREFIX),
        ),
    ],
)
def test_declared_then_prefix_then_host_then_generic(
    url: str,
    declared: SiteType | None,
    prefixes: list[SitePrefix],
    expected: tuple[SiteType | None, ExtractorSelection],
) -> None:
    """A declaration beats a prefix, which beats the host, which beats nothing."""
    assert resolve_site(url, declared, prefixes) == expected


def test_the_longest_matching_prefix_wins() -> None:
    """A more specific prefix overrides a broader one, in either order."""
    url = "https://www.kenwalger.com/blog/dev-copies/a-post"

    assert prefix_site(url, [BLOG, DEV_BLOG]) is SiteType.DEV
    assert prefix_site(url, [DEV_BLOG, BLOG]) is SiteType.DEV
    assert prefix_site(POST, [BLOG, DEV_BLOG]) is SiteType.WORDPRESS


@pytest.mark.parametrize(
    ("url", "matches"),
    [
        ("https://www.kenwalger.com/blog", True),
        ("https://www.kenwalger.com/blog/", True),
        ("https://WWW.kenwalger.com:443/blog/x/#top", True),
        ("https://www.kenwalger.com/blog?page=2", True),
        ("https://www.kenwalger.com/blogger", False),
        ("https://www.kenwalger.com/", False),
        ("http://www.kenwalger.com/blog/x", False),
        ("https://kenwalger.com/blog/x", False),
    ],
)
def test_prefixes_match_whole_segments_after_normalization(url: str, matches: bool) -> None:
    """Case, default ports, and trailing slashes do not matter; scheme, host, and segments do."""
    assert (prefix_site(url, [BLOG]) is SiteType.WORDPRESS) is matches


def test_a_root_prefix_covers_a_whole_host() -> None:
    """A prefix of just the origin covers every URL on it."""
    rule = SitePrefix(prefix="https://blog.example.com", site=SiteType.WORDPRESS)

    assert prefix_site("https://blog.example.com/2026/10/x/", [rule]) is SiteType.WORDPRESS
    assert prefix_site("https://other.example.com/", [rule]) is None


def test_select_extractor_reports_a_prefix_selection() -> None:
    """The extractor follows the prefix's site type, and says so."""
    assert select_extractor(POST, None, [BLOG]) == (WORDPRESS_ENTRY, ExtractorSelection.PREFIX)
