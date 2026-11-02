"""Tests for site-level findings (epi.og.image.shared), the run summary, and D4."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fetch_support import Site, make_fetcher, respond
from parse_support import WORDPRESS_URL, fixture

from cernis.audit import Target, audit
from cernis.checks.sitemap_listed import section_of
from cernis.model import Actor, Run, Status
from cernis.parse import SitePrefix, SiteType
from cernis.report import report_json, report_markdown

HTML = {"content-type": "text/html; charset=utf-8"}
ORIGIN = "https://blog.example.com"
IMAGE = f"{ORIGIN}/wp-content/uploads/2026/10/cover.png"
SECOND = f"{ORIGIN}/2026/10/another-post/"
THIRD = f"{ORIGIN}/2026/10/a-third-post/"


def clock() -> Callable[[], datetime]:
    """Return a clock that reads one second later each time.

    :return: The clock.
    """
    moments = iter(datetime(2026, 11, 2, 12, 0, n % 60, tzinfo=UTC) for n in range(600))
    return lambda: next(moments)


def page(image: str) -> bytes:
    """Write the WordPress fixture with a given og:image.

    :param image: The og:image URL.
    :return: The HTML.
    """
    return fixture("wordpress-entry").replace(IMAGE.encode(), image.encode())


def run(site: Site, tmp_path: Path, *urls: str) -> Run:
    """Audit WordPress pages.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :param *urls: The pages.
    :return: The run.
    """
    targets = [Target(url=url, site=SiteType.WORDPRESS) for url in urls]
    return audit(targets, make_fetcher(site, tmp_path, min_interval=0), now=clock())


def three_pages(third_image: str = IMAGE) -> Site:
    """Script three posts; the first two share the default og:image.

    :param third_image: The third post's og:image.
    :return: The scripted web.
    """
    site = Site()
    site.add(WORDPRESS_URL, respond(200, page(IMAGE), HTML))
    site.add(SECOND, respond(200, page(IMAGE), HTML))
    site.add(THIRD, respond(200, page(third_image), HTML))
    return site


def test_articles_sharing_an_og_image_get_one_site_fact(tmp_path: Path) -> None:
    """Two or more articles on one site with one image: one fact listing them, never a defect."""
    result = run(
        three_pages(f"{ORIGIN}/wp-content/uploads/own.png"), tmp_path, WORDPRESS_URL, SECOND, THIRD
    )

    (shared,) = [f for f in result.findings if f.check_id == "epi.og.image.shared"]
    assert (shared.status, shared.defect, shared.actor) == (Status.OBSERVED, False, Actor.AUTHOR)
    assert (shared.subject_url, shared.target) == (WORDPRESS_URL, IMAGE)
    assert shared.summary == (
        f"2 audited articles on {ORIGIN}/ share the og:image {IMAGE}: {WORDPRESS_URL}, {SECOND}."
    )
    assert [e.location for e in shared.evidence] == [
        f'{WORDPRESS_URL} meta[property="og:image"]',
        f'{SECOND} meta[property="og:image"]',
    ]


def test_distinct_images_give_no_site_fact(tmp_path: Path) -> None:
    """Nothing shared, nothing reported."""
    site = Site()
    site.add(WORDPRESS_URL, respond(200, page(IMAGE), HTML))
    site.add(SECOND, respond(200, page(f"{ORIGIN}/other.png"), HTML))

    result = run(site, tmp_path, WORDPRESS_URL, SECOND)

    assert not [f for f in result.findings if f.check_id == "epi.og.image.shared"]


def test_the_report_puts_site_facts_in_their_own_section(tmp_path: Path) -> None:
    """A Site section holds them; the page sections do not repeat them."""
    result = run(three_pages(), tmp_path, WORDPRESS_URL, SECOND, THIRD)

    text = report_markdown(result)
    site = text.split("## Site (1)", 1)[1].split("## Observed", 1)[0]
    assert "epi.og.image.shared" in site
    assert text.count("epi.og.image.shared ·") == 1
    payload = json.loads(report_json(result))
    assert payload["counts"]["site"] == 1


def test_the_summary_counts_author_defects_per_article(tmp_path: Path) -> None:
    """Plain counts: each article's AUTHOR defects, and how many articles have any."""
    site = three_pages()
    # The third post links to a page that is gone: one AUTHOR defect.
    site.add(
        THIRD,
        respond(
            200,
            page(IMAGE).replace(b"https://www.example.org/paper", b"https://www.example.org/gone"),
            HTML,
        ),
    )
    site.add("https://www.example.org/paper", respond(200, b"x", HTML))
    site.add(f"{ORIGIN}/2026/09/an-earlier-post/", respond(200, b"x", HTML))
    site.add(f"{ORIGIN}/2026/10/a-synthetic-post/", respond(200, b"x", HTML))
    site.add(IMAGE, respond(200, b"PNG", {"content-type": "image/png"}))

    result = run(site, tmp_path, WORDPRESS_URL, SECOND, THIRD)

    payload = json.loads(report_json(result))["summary"]
    counts = {row["subject"]: row["count"] for row in payload["author_defects"]}
    assert counts[THIRD] >= 1
    expected = {
        subject: sum(
            1
            for f in result.findings
            if f.subject_url == subject and f.defect and f.actor is Actor.AUTHOR
        )
        for subject in result.subjects
    }
    assert counts == expected
    assert payload["articles"] == 3
    assert payload["articles_with_author_defects"] == sum(1 for c in counts.values() if c)
    text = report_markdown(result)
    assert f"- {THIRD}: {counts[THIRD]}" in text
    assert (
        f"Articles with at least one AUTHOR defect: {payload['articles_with_author_defects']} of 3."
        in text
    )


def test_a_whole_origin_prefix_makes_the_whole_site_one_section() -> None:
    """Audit finding D4, decided in Session 5c: the prefix is the section."""
    rule = SitePrefix(prefix=f"{ORIGIN}/", site=SiteType.WORDPRESS)

    section = section_of(WORDPRESS_URL, (rule,))

    assert section == f"{ORIGIN}/"
    assert section_of(WORDPRESS_URL, ()) == f"{ORIGIN}/2026/10/"
