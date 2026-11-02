"""Tests for epi.robots.access, peri.robots.directives, and the crawler list."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fetch_support import Reply, Site, make_fetcher, respond
from parse_support import DEV_URL, WORDPRESS_URL, fixture

from cernis.audit import Target, audit
from cernis.checks.robots_access import check_version
from cernis.crawlers import CrawlerListError, crawler_list, parse_crawler_list
from cernis.fetch.rfc9309 import RobotsRules
from cernis.model import Actor, Finding, ReasonCode, Run, Status
from cernis.parse import SiteType

HTML = {"content-type": "text/html; charset=utf-8"}
WP_ROBOTS = "https://blog.example.com/robots.txt"
DEV_ROBOTS = "https://dev.to/robots.txt"

AI_GROUPS = b"""# Synthetic robots.txt with AI-crawler groups.
User-agent: *
Disallow: /wp-admin/

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: ClaudeBot
Allow: /2026/
Disallow: /

Sitemap: https://blog.example.com/wp-sitemap.xml
"""


def clock() -> Callable[[], datetime]:
    """Return a clock that reads one second later each time.

    :return: The clock.
    """
    moments = iter(datetime(2026, 11, 2, 12, 0, n, tzinfo=UTC) for n in range(60))
    return lambda: next(moments)


def run(site: Site, tmp_path: Path, url: str = WORDPRESS_URL, kind: SiteType | None = None) -> Run:
    """Audit one page on a scripted web.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :param url: The page.
    :param kind: Its declared site type.
    :return: The run.
    """
    fetcher = make_fetcher(site, tmp_path, min_interval=0)
    return audit([Target(url=url, site=kind)], fetcher, now=clock())


def access(run_: Run) -> dict[str, Finding]:
    """Index a run's epi.robots.access findings by crawler name.

    :param run_: The run.
    :return: The findings by target.
    """
    return {f.target: f for f in run_.findings if f.check_id == "epi.robots.access"}


def wordpress(robots: Reply) -> Site:
    """Script the WordPress page with a given robots.txt reply.

    :param robots: The robots.txt reply.
    :return: The scripted web.
    """
    site = Site()
    site.add(WP_ROBOTS, robots)
    site.add(WORDPRESS_URL, respond(200, fixture("wordpress-entry"), HTML))
    return site


# The crawler list


def test_the_shipped_list_has_the_confirmed_tokens_and_not_bytespider() -> None:
    """Thirteen tokens, each with an operator and a source; Bytespider could not be confirmed."""
    tokens = [c.token for c in crawler_list().crawlers]
    assert tokens == [
        "GPTBot",
        "ChatGPT-User",
        "OAI-SearchBot",
        "ClaudeBot",
        "Claude-User",
        "Claude-SearchBot",
        "Google-Extended",
        "PerplexityBot",
        "Perplexity-User",
        "CCBot",
        "Applebot-Extended",
        "Amazonbot",
        "Meta-ExternalAgent",
    ]
    assert crawler_list().version == 1
    assert all(c.source.startswith("https://") and c.operator for c in crawler_list().crawlers)


ENTRY = 'token = "{token}"\noperator = "X"\npurpose = "y"\nsource = "{source}"\n'


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("version = 0\n[[crawler]]\n" + ENTRY.format(token="A", source="https://a"), "version"),
        ("version = 1\n", "at least one"),
        ("version = 1\n[[crawler]]\n" + ENTRY.format(token="A b", source="https://a"), "product"),
        ("version = 1\n[[crawler]]\n" + ENTRY.format(token="A", source="ftp://a"), "source"),
        (
            "version = 1\n[[crawler]]\n"
            + ENTRY.format(token="Bot", source="https://a")
            + "[[crawler]]\n"
            + ENTRY.format(token="BOT", source="https://a"),
            "repeats",
        ),
        ('version = 1\n[[crawler]]\ntoken = "A"\n', "exactly"),
    ],
)
def test_a_malformed_list_is_rejected(text: str, message: str) -> None:
    """The list is validated, so a bad edit fails the test suite, not a run."""
    with pytest.raises(CrawlerListError, match=message):
        parse_crawler_list(text)


def test_the_check_version_names_the_list_and_matcher_versions() -> None:
    """A change to either is a CHECKER change."""
    assert check_version() == "1+c1+m1"


# The matcher additions


def test_sitemap_lines_are_collected_and_groups_are_named() -> None:
    """Sitemap lines never join a group; names() tells a named group from the * fallback."""
    rules = RobotsRules.parse(AI_GROUPS.decode())

    assert rules.sitemaps == ("https://blog.example.com/wp-sitemap.xml",)
    assert rules.names("gptbot")
    assert rules.names("CCBot")
    assert rules.names("*")
    assert not rules.names("PerplexityBot")


# epi.robots.access


def test_named_groups_and_the_star_fallback_are_reported(tmp_path: Path) -> None:
    """GPTBot and CCBot are named and disallowed; ClaudeBot is allowed /2026/; others fall back."""
    found = access(run(wordpress(respond(200, AI_GROUPS)), tmp_path, kind=SiteType.WORDPRESS))

    assert len(found) == 14
    assert found["*"].summary == (
        "robots.txt allows general crawlers (*) to fetch this page: a group names *; "
        "no rule matches."
    )
    assert found["GPTBot"].summary == (
        "robots.txt disallows GPTBot (OpenAI) to fetch this page: a group names GPTBot; "
        "the rule 'Disallow: /' decides."
    )
    assert found["ClaudeBot"].summary.startswith("robots.txt allows ClaudeBot (Anthropic)")
    assert "'Allow: /2026/'" in found["ClaudeBot"].summary
    assert found["PerplexityBot"].summary == (
        "robots.txt allows PerplexityBot (Perplexity) to fetch this page: no group names "
        "PerplexityBot, so the * group applies; no rule matches."
    )
    assert {f.defect for f in found.values()} == {False}
    assert {f.actor for f in found.values()} == {Actor.AUTHOR}
    assert {f.check_version for f in found.values()} == {"1+c1+m1"}


def test_the_robots_receipt_is_reused(tmp_path: Path) -> None:
    """Fourteen answers from the one robots.txt fetch Cernis's own access rested on."""
    site = wordpress(respond(200, AI_GROUPS))

    result = run(site, tmp_path, kind=SiteType.WORDPRESS)

    assert site.urls().count(WP_ROBOTS) == 1
    robots_receipt = next(r for r in result.receipts if r.requested_url == WP_ROBOTS)
    assert {f.evidence[0].receipt_id for f in access(result).values()} == {robots_receipt.id}


def test_on_dev_the_robots_txt_is_the_platforms(tmp_path: Path) -> None:
    """dev.to's robots.txt is DEV's to set."""
    site = Site()
    site.add(DEV_ROBOTS, respond(200, b"User-agent: GPTBot\nDisallow: /\n"))
    site.add(DEV_URL, respond(200, fixture("dev-article"), HTML))

    found = access(run(site, tmp_path, url=DEV_URL))

    assert {f.actor for f in found.values()} == {Actor.PLATFORM}
    assert "disallows GPTBot" in found["GPTBot"].summary
    assert found["*"].summary.endswith("there is no * group; no rule matches.")


def test_a_missing_robots_txt_allows_every_crawler(tmp_path: Path) -> None:
    """RFC 9309: a 4xx robots.txt means no restrictions."""
    found = access(run(wordpress(respond(404)), tmp_path, kind=SiteType.WORDPRESS))

    assert found["ClaudeBot"].summary == (
        "robots.txt answered 404, so under RFC 9309 it allows ClaudeBot (Anthropic) to fetch "
        "this page."
    )


@pytest.mark.parametrize(
    ("reply", "code"),
    [(respond(500), ReasonCode.FETCH_FAILED), (respond(429), ReasonCode.RATE_LIMITED)],
)
def test_an_unreachable_robots_txt_is_not_determinable(
    tmp_path: Path, reply: Reply, code: ReasonCode
) -> None:
    """robots.txt said nothing, so what it says for each crawler cannot be told."""
    found = access(run(wordpress(reply), tmp_path, kind=SiteType.WORDPRESS))

    assert {(f.status, f.reason_code) for f in found.values()} == {(Status.NOT_DETERMINABLE, code)}


def test_an_unread_page_still_gets_robots_access(tmp_path: Path) -> None:
    """A page Cernis may not fetch still has a robots.txt to report on."""
    site = wordpress(respond(200, b"User-agent: *\nDisallow: /\n"))

    found = access(run(site, tmp_path, kind=SiteType.WORDPRESS))

    assert "disallows general crawlers (*)" in found["*"].summary
    assert WORDPRESS_URL not in site.urls()


# peri.robots.directives


def directives(result: Run) -> Finding:
    """Return a run's one peri.robots.directives finding.

    :param result: The run.
    :return: The finding.
    """
    (found,) = [f for f in result.findings if f.check_id == "peri.robots.directives"]
    return found


def test_robots_meta_and_header_are_facts_never_defects(tmp_path: Path) -> None:
    """A noindex may be what the author wants."""
    page = fixture("wordpress-entry").replace(
        b"<meta name='robots' content='index, follow, max-image-preview:large' />",
        b'<meta name="robots" content="noindex, nofollow"><meta name="GPTBot" content="noai">',
    )
    site = Site()
    site.add(WORDPRESS_URL, respond(200, page, {**HTML, "x-robots-tag": "noarchive"}))

    found = directives(run(site, tmp_path, kind=SiteType.WORDPRESS))

    assert found.summary == (
        "The page declares robots directives: robots meta tag 'noindex, nofollow'; "
        "GPTBot meta tag 'noai'; X-Robots-Tag header 'noarchive'."
    )
    assert (found.defect, found.actor) == (False, Actor.AUTHOR)
    assert [e.location for e in found.evidence] == [
        'head > meta[name="robots"] content',
        'head > meta[name="GPTBot"] content',
        "X-Robots-Tag header",
    ]


def test_no_directives_records_the_search(tmp_path: Path) -> None:
    """Absence is evidence: both places searched are named."""
    site = Site()
    site.add(DEV_URL, respond(200, fixture("dev-article"), HTML))

    found = directives(run(site, tmp_path, url=DEV_URL))

    assert found.actor is Actor.PLATFORM
    assert [e.searched_for is not None for e in found.evidence] == [True, True]
