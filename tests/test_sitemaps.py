"""Tests for sitemap reading (cernis.sitemaps) and epi.sitemap.listed."""

import gzip
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fetch_support import Site, make_fetcher, redirect, respond
from parse_support import DEV_URL, WORDPRESS_URL, fixture

from cernis.audit import AuditLimits, Target, audit
from cernis.checks.sitemap_listed import section_of
from cernis.model import Actor, Finding, ReasonCode, Run, Status
from cernis.parse import SitePrefix, SiteType
from cernis.sitemaps import parse_sitemap

HTML = {"content-type": "text/html; charset=utf-8"}
XML = {"content-type": "application/xml"}
ORIGIN = "https://blog.example.com"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*locs: str) -> bytes:
    """Write a <urlset> sitemap.

    :param *locs: The page URLs.
    :return: The XML.
    """
    rows = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {NS}>{rows}</urlset>'.encode()


def index(*locs: str) -> bytes:
    """Write a <sitemapindex>.

    :param *locs: The child sitemap URLs.
    :return: The XML.
    """
    rows = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0"?><sitemapindex {NS}>{rows}</sitemapindex>'.encode()


def clock() -> Callable[[], datetime]:
    """Return a clock that reads one second later each time.

    :return: The clock.
    """
    moments = iter(datetime(2026, 11, 2, 12, 0, n % 60, tzinfo=UTC) for n in range(60))
    return lambda: next(moments)


def blog(robots: bytes = b"") -> Site:
    """Script the WordPress page, with an optional robots.txt.

    :param robots: The robots.txt body; unrouted (404) if empty.
    :return: The scripted web.
    """
    site = Site()
    site.add(WORDPRESS_URL, respond(200, fixture("wordpress-entry"), HTML))
    if robots:
        site.add(f"{ORIGIN}/robots.txt", respond(200, robots))
    return site


def run(
    site: Site,
    tmp_path: Path,
    *urls: str,
    limits: AuditLimits | None = None,
    prefixes: tuple[SitePrefix, ...] = (),
) -> Run:
    """Audit pages declared WordPress.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :param *urls: The pages; the WordPress page if none.
    :param limits: The limits.
    :param prefixes: Prefix rules.
    :return: The run.
    """
    targets = [Target(url=url, site=SiteType.WORDPRESS) for url in (urls or (WORDPRESS_URL,))]
    fetcher = make_fetcher(site, tmp_path, min_interval=0)
    return audit(targets, fetcher, now=clock(), limits=limits, prefixes=prefixes)


def listed(result: Run, subject: str = WORDPRESS_URL) -> list[Finding]:
    """Select a page's epi.sitemap.listed findings and recommendations.

    :param result: The run.
    :param subject: The page.
    :return: The findings.
    """
    return [
        f
        for f in result.findings
        if f.check_id == "epi.sitemap.listed" and f.subject_url == subject
    ]


# parse_sitemap


def test_a_urlset_and_an_index_are_read() -> None:
    """Namespaced or not, <loc> values are read in order."""
    assert parse_sitemap(urlset("https://a/1", "https://a/2"), limit=10_000).locs == (
        "https://a/1",
        "https://a/2",
    )
    read = parse_sitemap(index("https://a/s1.xml"), limit=10_000)
    assert (read.kind, read.locs) == ("sitemapindex", ("https://a/s1.xml",))


def test_gzip_is_read_within_the_limit() -> None:
    """A .xml.gz body is decompressed, and one that expands too far is refused."""
    body = gzip.compress(urlset("https://a/1"))
    assert parse_sitemap(body, limit=10_000).locs == ("https://a/1",)
    bomb = gzip.compress(b" " * 100_000)
    assert "expands past" in (parse_sitemap(bomb, limit=1_000).problem or "")


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (b'<!DOCTYPE x [<!ENTITY a "aaaa">]><urlset>&a;</urlset>', "DOCTYPE"),
        (b"<urlset><url>", "not well-formed"),
        (b"<html><body>Not found</body></html>", "root element is <html>"),
        (b"\x1f\x8bnot gzip at all", "gzip"),
    ],
)
def test_what_is_not_a_sitemap_is_named(body: bytes, problem: str) -> None:
    """Entities are never expanded: a DOCTYPE is refused before parsing."""
    assert problem in (parse_sitemap(body, limit=10_000).problem or "")


def test_a_section_is_the_prefix_or_the_parent_path() -> None:
    """The defect rule compares the page with pages in its own section."""
    rule = SitePrefix(prefix="https://blog.example.com/", site=SiteType.WORDPRESS)
    assert section_of(WORDPRESS_URL, ()) == "https://blog.example.com/2026/10/"
    assert section_of(WORDPRESS_URL, (rule,)) == "https://blog.example.com/"


# epi.sitemap.listed


def test_robots_sitemap_lines_come_first_and_indexes_are_followed(tmp_path: Path) -> None:
    """robots.txt names an index, which names the urlset that lists the page."""
    site = blog(b"User-agent: *\nDisallow:\nSitemap: https://blog.example.com/wp-sitemap.xml\n")
    site.add(
        f"{ORIGIN}/wp-sitemap.xml", respond(200, index(f"{ORIGIN}/wp-sitemap-posts-1.xml"), XML)
    )
    site.add(f"{ORIGIN}/wp-sitemap-posts-1.xml", respond(200, urlset(WORDPRESS_URL), XML))

    (found,) = listed(run(site, tmp_path))

    assert found.summary == f"The sitemap {ORIGIN}/wp-sitemap-posts-1.xml lists the page."
    assert (found.defect, found.actor) == (False, Actor.AUTHOR)
    assert f"{ORIGIN}/sitemap.xml" not in site.urls()


def test_a_gzipped_sitemap_at_the_fallback_location_lists_the_page(tmp_path: Path) -> None:
    """With no Sitemap line, /sitemap.xml is tried; equivalence names the normalization."""
    site = blog()
    body = gzip.compress(urlset(WORDPRESS_URL.rstrip("/")))
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, body, {"content-type": "application/gzip"}))

    (found,) = listed(run(site, tmp_path))

    assert found.summary.endswith("which is equivalent (trailing slash).")


def test_a_page_missing_from_a_sitemap_listing_its_neighbors_is_a_defect(tmp_path: Path) -> None:
    """Other posts in the same section are listed; this one is not."""
    site = blog()
    site.add(
        f"{ORIGIN}/wp-sitemap.xml",
        respond(200, urlset(f"{ORIGIN}/2026/10/another-post/", f"{ORIGIN}/2026/10/a-third/"), XML),
    )

    found, advice = listed(run(site, tmp_path))

    assert found.defect
    assert found.summary == (
        "The sitemap does not list the page, though it lists 2 other pages under "
        f"{ORIGIN}/2026/10/ (read: {ORIGIN}/wp-sitemap.xml)."
    )
    assert advice.status is Status.RECOMMENDATION
    assert advice.summary == f"Add {WORDPRESS_URL} to the site's sitemap."
    assert "sitemaps.org" in (advice.rationale or "")


def test_a_sitemap_with_nothing_in_the_section_is_a_fact(tmp_path: Path) -> None:
    """A sitemap of other sections says nothing about this one."""
    site = blog()
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, urlset(f"{ORIGIN}/about/"), XML))

    (found,) = listed(run(site, tmp_path))

    assert not found.defect
    assert "lists no other page under" in found.summary


def test_no_sitemap_is_a_fact_naming_every_place_searched(tmp_path: Path) -> None:
    """Absence is evidence."""
    (found,) = listed(run(blog(), tmp_path))

    assert found.summary == (
        f"No sitemap was found: Cernis looked in robots.txt and at {ORIGIN}/sitemap.xml "
        f"(answered 404); {ORIGIN}/wp-sitemap.xml (answered 404)."
    )
    assert not found.defect


def test_a_sitemap_that_fails_is_not_determinable(tmp_path: Path) -> None:
    """A 500 is not the absence of a sitemap."""
    site = blog()
    site.add(f"{ORIGIN}/sitemap.xml", respond(500))

    (found,) = listed(run(site, tmp_path))

    assert (found.status, found.reason_code) == (Status.NOT_DETERMINABLE, ReasonCode.FETCH_FAILED)


def test_an_unread_child_makes_an_absence_not_determinable(tmp_path: Path) -> None:
    """The page could be in the child that failed."""
    site = blog()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(200, index(f"{ORIGIN}/s1.xml", f"{ORIGIN}/s2.xml"), XML),
    )
    site.add(f"{ORIGIN}/s1.xml", respond(200, urlset(f"{ORIGIN}/2026/10/other/"), XML))
    site.add(f"{ORIGIN}/s2.xml", respond(503))

    (found,) = listed(run(site, tmp_path))

    assert found.status is Status.NOT_DETERMINABLE
    assert f"{ORIGIN}/s2.xml could not be read: the server answered 503" in found.summary


def test_the_document_limit_is_never_a_silent_skip(tmp_path: Path) -> None:
    """Children past the limit leave the answer open, with LIMIT_REACHED."""
    site = blog()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(200, index(*(f"{ORIGIN}/s{n}.xml" for n in range(5))), XML),
    )
    for n in range(5):
        site.add(f"{ORIGIN}/s{n}.xml", respond(200, urlset(f"{ORIGIN}/2026/10/p{n}/"), XML))

    (found,) = listed(run(site, tmp_path, limits=AuditLimits(sitemap_documents=3)))

    assert found.reason_code is ReasonCode.LIMIT_REACHED
    assert f"{ORIGIN}/s4.xml" not in site.urls()


def test_sitemaps_are_read_once_per_site(tmp_path: Path) -> None:
    """Two pages on one site share one read."""
    other = f"{ORIGIN}/2026/10/another-post/"
    site = blog()
    site.add(other, respond(200, fixture("wordpress-entry"), HTML))
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, urlset(WORDPRESS_URL, other), XML))

    result = run(site, tmp_path, WORDPRESS_URL, other)

    assert site.urls().count(f"{ORIGIN}/sitemap.xml") == 1
    assert len(listed(result)) == len(listed(result, other)) == 1


def test_dev_pages_are_skipped(tmp_path: Path) -> None:
    """DEV's sitemaps are the platform's."""
    site = Site()
    site.add(DEV_URL, respond(200, fixture("dev-article"), HTML))

    result = audit([Target(url=DEV_URL)], make_fetcher(site, tmp_path, min_interval=0), now=clock())

    assert not [f for f in result.findings if f.check_id == "epi.sitemap.listed"]
    assert "https://dev.to/sitemap.xml" not in site.urls()


def test_a_wordpress_install_under_a_prefix_is_searched_at_its_own_root(tmp_path: Path) -> None:
    """Found in the Session 5b real run: a root sitemap of another site must not hide the blog's."""
    post = f"{ORIGIN}/blog/2026/10/a-post/"
    site = Site()
    site.add(post, respond(200, fixture("wordpress-entry"), HTML))
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, urlset(f"{ORIGIN}/about/"), XML))
    site.add(f"{ORIGIN}/blog/wp-sitemap.xml", respond(200, urlset(post), XML))
    rule = SitePrefix(prefix=f"{ORIGIN}/blog/", site=SiteType.WORDPRESS)

    (found,) = listed(run(site, tmp_path, post, prefixes=(rule,)), post)

    assert found.summary == f"The sitemap {ORIGIN}/blog/wp-sitemap.xml lists the page."
    assert [u for u in site.urls() if "sitemap" in u] == [
        f"{ORIGIN}/blog/sitemap.xml",
        f"{ORIGIN}/blog/wp-sitemap.xml",
    ]


# Session 5b audit (aud_gwCSZD5Y6S) regressions


def test_a_utf16_doctype_is_refused_by_the_parser() -> None:
    """V3 f1: a byte search misses a UTF-16 DOCTYPE; the parser does not."""
    body = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE urlset [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f"<urlset {NS}><url><loc>https://a/&b;</loc></url></urlset>"
    ).encode("utf-16")

    read = parse_sitemap(body, limit=100_000)

    assert (read.kind, read.locs) == (None, ())
    assert "DOCTYPE" in (read.problem or "")


def test_every_gzip_member_is_read() -> None:
    """V3 f9: a multi-member gzip is one document, all of it read."""
    body = gzip.compress(
        f"<urlset {NS}><url><loc>https://a/1</loc></url>".encode()
    ) + gzip.compress(b"<url><loc>https://a/2</loc></url></urlset>")

    assert parse_sitemap(body, limit=10_000).locs == ("https://a/1", "https://a/2")


def test_the_entry_cap_is_a_limit_reached() -> None:
    """V1 f1, V3 f11: a document's entries are capped, and the cap is recorded."""
    read = parse_sitemap(
        urlset("https://a/1", "https://a/2", "https://a/3"), limit=10_000, max_entries=2
    )

    assert (read.locs, read.capped) == (("https://a/1", "https://a/2"), True)


def test_cross_host_index_children_are_not_followed(tmp_path: Path) -> None:
    """V2 f9, V3 f13: an index lists its own site's sitemaps."""
    site = blog()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(200, index("https://elsewhere.example/s.xml", f"{ORIGIN}/s1.xml"), XML),
    )
    site.add(f"{ORIGIN}/s1.xml", respond(200, urlset(WORDPRESS_URL), XML))

    (found,) = listed(run(site, tmp_path))

    assert not found.defect
    assert "https://elsewhere.example/s.xml" not in site.urls()


def test_a_child_the_fetcher_refuses_leaves_the_answer_open(tmp_path: Path) -> None:
    """V1 f6, V3 f3, V4 f7: a refused child is an unread document, never a silent skip."""
    site = blog()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(200, index(f"https://user:pw@{ORIGIN[8:]}/s2.xml", f"{ORIGIN}/s1.xml"), XML),
    )
    site.add(f"{ORIGIN}/s1.xml", respond(200, urlset(f"{ORIGIN}/2026/10/other/"), XML))

    (found,) = listed(run(site, tmp_path))

    assert (found.status, found.defect) == (Status.NOT_DETERMINABLE, False)


def test_malformed_locs_are_counted_not_fatal(tmp_path: Path) -> None:
    """V3 f2, V4 f4: one bad <loc> never ends the run."""
    site = blog()
    site.add(
        f"{ORIGIN}/sitemap.xml",
        respond(200, urlset("http://[::1", "http://a b/", WORDPRESS_URL), XML),
    )

    (found,) = listed(run(site, tmp_path))

    assert found.summary == f"The sitemap {ORIGIN}/sitemap.xml lists the page."


def test_only_404_and_410_mean_no_sitemap(tmp_path: Path) -> None:
    """V4 f8: a 400 does not establish absence."""
    site = blog()
    site.add(f"{ORIGIN}/sitemap.xml", respond(400))

    (found,) = listed(run(site, tmp_path))

    assert found.status is Status.NOT_DETERMINABLE


@pytest.mark.parametrize(
    ("old", "new", "why"),
    [
        (
            f"href='{WORDPRESS_URL}'",
            "href='https://dev.to/example-author/a-synthetic-post-1a2b'",
            "its canonical URL names another page",
        ),
        (
            "content='index, follow, max-image-preview:large'",
            "content='noindex, follow'",
            "it declares noindex",
        ),
    ],
)
def test_a_page_expected_to_be_left_out_is_a_fact(
    tmp_path: Path, old: str, new: str, why: str
) -> None:
    """V3 f4: a copy, or a noindex page, is rightly missing from the sitemap."""
    page = fixture("wordpress-entry").decode().replace(old, new, 1).encode()
    site = Site()
    site.add(WORDPRESS_URL, respond(200, page, HTML))
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, urlset(f"{ORIGIN}/2026/10/other/"), XML))

    (found,) = listed(run(site, tmp_path))

    assert not found.defect
    assert f"which is expected: {why}" in found.summary


def test_a_news_sitemap_omission_is_not_determinable(tmp_path: Path) -> None:
    """V3 f4: a news sitemap lists only recent articles."""
    news = (
        f'<urlset {NS} xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
        f"<url><loc>{ORIGIN}/2026/10/new/</loc><news:news><news:title>x</news:title></news:news>"
        "</url></urlset>"
    ).encode()
    site = blog()
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, news, XML))

    (found,) = listed(run(site, tmp_path))

    assert (found.status, found.reason_code) == (Status.NOT_DETERMINABLE, ReasonCode.AMBIGUOUS)


def test_a_loc_the_page_redirected_through_is_the_page(tmp_path: Path) -> None:
    """V3 f5, V4 f3: the shared comparison counts the page's own redirect chain."""
    old = f"{ORIGIN}/?p=42"
    site = blog()
    site.add(old, redirect(WORDPRESS_URL))
    site.add(f"{ORIGIN}/sitemap.xml", respond(200, urlset(old, f"{ORIGIN}/2026/10/other/"), XML))

    (found,) = listed(run(site, tmp_path, old), old)

    assert not found.defect
    assert found.summary.startswith(f"The sitemap {ORIGIN}/sitemap.xml lists the page")
