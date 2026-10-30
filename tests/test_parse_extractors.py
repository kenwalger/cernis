"""Tests for article-body extractors: selection, what they find, and refusing to guess."""

import pytest
from parse_support import DEV_URL, WORDPRESS_URL, fixture
from selectolax.lexbor import LexborHTMLParser

from cernis.parse import (
    DEV_ARTICLE,
    EXTRACTORS,
    GENERIC,
    WORDPRESS_ENTRY,
    SiteType,
    choose_extractor,
    read_article,
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
