"""Tests for epi.links.resolve: article-body links, limits, and outcomes."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fetch_support import FakeResolver, Reply, Site, make_fetcher, redirect, respond

from cernis.audit import AuditLimits, Target, audit
from cernis.checks.links import LinkLimits
from cernis.fetch.cache import Cache
from cernis.model import Actor, Finding, ReasonCode, Run, Status
from cernis.parse import SiteType

HTML = {"content-type": "text/html; charset=utf-8"}
PAGE = "https://blog.example.com/2026/11/links/"


def page(*hrefs: str) -> bytes:
    """Write a synthetic WordPress entry whose body holds the given links.

    Navigation and a footer link sit outside the body, so they are never checked.

    :param *hrefs: The body's ``href`` values, in order.
    :return: The HTML.
    """
    links = "".join(f'<p><a href="{href}">link</a></p>' for href in hrefs)
    return (
        '<!doctype html><html lang="en"><head><title>Links</title>'
        f'<link rel="canonical" href="{PAGE}"></head><body>'
        '<nav><a href="https://blog.example.com/about/">About</a></nav>'
        f'<article><div class="entry-content">{links}</div></article>'
        '<footer><a href="https://wordpress.org/">WordPress</a></footer>'
        "</body></html>"
    ).encode()


def clock() -> Callable[[], datetime]:
    """Return a clock that reads one second later each time.

    :return: The clock.
    """
    moments = iter(datetime(2026, 11, 2, 12, 0, n % 60, tzinfo=UTC) for n in range(600))
    return lambda: next(moments)


def run(
    site: Site,
    tmp_path: Path,
    *,
    limits: AuditLimits | None = None,
    site_type: SiteType | None = SiteType.WORDPRESS,
    resolver: FakeResolver | None = None,
) -> Run:
    """Audit the links page.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :param limits: The limits.
    :param site_type: The page's declared site type.
    :param resolver: The fake resolver.
    :return: The run.
    """
    fetcher = make_fetcher(site, tmp_path, resolver=resolver, min_interval=0)
    return audit([Target(url=PAGE, site=site_type)], fetcher, now=clock(), limits=limits)


def links(result: Run) -> dict[str, Finding]:
    """Index a run's epi.links.resolve findings (not recommendations) by target.

    :param result: The run.
    :return: The findings.
    """
    return {
        f.target: f
        for f in result.findings
        if f.check_id == "epi.links.resolve" and f.status is not Status.RECOMMENDATION
    }


def web(*hrefs: str) -> Site:
    """Script the links page.

    :param *hrefs: The body's links.
    :return: The scripted web.
    """
    site = Site()
    site.add(PAGE, respond(200, page(*hrefs), HTML))
    return site


def test_only_body_links_are_checked_and_each_once(tmp_path: Path) -> None:
    """Navigation and footer links are never fetched; a repeated link is fetched once."""
    site = web("https://www.example.org/a", "https://www.example.org/a#part", "/2026/10/older/")
    site.add("https://www.example.org/a", respond(200, b"x", HTML))
    site.add("https://blog.example.com/2026/10/older/", respond(200, b"x", HTML))

    found = links(run(site, tmp_path))

    assert set(found) == {"https://www.example.org/a", "https://blog.example.com/2026/10/older/"}
    assert found["https://www.example.org/a"].summary == (
        "The link https://www.example.org/a answers 200."
    )
    assert site.urls().count("https://www.example.org/a") == 1
    assert "https://blog.example.com/about/" not in site.urls()
    assert "https://wordpress.org/" not in site.urls()
    assert {f.actor for f in found.values()} == {Actor.AUTHOR}


def test_skipped_links_are_counted_never_dropped(tmp_path: Path) -> None:
    """mailto:, tel:, javascript:, and fragment-only links get one fact."""
    site = web("mailto:a@example.com", "tel:+15550100", "javascript:void(0)", "#notes")

    found = links(run(site, tmp_path))

    assert found["skipped links"].summary == (
        "4 of the article body's 4 links are not checked, by design: "
        "1 fragment-only, 1 javascript:, 1 mailto:, 1 tel:."
    )
    assert len(site.requests) == 4  # robots.txt, the page, and two sitemap locations


@pytest.mark.parametrize("status", [404, 410])
def test_a_404_or_410_link_is_a_defect_with_a_recommendation(tmp_path: Path, status: int) -> None:
    """The only defect condition."""
    gone = "https://www.example.org/gone"
    site = web(gone)
    site.add(gone, respond(status))

    result = run(site, tmp_path)

    finding = links(result)[gone]
    assert finding.defect
    assert finding.summary == f"The link {gone} answers {status}, so it leads to no page."
    (advice,) = [f for f in result.findings if f.based_on == (finding.id,)]
    assert advice.summary == f"Update or remove the article's link to {gone}."
    assert f"answers {status}" in (advice.rationale or "")


def test_a_redirect_is_a_fact_naming_the_final_url(tmp_path: Path) -> None:
    """A moved page is not a broken link."""
    moved = "https://www.example.org/old"
    site = web(moved)
    site.add(moved, redirect("https://www.example.org/new"))
    site.add("https://www.example.org/new", respond(200, b"x", HTML))

    finding = links(run(site, tmp_path))[moved]

    assert not finding.defect
    assert finding.summary == (
        f"The link {moved} redirects (1 hop) to https://www.example.org/new, which answers 200."
    )


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (respond(401), ReasonCode.ACCESS_DENIED),
        (respond(403), ReasonCode.ACCESS_DENIED),
        (respond(429), ReasonCode.RATE_LIMITED),
        (respond(500), ReasonCode.FETCH_FAILED),
    ],
)
def test_other_failures_use_the_matching_reason_codes(
    tmp_path: Path, reply: Reply, code: ReasonCode
) -> None:
    """Never a defect, and never a guess."""
    url = "https://www.example.org/x"
    site = web(url)
    site.add(url, reply)

    finding = links(run(site, tmp_path))[url]

    assert (finding.status, finding.reason_code) == (Status.NOT_DETERMINABLE, code)


def test_a_link_to_a_private_address_is_refused(tmp_path: Path) -> None:
    """The address screen applies to body links like any other fetch (ADR-005)."""
    url = "http://intranet.example/admin"
    site = web(url, "http://169.254.169.254/latest/meta-data/")
    resolver = FakeResolver({"intranet.example": ["10.0.0.9"]})

    found = links(run(site, tmp_path, resolver=resolver))

    assert found[url].reason_code is ReasonCode.ADDRESS_REFUSED
    assert found["http://169.254.169.254/latest/meta-data/"].reason_code is (
        ReasonCode.ADDRESS_REFUSED
    )
    assert not [u for u in site.urls() if "intranet" in u or "169.254" in u]


def test_a_link_robots_txt_disallows_is_not_fetched(tmp_path: Path) -> None:
    """Cernis respects every site's robots.txt, not only the author's."""
    url = "https://private.example/page"
    site = web(url)
    site.add("https://private.example/robots.txt", respond(200, b"User-agent: *\nDisallow: /\n"))

    finding = links(run(site, tmp_path))[url]

    assert finding.reason_code is ReasonCode.DISALLOWED_BY_ROBOTS
    assert url not in site.urls()


def test_the_per_page_limit_leaves_one_finding_saying_how_many(tmp_path: Path) -> None:
    """Links past the limit are named in one NOT_DETERMINABLE finding."""
    urls = [f"https://blog.example.com/2026/10/p{n}/" for n in range(5)]
    site = web(*urls)

    found = links(run(site, tmp_path, limits=AuditLimits(links=LinkLimits(per_page=2))))

    assert {u for u in urls if u in found} == set(urls[:2])
    unchecked = found["unchecked links"]
    assert (unchecked.status, unchecked.reason_code) == (
        Status.NOT_DETERMINABLE,
        ReasonCode.LIMIT_REACHED,
    )
    assert unchecked.summary == (
        "Whether 3 of the article body's links resolve is not determinable: Cernis did not "
        "fetch them: 3 past the limit of 2 links per page."
    )
    assert unchecked.evidence[0].observed == " ".join(urls[2:])
    assert not [u for u in urls[2:] if u in site.urls()]


def test_the_per_host_limit_counts_external_hosts_across_the_run(tmp_path: Path) -> None:
    """The page's own host is not limited; each external host gets at most N."""
    external = [f"https://cdn.example/f{n}" for n in range(4)]
    own = [f"https://blog.example.com/2026/10/q{n}/" for n in range(3)]
    site = web(*external, *own)

    found = links(run(site, tmp_path, limits=AuditLimits(links=LinkLimits(per_external_host=1))))

    assert set(own) <= set(found)
    assert [u for u in external if u in found] == external[:1]
    assert "3 past the limit of 1 links per external host per run (cdn.example)" in (
        found["unchecked links"].summary
    )


def test_link_bodies_are_never_stored(tmp_path: Path) -> None:
    """Links are fetched for their status only; the cache holds no body for them."""
    url = "https://www.example.org/cached"
    site = web(url)
    site.add(url, respond(200, b"body", {**HTML, "etag": '"e1"'}))

    run(site, tmp_path)

    assert Cache(tmp_path).lookup(url) is None


def test_a_page_with_no_article_extractor_says_what_would_answer(tmp_path: Path) -> None:
    """The generic extractor cannot tell article links from navigation."""
    site = web("https://www.example.org/a")

    found = links(run(site, tmp_path, site_type=None))

    (finding,) = found.values()
    assert finding.reason_code is ReasonCode.REQUIRES_EXTERNAL_DATA
    assert "dev or wordpress" in (finding.would_require or "")
    assert "https://www.example.org/a" not in site.urls()


def test_a_body_with_no_links_is_a_fact(tmp_path: Path) -> None:
    """Absence is evidence."""
    (finding,) = links(run(web(), tmp_path)).values()

    assert finding.summary == "The article body has no links."


# Session 5b audit (aud_gwCSZD5Y6S) regressions


def test_a_link_already_fetched_costs_no_host_budget(tmp_path: Path) -> None:
    """V3 f10: the same external link on two pages is one request and one budget unit."""
    shared = "https://cdn.example/shared"
    second = "https://blog.example.com/2026/11/second/"
    site = web(shared, "https://cdn.example/other")
    site.add(second, respond(200, page(shared), HTML))
    fetcher = make_fetcher(site, tmp_path, min_interval=0)
    limits = AuditLimits(links=LinkLimits(per_external_host=2))

    result = audit(
        [Target(url=PAGE, site=SiteType.WORDPRESS), Target(url=second, site=SiteType.WORDPRESS)],
        fetcher,
        now=clock(),
        limits=limits,
    )

    on_second = [f for f in result.findings if f.subject_url == second and f.target == shared]
    assert on_second[0].status is Status.OBSERVED
    assert site.urls().count(shared) == 1


def test_a_redirect_destination_is_charged_to_its_host(tmp_path: Path) -> None:
    """V1 f5: links redirecting to one external host share that host's budget."""
    hops = [f"https://blog.example.com/go/{n}" for n in range(3)]
    site = web(*hops, "https://cdn.example/direct")
    for n, hop in enumerate(hops):
        site.add(hop, redirect(f"https://cdn.example/r{n}"))
        site.add(f"https://cdn.example/r{n}", respond(200, b"x", HTML))

    found = links(run(site, tmp_path, limits=AuditLimits(links=LinkLimits(per_external_host=2))))

    assert "https://cdn.example/direct" not in found
    assert "cdn.example" in found["unchecked links"].summary


def test_a_link_with_user_information_is_not_fetchable(tmp_path: Path) -> None:
    """V3 f3: a link the fetcher refuses is named for what it is."""
    site = web("https://user:secret@www.example.org/x")

    found = links(run(site, tmp_path))

    assert found["skipped links"].summary.endswith("by design: 1 not fetchable.")
    assert not [u for u in site.urls() if "example.org" in u]
