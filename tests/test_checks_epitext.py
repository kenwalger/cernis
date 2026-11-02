"""Tests for the epitext checks: the pair check, canonical resolution, and og:image.

Every case runs end to end, through the real fetcher on a scripted web, so
reuse of fetches within a run is tested along with the checks.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fetch_support import Reply, Site, make_fetcher, redirect, respond
from parse_support import DEV_URL, WORDPRESS_URL, fixture

from cernis.audit import PairTarget, Target, audit
from cernis.fetch.cache import Cache
from cernis.model import Actor, Finding, ReasonCode, Run, Status
from cernis.parse import SiteType
from cernis.report import report_markdown

HTML = {"content-type": "text/html; charset=utf-8"}
PNG = {"content-type": "image/png", "etag": '"img1"'}
WP_IMAGE = "https://blog.example.com/wp-content/uploads/2026/10/cover.png"
DEV_IMAGE = "https://media.dev.example/cover/synthetic-cover.png"
OWNED_COPY = "https://mirror.example.net/a-synthetic-post/"


def clock() -> Callable[[], datetime]:
    """Return a clock that reads one second later each time.

    :return: The clock.
    """
    moments = iter(datetime(2026, 11, 2, 12, 0, n, tzinfo=UTC) for n in range(60))
    return lambda: next(moments)


def web(copy_html: bytes | None = None, original_html: bytes | None = None) -> Site:
    """Script a web with the WordPress original, the DEV copy, and both images.

    :param copy_html: The copy's page; the dev-article fixture if ``None``.
    :param original_html: The original's page; the wordpress-entry fixture if ``None``.
    :return: The scripted web.
    """
    site = Site()
    site.add(WORDPRESS_URL, respond(200, original_html or fixture("wordpress-entry"), HTML))
    site.add(DEV_URL, respond(200, copy_html or fixture("dev-article"), HTML))
    site.add(WP_IMAGE, respond(200, b"\x89PNG fake", PNG))
    site.add(DEV_IMAGE, respond(200, b"\x89PNG fake", PNG))
    return site


def pair_run(
    site: Site,
    tmp_path: Path,
    original: str = WORDPRESS_URL,
    copy: str = DEV_URL,
    copy_site: SiteType | None = None,
) -> Run:
    """Audit one pair on a scripted web.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :param original: The original's URL.
    :param copy: The copy's URL.
    :param copy_site: The copy's declared site type.
    :return: The run.
    """
    pair = PairTarget(
        original=Target(url=original, site=SiteType.WORDPRESS),
        copy=Target(url=copy, site=copy_site),
    )
    return audit([], make_fetcher(site, tmp_path, min_interval=0), now=clock(), pairs=[pair])


def pick(run: Run, check_id: str, target: str | None = None) -> list[Finding]:
    """Select a check's own findings (not recommendations), optionally for one target.

    :param run: The run.
    :param check_id: The check.
    :param target: The target, or ``None`` for all.
    :return: The findings.
    """
    return [
        f
        for f in run.findings
        if f.check_id == check_id
        and f.status is not Status.RECOMMENDATION
        and (target is None or f.target == target)
    ]


def edited(name: str, old: str, new: str) -> bytes:
    """Return a fixture with one exact edit.

    :param name: The fixture.
    :param old: Text that must occur in it.
    :param new: Its replacement.
    :return: The edited page.
    """
    text = fixture(name).decode("utf-8")
    assert old in text, old
    return text.replace(old, new).encode("utf-8")


# The pair check


def test_a_matching_pair_has_two_facts_and_no_defect(tmp_path: Path) -> None:
    """The copy names the original, and the original names itself."""
    run = pair_run(web(), tmp_path)

    copy_side, original_side = pick(run, "epi.pair.canonical")
    assert (copy_side.target, copy_side.defect, copy_side.actor) == ("copy", False, Actor.AUTHOR)
    assert copy_side.summary == f"The copy's canonical URL is the original's URL, {WORDPRESS_URL}."
    assert (original_side.target, original_side.defect) == ("original", False)
    assert original_side.summary == (
        f"The original's canonical URL is the original's own URL, {WORDPRESS_URL}."
    )
    assert {f.subject_url for f in (copy_side, original_side)} == {DEV_URL}
    assert [(p.original, p.copy) for p in run.pairs] == [(WORDPRESS_URL, DEV_URL)]
    assert not [
        f
        for f in run.findings
        if f.status is Status.RECOMMENDATION and f.check_id.startswith("epi.pair")
    ]


def test_a_copy_with_no_canonical_is_a_defect_with_a_dev_recommendation(tmp_path: Path) -> None:
    """On DEV, the fix is canonical_url in the front matter."""
    copy = edited("dev-article", f'  <link rel="canonical" href="{WORDPRESS_URL}">\n', "")

    run = pair_run(web(copy_html=copy), tmp_path)

    (copy_side,) = pick(run, "epi.pair.canonical", "copy")
    assert copy_side.defect
    assert copy_side.summary == (
        f"The copy declares no canonical URL, so it does not name the original, {WORDPRESS_URL}."
    )
    (advice,) = [f for f in run.findings if f.based_on == (copy_side.id,)]
    assert advice.summary == f"Set canonical_url in the copy's DEV front matter to {WORDPRESS_URL}."
    assert "the copy's canonical is missing" in (advice.rationale or "")


def test_a_copy_pointing_elsewhere_is_a_defect(tmp_path: Path) -> None:
    """A DEV copy whose canonical is itself contradicts the declared pairing."""
    copy = edited("dev-article", f'href="{WORDPRESS_URL}"', f'href="{DEV_URL}"')

    run = pair_run(web(copy_html=copy), tmp_path)

    (copy_side,) = pick(run, "epi.pair.canonical", "copy")
    assert copy_side.defect
    assert copy_side.summary == (
        f"The copy's canonical URL ({DEV_URL}) is different from the original's URL "
        f"({WORDPRESS_URL})."
    )
    (advice,) = [f for f in run.findings if f.based_on == (copy_side.id,)]
    assert f"the copy's canonical names {DEV_URL}" in (advice.rationale or "")


@pytest.mark.parametrize(
    ("canonical", "template"),
    [
        (None, "epi.pair.canonical.add-copy-canonical"),
        ("https://mirror.example.net/elsewhere/", "epi.pair.canonical.set-copy-canonical"),
    ],
)
def test_a_copy_off_dev_gets_a_plain_canonical_recommendation(
    tmp_path: Path, canonical: str | None, template: str
) -> None:
    """An owned copy elsewhere: add or set the canonical link itself."""
    page = edited(
        "wordpress-entry",
        f"<link rel='canonical' href='{WORDPRESS_URL}' />",
        f"<link rel='canonical' href='{canonical}' />" if canonical else "",
    )
    site = web()
    site.add(OWNED_COPY, respond(200, page, HTML))

    run = pair_run(site, tmp_path, copy=OWNED_COPY, copy_site=SiteType.OWNED)

    (copy_side,) = pick(run, "epi.pair.canonical", "copy")
    (advice,) = [f for f in run.findings if f.based_on == (copy_side.id,)]
    assert advice.target == f"{template}:copy"


def test_a_trailing_slash_is_equivalent_and_named(tmp_path: Path) -> None:
    """A cosmetic difference is a fact that names the normalization, never a defect."""
    without_slash = WORDPRESS_URL.rstrip("/")
    copy = edited("dev-article", f'href="{WORDPRESS_URL}"', f'href="{without_slash}"')

    run = pair_run(web(copy_html=copy), tmp_path)

    (copy_side,) = pick(run, "epi.pair.canonical", "copy")
    assert not copy_side.defect
    assert copy_side.summary == (
        f"The copy's canonical URL ({without_slash}) is equivalent to the original's URL "
        f"({WORDPRESS_URL}): trailing slash."
    )


def test_a_redirect_makes_the_pair_equivalent_citing_its_receipt(tmp_path: Path) -> None:
    """The original was declared by a short URL that redirects to the canonical one."""
    short = "https://blog.example.com/?p=42"
    site = web()
    site.add(short, redirect(WORDPRESS_URL))

    run = pair_run(site, tmp_path, original=short)

    copy_side, original_side = pick(run, "epi.pair.canonical")
    page_receipt = next(r for r in run.receipts if r.requested_url == short)
    for side in (copy_side, original_side):
        assert not side.defect
        assert side.summary.endswith(f": redirect, receipt {page_receipt.id}.")


def test_an_original_whose_canonical_names_another_page_is_a_defect(tmp_path: Path) -> None:
    """The original's own canonical must name the original."""
    other = "https://blog.example.com/2026/10/another-post/"
    original = edited("wordpress-entry", f"href='{WORDPRESS_URL}'", f"href='{other}'")
    site = web(original_html=original)
    site.add(other, respond(200, b"<html></html>", HTML))

    run = pair_run(site, tmp_path)

    (original_side,) = pick(run, "epi.pair.canonical", "original")
    assert original_side.defect
    (advice,) = [f for f in run.findings if f.based_on == (original_side.id,)]
    assert advice.summary == f"Set the original's canonical URL to its own URL, {WORDPRESS_URL}."


def test_an_unreachable_original_makes_the_pair_check_not_determinable(tmp_path: Path) -> None:
    """Without the original, neither side can be judged; the reason code is the original's."""
    site = web()
    site.add(WORDPRESS_URL, httpx.ConnectTimeout("slow"))

    run = pair_run(site, tmp_path)

    sides = pick(run, "epi.pair.canonical")
    assert [(f.target, f.status, f.reason_code) for f in sides] == [
        ("copy", Status.NOT_DETERMINABLE, ReasonCode.FETCH_FAILED),
        ("original", Status.NOT_DETERMINABLE, ReasonCode.FETCH_FAILED),
    ]
    assert sides[0].summary.startswith(
        f"Whether the copy's canonical URL names the original, {WORDPRESS_URL} is not "
        "determinable: the original could not be read whole: the request timed out"
    )
    assert pick(run, "peri.canonical.present")[1].status is Status.OBSERVED


@pytest.mark.parametrize(
    ("reply", "code"),
    [(respond(403), ReasonCode.ACCESS_DENIED), (respond(429), ReasonCode.RATE_LIMITED)],
)
def test_an_original_refusing_access_gives_its_reason_code(
    tmp_path: Path, reply: Reply, code: ReasonCode
) -> None:
    """The pair check carries the original's own reason code."""
    site = web()
    site.add(WORDPRESS_URL, reply)

    run = pair_run(site, tmp_path)

    assert {f.reason_code for f in pick(run, "epi.pair.canonical")} == {code}


def test_an_unreachable_copy_leaves_the_original_side_answered(tmp_path: Path) -> None:
    """The original can still be checked against itself."""
    site = web()
    site.add(DEV_URL, respond(404))

    run = pair_run(site, tmp_path)

    copy_side, original_side = pick(run, "epi.pair.canonical")
    assert (copy_side.status, copy_side.reason_code) == (
        Status.NOT_DETERMINABLE,
        ReasonCode.FETCH_FAILED,
    )
    assert original_side.status is Status.OBSERVED


def test_a_copy_with_two_disagreeing_canonicals_is_ambiguous(tmp_path: Path) -> None:
    """Which canonical names the copy's original cannot be told."""
    copy = edited(
        "dev-article",
        f'  <link rel="canonical" href="{WORDPRESS_URL}">\n',
        f'  <link rel="canonical" href="{WORDPRESS_URL}">\n'
        f'  <link rel="canonical" href="{DEV_URL}">\n',
    )

    run = pair_run(web(copy_html=copy), tmp_path)

    (copy_side,) = pick(run, "epi.pair.canonical", "copy")
    assert (copy_side.status, copy_side.reason_code) == (
        Status.NOT_DETERMINABLE,
        ReasonCode.AMBIGUOUS,
    )


# epi.canonical.resolves


def test_a_canonical_that_is_the_page_itself_reuses_the_page_fetch(tmp_path: Path) -> None:
    """Item 7: each distinct URL is fetched once per run."""
    site = web()

    run = pair_run(site, tmp_path)

    assert site.urls().count(WORDPRESS_URL) == 1
    (original_resolves,) = [
        f for f in pick(run, "epi.canonical.resolves") if f.subject_url == WORDPRESS_URL
    ]
    page_receipt = next(r for r in run.receipts if r.requested_url == WORDPRESS_URL)
    assert original_resolves.evidence[0].receipt_id == page_receipt.id
    assert original_resolves.summary == f"The canonical URL {WORDPRESS_URL} answers 200."
    assert len(run.receipts) == len({r.id for r in run.receipts})


def test_a_canonical_reached_by_a_redirect_reuses_that_fetch(tmp_path: Path) -> None:
    """A page that redirected to its canonical has already shown what the canonical answers."""
    short = "https://blog.example.com/2026/10/a-synthetic-post"
    site = web()
    site.add(short, redirect(WORDPRESS_URL))

    run = audit(
        [Target(url=short, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    assert site.urls().count(WORDPRESS_URL) == 1
    # The canonical answered directly; the redirect was the page URL's, not its.
    (finding,) = pick(run, "epi.canonical.resolves")
    assert finding.summary == f"The canonical URL {WORDPRESS_URL} answers 200."
    assert [e.location for e in finding.evidence] == ["HTTP status"]


@pytest.mark.parametrize(
    ("reply", "status", "defect", "summary"),
    [
        (
            respond(404),
            Status.OBSERVED,
            True,
            "The canonical URL {url} answers 404, so it names no page.",
        ),
        (
            respond(410),
            Status.OBSERVED,
            True,
            "The canonical URL {url} answers 410, so it names no page.",
        ),
        (respond(200, b"x", HTML), Status.OBSERVED, False, "The canonical URL {url} answers 200."),
        (
            redirect(WORDPRESS_URL),
            Status.OBSERVED,
            False,
            "The canonical URL {url} redirects (1 hop) to "
            + WORDPRESS_URL
            + ", which answers 200.",
        ),
        (respond(401), Status.NOT_DETERMINABLE, False, ""),
        (respond(403), Status.NOT_DETERMINABLE, False, ""),
        (respond(429), Status.NOT_DETERMINABLE, False, ""),
        (respond(500), Status.NOT_DETERMINABLE, False, ""),
    ],
)
def test_canonical_resolution_by_status(
    tmp_path: Path, reply: Reply, status: Status, defect: bool, summary: str
) -> None:
    """Defect only for 404 and 410; 401 and 403 are ACCESS_DENIED, 429 RATE_LIMITED."""
    elsewhere = "https://blog.example.com/canonical-target/"
    page = edited("wordpress-entry", f"href='{WORDPRESS_URL}'", f"href='{elsewhere}'")
    site = web(original_html=page)
    site.add(elsewhere, reply)

    run = audit(
        [Target(url=WORDPRESS_URL, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    (finding,) = pick(run, "epi.canonical.resolves")
    assert (finding.target, finding.status, finding.defect) == (elsewhere, status, defect)
    if summary:
        assert finding.summary == summary.format(url=elsewhere)
    expected_code = {
        401: ReasonCode.ACCESS_DENIED,
        403: ReasonCode.ACCESS_DENIED,
        429: ReasonCode.RATE_LIMITED,
        500: ReasonCode.FETCH_FAILED,
    }
    if status is Status.NOT_DETERMINABLE:
        code = int(finding.evidence[0].observed or 0)
        assert finding.reason_code is expected_code[code]
    advice = [f for f in run.findings if f.based_on == (finding.id,)]
    assert bool(advice) is defect
    if defect:
        assert (
            advice[0].summary
            == f"Change the canonical URL {elsewhere} to the URL of a page that exists."
        )


def test_a_canonical_redirect_records_the_whole_chain(tmp_path: Path) -> None:
    """The redirect chain is evidence, hop by hop."""
    first = "https://blog.example.com/c1/"
    page = edited("wordpress-entry", f"href='{WORDPRESS_URL}'", f"href='{first}'")
    site = web(original_html=page)
    site.add(first, redirect("https://blog.example.com/c2/"))
    site.add("https://blog.example.com/c2/", redirect("https://blog.example.com/c3/"))
    site.add("https://blog.example.com/c3/", respond(200, b"x", HTML))

    run = audit(
        [Target(url=WORDPRESS_URL, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    (finding,) = pick(run, "epi.canonical.resolves")
    chain = next(e.observed for e in finding.evidence if e.location == "redirect chain")
    assert (
        chain
        == "https://blog.example.com/c1/ -> https://blog.example.com/c2/ -> https://blog.example.com/c3/"
    )
    assert "redirects (2 hops) to https://blog.example.com/c3/" in finding.summary


def test_a_canonical_on_a_private_address_is_refused(tmp_path: Path) -> None:
    """The canonical fetch goes through the address screen like any other."""
    page = edited("wordpress-entry", f"href='{WORDPRESS_URL}'", "href='http://10.0.0.5/admin'")

    run = audit(
        [Target(url=WORDPRESS_URL, site=SiteType.WORDPRESS)],
        make_fetcher(web(original_html=page), tmp_path, min_interval=0),
        now=clock(),
    )

    (finding,) = pick(run, "epi.canonical.resolves")
    assert finding.reason_code is ReasonCode.ADDRESS_REFUSED


# epi.og.image.resolves


def test_an_image_is_a_fact_and_is_never_stored(tmp_path: Path) -> None:
    """An image answers with image/*; the cache never holds its body."""
    run = pair_run(web(), tmp_path)

    images = pick(run, "epi.og.image.resolves")
    assert {(f.target, f.defect) for f in images} == {(WP_IMAGE, False), (DEV_IMAGE, False)}
    assert any(
        f.summary == f"og:image {WP_IMAGE} answers 200 with an image (image/png)." for f in images
    )
    assert Cache(tmp_path).lookup(WP_IMAGE) is None


@pytest.mark.parametrize(
    ("reply", "summary"),
    [
        (
            respond(200, b"<html></html>", HTML),
            "og:image {url} answers 200 with Content-Type text/html, not an image.",
        ),
        (respond(200, b"x"), "og:image {url} answers 200 with no Content-Type, not an image."),
        (respond(404), "og:image {url} answers 404, so the page names no image."),
        (respond(410), "og:image {url} answers 410, so the page names no image."),
    ],
)
def test_an_og_image_that_is_not_an_image_is_a_defect(
    tmp_path: Path, reply: Reply, summary: str
) -> None:
    """HTML where an image should be, no content type, or a missing image."""
    site = web()
    site.add(WP_IMAGE, reply)

    run = audit(
        [Target(url=WORDPRESS_URL, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    (finding,) = pick(run, "epi.og.image.resolves")
    assert (finding.defect, finding.summary) == (True, summary.format(url=WP_IMAGE))
    (advice,) = [f for f in run.findings if f.based_on == (finding.id,)]
    assert advice.summary == "Set og:image to the URL of an image that exists."


def test_a_dev_og_image_defect_is_the_platforms_with_no_recommendation(tmp_path: Path) -> None:
    """DEV generates its og:image; the author cannot fix it."""
    site = web()
    site.add(DEV_IMAGE, respond(404))

    run = audit([Target(url=DEV_URL)], make_fetcher(site, tmp_path, min_interval=0), now=clock())

    (finding,) = pick(run, "epi.og.image.resolves")
    assert (finding.defect, finding.actor) == (True, Actor.PLATFORM)
    assert not [f for f in run.findings if f.based_on == (finding.id,)]


def test_an_image_redirect_is_followed_and_named(tmp_path: Path) -> None:
    """A redirecting image is a fact naming where it went."""
    site = web()
    site.add(WP_IMAGE, redirect("https://cdn.example/cover.png"))
    site.add("https://cdn.example/cover.png", respond(200, b"x", PNG))

    run = audit(
        [Target(url=WORDPRESS_URL, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    (finding,) = pick(run, "epi.og.image.resolves")
    assert finding.summary == (
        f"og:image {WP_IMAGE} answers 200 (after redirecting to https://cdn.example/cover.png) "
        "with an image (image/png)."
    )


# The owned site type


def test_an_owned_page_has_author_actors_throughout(tmp_path: Path) -> None:
    """Owned: generic extractor, and every finding is the author's."""
    site = web()
    site.add(OWNED_COPY, respond(200, fixture("wordpress-entry"), HTML))

    run = audit(
        [Target(url=OWNED_COPY, site=SiteType.OWNED)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    assert {f.actor for f in run.findings if f.subject_url == OWNED_COPY} == {Actor.AUTHOR}
    (snapshot,) = run.snapshots
    assert (snapshot.extractor_id, snapshot.content_sha256) == ("generic", None)


def test_an_unreadable_owned_page_is_still_the_authors(tmp_path: Path) -> None:
    """Even a failed fetch of an owned page names the author."""
    site = Site()
    site.add(OWNED_COPY, respond(500))

    run = audit(
        [Target(url=OWNED_COPY, site=SiteType.OWNED)],
        make_fetcher(site, tmp_path, min_interval=0),
        now=clock(),
    )

    assert {f.actor for f in run.findings} == {Actor.AUTHOR}


# The report


def test_the_report_presents_the_pair_as_one_subject_with_both_pages(tmp_path: Path) -> None:
    """One pair heading, then the original, the copy, and the pair check."""
    text = report_markdown(pair_run(web(), tmp_path))

    assert text.startswith("# Cernis audit: A Synthetic Post About Fixtures \u2013 Example Blog\n")
    assert f"Copy: {DEV_URL}\nOriginal: {WORDPRESS_URL}\n" in text
    assert f"- Pair 1: original {WORDPRESS_URL}; copy {DEV_URL}" in text
    observed = text.split("## Observed", 1)[1].split("## Recommendations", 1)[0]
    headings = [line for line in observed.splitlines() if line.startswith("###")]
    assert headings == [
        f"### Pair: {DEV_URL} (copy of {WORDPRESS_URL})",
        f"#### Original: {WORDPRESS_URL}",
        f"#### Copy: {DEV_URL}",
        "#### The pair",
    ]
