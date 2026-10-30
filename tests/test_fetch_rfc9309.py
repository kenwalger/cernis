"""Tests for Cernis's RFC 9309 matcher: groups, longest match, wildcards, encoding.

The examples marked "RFC 9309" are taken from the RFC's own text. Every
test here runs the same on Python 3.12, 3.13, and 3.14, because the matcher
uses no part of :mod:`urllib.robotparser`.
"""

import pytest

from cernis.fetch.rfc9309 import MATCHER_VERSION, RobotsRules

RFC_SIMPLE_EXAMPLE = """\
User-Agent: *
Disallow: *.gif$
Disallow: /example/
Allow: /publications/

User-Agent: foobot
Disallow:/
Allow:/example/page.html
Allow:/example/allowed.gif

User-Agent: barbot
User-Agent: bazbot
Disallow: /example/page.html

User-Agent: quxbot
"""


def allowed(text: str, token: str, path: str) -> bool:
    """Check one path.

    :param text: The robots.txt text.
    :param token: The crawler's product token.
    :param path: The path and query, as sent.
    :return: Whether the path is allowed.
    """
    return RobotsRules.parse(text).check(token, path).allowed


def test_the_matcher_has_its_own_version() -> None:
    """A change to matching is a CHECKER change, so the matcher carries a version."""
    assert MATCHER_VERSION == "1"


# RFC 9309 section 5.1, the simple example


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/example/page.html", True),
        ("/example/allowed.gif", True),
        ("/example/other.html", False),
        ("/publications/", False),
        ("/", False),
    ],
)
def test_rfc_example_foobot(path: str, expected: bool) -> None:
    """RFC 9309 5.1: foobot may fetch only the two pages its group allows."""
    assert allowed(RFC_SIMPLE_EXAMPLE, "foobot", path) is expected


@pytest.mark.parametrize("token", ["barbot", "bazbot"])
@pytest.mark.parametrize(
    ("path", "expected"),
    [("/example/page.html", False), ("/example/other.html", True), ("/image.gif", True)],
)
def test_rfc_example_barbot_and_bazbot_share_a_group(token: str, path: str, expected: bool) -> None:
    """RFC 9309 5.1: two user-agent lines open one group, and the * group does not apply."""
    assert allowed(RFC_SIMPLE_EXAMPLE, token, path) is expected


@pytest.mark.parametrize("path", ["/example/page.html", "/image.gif", "/anything"])
def test_rfc_example_quxbot_has_an_empty_group(path: str) -> None:
    """RFC 9309 5.1: a group with no rules allows everything, and still replaces *."""
    assert allowed(RFC_SIMPLE_EXAMPLE, "quxbot", path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/image.gif", False),
        ("/dir/photo.gif", False),
        ("/photo.gif?size=2", True),
        ("/example/", False),
        ("/example/page.html", False),
        ("/publications/", True),
        ("/publications/paper.gif", True),
        ("/other", True),
    ],
)
def test_rfc_example_other_crawlers_use_the_star_group(path: str, expected: bool) -> None:
    """RFC 9309 5.1: an unnamed crawler obeys * (with ``$`` ending ``*.gif``)."""
    assert allowed(RFC_SIMPLE_EXAMPLE, "Cernis", path) is expected


# RFC 9309 section 5.2, longest match


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/example/page/", True), ("/example/page/disallowed.gif", False)],
)
def test_rfc_example_longest_match(path: str, expected: bool) -> None:
    """RFC 9309 5.2: the more specific rule wins, whatever the order."""
    rules = "User-Agent: foobot\nAllow: /example/page/\nDisallow: /example/page/disallowed.gif\n"
    reordered = (
        "User-Agent: foobot\nDisallow: /example/page/disallowed.gif\nAllow: /example/page/\n"
    )
    assert allowed(rules, "foobot", path) is expected
    assert allowed(reordered, "foobot", path) is expected


def test_longest_match_beats_file_order() -> None:
    """A longer Allow after a shorter Disallow wins, wherever it is in the file."""
    assert allowed("User-agent: *\nDisallow: /\nAllow: /post\n", "Cernis", "/post")
    assert not allowed("User-agent: *\nAllow: /\nDisallow: /secret\n", "Cernis", "/secret/x")


@pytest.mark.parametrize(
    "rules",
    [
        "User-agent: *\nDisallow: /page\nAllow: /page\n",
        "User-agent: *\nAllow: /page\nDisallow: /page\n",
    ],
)
def test_allow_wins_a_tie(rules: str) -> None:
    """RFC 9309 2.2.2: equivalent Allow and Disallow rules resolve to Allow."""
    assert allowed(rules, "Cernis", "/page")


# Groups (RFC 9309 section 2.2.1)


def test_groups_for_the_same_agent_are_combined() -> None:
    """RFC 9309 2.2.1: two groups naming the same crawler are one group."""
    rules = (
        "user-agent: ExampleBot\ndisallow: /foo\ndisallow: /bar\n\n"
        "user-agent: ExampleBot\ndisallow: /baz\n"
    )
    for path in ("/foo", "/bar", "/baz"):
        assert not allowed(rules, "ExampleBot", path)
    assert allowed(rules, "ExampleBot", "/qux")


def test_star_groups_are_combined_too() -> None:
    """Two * groups combine like any other."""
    rules = "User-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b\n"
    assert not allowed(rules, "Cernis", "/a")
    assert not allowed(rules, "Cernis", "/b")


@pytest.mark.parametrize(
    "line", ["User-agent: cernis", "USER-AGENT: CERNIS", "user-agent: Cernis/1.0"]
)
def test_the_product_token_matches_case_insensitively(line: str) -> None:
    """RFC 9309 2.2.1: case-insensitive matching on the product token."""
    assert not allowed(f"{line}\nDisallow: /\n", "Cernis", "/post")


@pytest.mark.parametrize("agent", ["e", "Cern", "CernisBot", "notcernis"])
def test_another_product_token_is_not_ours(agent: str) -> None:
    """Only the whole product token matches: no substrings (urllib.robotparser got this wrong)."""
    rules = f"User-agent: {agent}\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert allowed(rules, "Cernis", "/post")


def test_our_group_replaces_the_star_group() -> None:
    """A group for Cernis is used instead of *, not as well as it."""
    rules = "User-agent: *\nDisallow: /private\n\nUser-agent: Cernis\nDisallow: /drafts\n"
    assert allowed(rules, "Cernis", "/private")
    assert not allowed(rules, "Cernis", "/drafts")


def test_no_matching_group_and_no_star_group_allows_everything() -> None:
    """RFC 9309 2.2.1: with no group that applies, no rules apply."""
    assert allowed("User-agent: OtherBot\nDisallow: /\n", "Cernis", "/post")


def test_rules_before_any_user_agent_are_ignored() -> None:
    """A rule belongs to a group; one with no group above it applies to nobody."""
    assert allowed("Disallow: /\nUser-agent: *\nAllow: /x\n", "Cernis", "/post")


def test_an_empty_robots_txt_allows_everything() -> None:
    """No groups, no rules."""
    assert allowed("", "Cernis", "/post")


def test_robots_txt_itself_is_always_allowed() -> None:
    """RFC 9309 2.2.2: the /robots.txt URI is implicitly allowed."""
    assert allowed("User-agent: *\nDisallow: /\n", "Cernis", "/robots.txt")


# Lines and records


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_every_rfc_line_ending_is_accepted(newline: str) -> None:
    """RFC 9309 2.2: lines end in LF, CR, or CRLF."""
    text = newline.join(["User-agent: *", "Disallow: /post", ""])
    assert not allowed(text, "Cernis", "/post")


def test_comments_and_whitespace_are_ignored() -> None:
    """A # starts a comment; whitespace around keys and values does not count."""
    text = "# header\n  User-agent :  *   # everyone\n Disallow:   /post  # not this\n"
    assert not allowed(text, "Cernis", "/post")
    assert allowed(text, "Cernis", "/other")


def test_unknown_records_and_malformed_lines_are_ignored() -> None:
    """Sitemap, Crawl-delay, and lines without a colon do not end or break a group."""
    text = "User-agent: *\nCrawl-delay: 10\nnonsense\nSitemap: https://x/s.xml\nDisallow: /post\n"
    assert not allowed(text, "Cernis", "/post")


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_disallow_is_no_rule(value: str) -> None:
    """An empty Disallow disallows nothing."""
    assert allowed(f"User-agent: *\nDisallow:{value}\n", "Cernis", "/post")


def test_a_pattern_that_is_not_a_path_is_ignored() -> None:
    """A pattern must start with / or * (RFC 9309 2.2 ABNF)."""
    assert allowed("User-agent: *\nDisallow: post\n", "Cernis", "/post")


# Special characters (RFC 9309 section 2.2.3)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("/this/*/exactly", "/this/is/exactly", True),
        ("/this/*/exactly", "/this/is/not/exactly", True),
        ("/this/*/exactly", "/this/exactly", False),
        ("/this/path/exactly$", "/this/path/exactly", True),
        ("/this/path/exactly$", "/this/path/exactly/not", False),
        ("/this/path/exactly$", "/this/path/exactly?q", False),
        ("*.pdf$", "/docs/paper.pdf", True),
        ("*.pdf$", "/docs/paper.pdf.html", False),
        ("/*", "/", True),
        ("/a*b*c", "/aXbYc", True),
        ("/a*b*c", "/aXcYb", False),
        ("/a$b", "/a$b", True),
        ("/a$b", "/a", False),
    ],
)
def test_wildcards_and_end_anchors(pattern: str, path: str, expected: bool) -> None:
    """``*`` matches any run of characters; ``$`` only ends a pattern when it is last."""
    assert allowed(f"User-agent: *\nDisallow: {pattern}\n", "Cernis", path) is not expected


@pytest.mark.parametrize(
    ("pattern", "path"),
    [
        ("/foo/bar?baz=quz", "/foo/bar?baz=quz"),
        ("/foo/bar/\u30c4", "/foo/bar/%E3%83%84"),
        ("/foo/bar/%E3%83%84", "/foo/bar/%E3%83%84"),
        ("/foo/bar/%e3%83%84", "/foo/bar/%E3%83%84"),
        ("/foo/bar/%62%61%7A", "/foo/bar/baz"),
        ("/foo/bar/baz", "/foo/bar/%62%61%7A"),
        ("/path/file-with-a-%2A.html", "/path/file-with-a-*.html"),
        ("/path/foo-%24", "/path/foo-$"),
    ],
)
def test_percent_encoding_is_normalized(pattern: str, path: str) -> None:
    """RFC 9309 2.2.2 and 2.2.3: patterns and paths compare after the same normalization."""
    assert not allowed(f"User-agent: *\nDisallow: {pattern}\n", "Cernis", path)


def test_an_encoded_star_is_a_literal_star() -> None:
    """``%2A`` in a pattern matches a literal ``*`` only, never any text."""
    rules = "User-agent: *\nDisallow: /a%2Ab\n"
    assert allowed(rules, "Cernis", "/aXb")
    assert not allowed(rules, "Cernis", "/a*b")


def test_an_encoded_slash_stays_encoded() -> None:
    """Reserved characters keep their encoding, so ``%2F`` is not ``/``."""
    rules = "User-agent: *\nDisallow: /a/b\n"
    assert allowed(rules, "Cernis", "/a%2Fb")


def test_matching_is_case_sensitive_in_the_path() -> None:
    """Paths compare case-sensitively."""
    assert allowed("User-agent: *\nDisallow: /Post\n", "Cernis", "/post")


def test_many_wildcards_do_not_take_exponential_time() -> None:
    """A hostile pattern with many ``*`` is matched in linear passes, not by backtracking."""
    rules = "User-agent: *\nDisallow: /" + "*a" * 200 + "b\n"
    assert allowed(rules, "Cernis", "/" + "a" * 5000)


# Evidence


def test_the_deciding_rule_is_reported() -> None:
    """The verdict names the rule that decided, as written, for the receipt's evidence."""
    rules = RobotsRules.parse("User-agent: *\nDisallow: /private/  # keep out\nAllow: /\n")

    verdict = rules.check("Cernis", "/private/x")

    assert not verdict.allowed
    assert verdict.rule == "Disallow: /private/"
    assert rules.check("Cernis", "/robots.txt").rule is None
    assert rules.check("Cernis", "/public").rule == "Allow: /"
