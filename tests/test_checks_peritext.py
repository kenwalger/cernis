"""The nine peritext checks against the ten fixtures, with every expected finding written out.

Each fixture's expected findings were written by hand from the fixture and
DESIGN.md section 4 (the "Reports" and "Defect when" columns) before the
checks existed. A row is ``(check_id, target, status, defect, actor, summary)``;
recommendations are listed separately as ``(template id, the check it rests on)``.
"""

import dataclasses
import itertools

import pytest
from parse_support import DEV_URL, WORDPRESS_URL, fixture, receipt_for

from cernis.checks.peritext import peritext_findings
from cernis.checks.recommend import recommendations_for
from cernis.model import Actor, Finding, Status
from cernis.parse import SiteType, effective_site, parse_page

A, P = Actor.AUTHOR, Actor.PLATFORM
OBS, ND = Status.OBSERVED, Status.NOT_DETERMINABLE
VOLATILE_URL = "https://dev.to/example-author/volatile-tokens-7g8h"

DEV_DESCRIPTION = "A hand-written page that imitates a DEV article, for Cernis's tests."
DEV_TITLE = "A Synthetic Post About Fixtures - DEV Community"
WP_DESCRIPTION = "A hand-written page that imitates a WordPress entry, for Cernis's tests."
WP_TITLE = "A Synthetic Post About Fixtures \u2013 Example Blog"
WP_CANONICAL = "https://blog.example.com/2026/10/a-synthetic-post/"

Row = tuple[str, str, Status, bool, Actor, str]


def og_rows(actor: Actor, states: dict[str, str], url_actor: Actor | None = None) -> list[Row]:
    """Write the four peri.og.core rows.

    :param actor: The actor for og:title, og:description, and og:image.
    :param states: Each property's summary ending, such as ``is present.``.
    :param url_actor: The actor for og:url, if different.
    :return: The rows.
    """
    return [
        (
            "peri.og.core",
            prop,
            OBS,
            False,
            url_actor if prop == "og:url" and url_actor else actor,
            f"{prop} {states[prop]}",
        )
        for prop in ("og:title", "og:description", "og:image", "og:url")
    ]


ALL_PRESENT = {p: "is present." for p in ("og:title", "og:description", "og:image", "og:url")}
ALL_ABSENT = {p: "is absent." for p in ("og:title", "og:description", "og:image", "og:url")}

EXPECTED: dict[str, tuple[str, SiteType | None, list[Row], list[tuple[str, str]]]] = {
    "dev-article": (
        DEV_URL,
        None,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares a canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                f"The page declares one canonical URL: {WP_CANONICAL}.",
            ),
            ("peri.canonical.absolute", "", OBS, False, A, "The canonical URL is absolute."),
            (
                "peri.meta.description",
                "",
                OBS,
                False,
                A,
                f"The page has a meta description of {len(DEV_DESCRIPTION)} characters.",
            ),
            *og_rows(A, ALL_PRESENT, url_actor=P),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                True,
                P,
                f"og:url ({DEV_URL}) and the canonical URL ({WP_CANONICAL}) are different.",
            ),
            ("peri.lang", "", OBS, False, P, "The page declares its language as 'en'."),
            (
                "peri.jsonld.parses",
                "block 1",
                OBS,
                False,
                P,
                "JSON-LD block 1 parses; its @type is Article.",
            ),
            (
                "peri.title",
                "",
                OBS,
                False,
                P,
                f"The page's title is {len(DEV_TITLE)} characters long.",
            ),
        ],
        [],
    ),
    "wordpress-entry": (
        WORDPRESS_URL,
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares a canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                f"The page declares one canonical URL: {WP_CANONICAL}.",
            ),
            ("peri.canonical.absolute", "", OBS, False, A, "The canonical URL is absolute."),
            (
                "peri.meta.description",
                "",
                OBS,
                False,
                A,
                f"The page has a meta description of {len(WP_DESCRIPTION)} characters.",
            ),
            *og_rows(A, ALL_PRESENT),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "og:url and the canonical URL are identical.",
            ),
            ("peri.lang", "", OBS, False, A, "The page declares its language as 'en-US'."),
            (
                "peri.jsonld.parses",
                "block 1",
                OBS,
                False,
                A,
                "JSON-LD block 1 parses; its @types are Article, WebPage.",
            ),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len(WP_TITLE)} characters long.",
            ),
        ],
        [],
    ),
    "missing-canonical": (
        "https://blog.example.com/no-canonical/",
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares no canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                "The page declares no canonical URL, so there is nothing to compare.",
            ),
            (
                "peri.meta.description",
                "",
                OBS,
                False,
                A,
                f"The page has a meta description of {len('This page declares no canonical URL.')} characters.",
            ),
            *og_rows(A, ALL_PRESENT),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "There is no canonical URL to compare with og:url.",
            ),
            ("peri.lang", "", OBS, False, A, "The page declares its language as 'en'."),
            ("peri.jsonld.parses", "", OBS, False, A, "The page has no JSON-LD blocks."),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len('A Post With No Canonical')} characters long.",
            ),
        ],
        [],
    ),
    "two-canonicals": (
        "https://blog.example.com/two-canonicals/",
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares 2 canonical links."),
            (
                "peri.canonical.single",
                "",
                OBS,
                True,
                A,
                "The page declares 2 canonical links that name different URLs.",
            ),
            ("peri.canonical.absolute", "", OBS, False, A, "All 2 canonical URLs are absolute."),
            (
                "peri.meta.description",
                "",
                OBS,
                False,
                A,
                f"The page has a meta description of {len('Two canonical links that disagree.')} characters.",
            ),
            *og_rows(A, ALL_ABSENT),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "There is no og:url to compare with the canonical URL.",
            ),
            ("peri.lang", "", OBS, False, A, "The page declares its language as 'en'."),
            ("peri.jsonld.parses", "", OBS, False, A, "The page has no JSON-LD blocks."),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len('A Post With Two Canonicals')} characters long.",
            ),
        ],
        [("peri.canonical.single.keep-one", "peri.canonical.single")],
    ),
    "relative-canonical": (
        "https://blog.example.com/2026/10/relative-canonical/",
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares a canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                "The page declares one canonical URL: /2026/10/relative-canonical/.",
            ),
            (
                "peri.canonical.absolute",
                "",
                OBS,
                True,
                A,
                "The canonical URL '/2026/10/relative-canonical/' is relative.",
            ),
            (
                "peri.meta.description",
                "",
                OBS,
                False,
                A,
                f"The page has a meta description of {len('The canonical is a path, not an absolute URL.')} characters.",
            ),
            *og_rows(A, ALL_ABSENT),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "There is no og:url to compare with the canonical URL.",
            ),
            ("peri.lang", "", OBS, False, A, "The page declares its language as 'en'."),
            ("peri.jsonld.parses", "", OBS, False, A, "The page has no JSON-LD blocks."),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len('A Post With a Relative Canonical')} characters long.",
            ),
        ],
        [("peri.canonical.absolute.make-absolute", "peri.canonical.absolute")],
    ),
    "missing-og": (
        "https://blog.example.com/missing-og/",
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares a canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                "The page declares one canonical URL: https://blog.example.com/missing-og/.",
            ),
            ("peri.canonical.absolute", "", OBS, False, A, "The canonical URL is absolute."),
            ("peri.meta.description", "", OBS, False, A, "The page has no meta description."),
            *og_rows(
                A,
                {
                    "og:title": "is present.",
                    "og:description": "is declared with name= rather than property=.",
                    "og:image": "is present but empty.",
                    "og:url": "is absent.",
                },
            ),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "There is no og:url to compare with the canonical URL.",
            ),
            (
                "peri.lang",
                "",
                OBS,
                False,
                A,
                "The page does not declare a language (no lang attribute on <html>).",
            ),
            ("peri.jsonld.parses", "", OBS, False, A, "The page has no JSON-LD blocks."),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len('A Post With Only Some Open Graph Tags')} characters long.",
            ),
        ],
        [],
    ),
    "broken-jsonld": (
        "https://blog.example.com/broken-jsonld/",
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares a canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                "The page declares one canonical URL: https://blog.example.com/broken-jsonld/.",
            ),
            ("peri.canonical.absolute", "", OBS, False, A, "The canonical URL is absolute."),
            ("peri.meta.description", "", OBS, False, A, "The page has no meta description."),
            *og_rows(A, ALL_ABSENT),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "There is no og:url to compare with the canonical URL.",
            ),
            ("peri.lang", "", OBS, False, A, "The page declares its language as 'en'."),
            (
                "peri.jsonld.parses",
                "block 1",
                OBS,
                False,
                A,
                "JSON-LD block 1 parses; its @type is BlogPosting.",
            ),
            (
                "peri.jsonld.parses",
                "block 2",
                OBS,
                True,
                A,
                "JSON-LD block 2 does not parse: not valid JSON.",
            ),
            (
                "peri.jsonld.parses",
                "block 3",
                OBS,
                False,
                A,
                "JSON-LD block 3 parses; its @types are Article, NewsArticle, Person.",
            ),
            (
                "peri.jsonld.parses",
                "block 4",
                OBS,
                True,
                A,
                "JSON-LD block 4 does not parse: the block is empty.",
            ),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len('A Post With Broken JSON-LD')} characters long.",
            ),
        ],
        [
            ("peri.jsonld.parses.fix-json", "peri.jsonld.parses"),
            ("peri.jsonld.parses.fix-json", "peri.jsonld.parses"),
        ],
    ),
    "malformed": (
        "https://blog.example.com/mal-formee/",
        SiteType.WORDPRESS,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares 2 canonical links."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                "The page declares 2 canonical links; only one has an href, naming https://blog.example.com/mal-formee/.",
            ),
            (
                "peri.canonical.absolute",
                "",
                OBS,
                True,
                A,
                "Of 2 canonical links, 1 is not an absolute http or https URL.",
            ),
            (
                "peri.meta.description",
                "",
                OBS,
                False,
                A,
                f"The page has a meta description of {len('Sans guillemets ni balises fermantes')} characters.",
            ),
            *og_rows(
                A,
                {
                    "og:title": "is present but has no content attribute.",
                    "og:description": "is absent.",
                    "og:image": "is present.",
                    "og:url": "is absent.",
                },
            ),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                A,
                "There is no og:url to compare with the canonical URL.",
            ),
            ("peri.lang", "", OBS, False, A, "The page declares its language as 'fr'."),
            (
                "peri.jsonld.parses",
                "block 1",
                OBS,
                True,
                A,
                "JSON-LD block 1 does not parse: not valid JSON.",
            ),
            (
                "peri.title",
                "",
                OBS,
                False,
                A,
                f"The page's title is {len('Une page mal formée')} characters long.",
            ),
        ],
        [
            ("peri.canonical.absolute.add-href", "peri.canonical.absolute"),
            ("peri.jsonld.parses.fix-json", "peri.jsonld.parses"),
        ],
    ),
}

for _name in ("volatile-a", "volatile-b"):
    EXPECTED[_name] = (
        VOLATILE_URL,
        None,
        [
            ("peri.canonical.present", "", OBS, False, A, "The page declares a canonical link."),
            (
                "peri.canonical.single",
                "",
                OBS,
                False,
                A,
                f"The page declares one canonical URL: {VOLATILE_URL}.",
            ),
            ("peri.canonical.absolute", "", OBS, False, A, "The canonical URL is absolute."),
            ("peri.meta.description", "", OBS, False, A, "The page has no meta description."),
            *og_rows(
                A,
                {
                    "og:title": "is present.",
                    "og:description": "is absent.",
                    "og:image": "is absent.",
                    "og:url": "is absent.",
                },
                url_actor=P,
            ),
            (
                "peri.og.url_matches_canonical",
                "",
                OBS,
                False,
                P,
                "There is no og:url to compare with the canonical URL.",
            ),
            ("peri.lang", "", OBS, False, P, "The page declares its language as 'en'."),
            ("peri.jsonld.parses", "", OBS, False, P, "The page has no JSON-LD blocks."),
            (
                "peri.title",
                "",
                OBS,
                False,
                P,
                f"The page's title is {len('A Synthetic Post With Volatile Tokens')} characters long.",
            ),
        ],
        [],
    )


def run_checks(name: str) -> tuple[list[Finding], list[Finding]]:
    """Run the peritext checks and recommendations over one fixture.

    :param name: The fixture.
    :return: The observed findings and the recommendations.
    """
    url, site, _, _ = EXPECTED[name]
    body = fixture(name)
    receipt = receipt_for(body, url)
    page = parse_page(receipt, body)
    counter = itertools.count(1)

    def new_id() -> str:
        return f"f-{next(counter):03d}"

    findings = peritext_findings(
        page, receipt, subject_url=url, site=effective_site(url, site), new_id=new_id
    )
    advice = recommendations_for(findings, page=page, receipt=receipt, new_id=new_id)
    return findings, advice


def test_every_fixture_is_covered() -> None:
    """All ten fixtures have expectations."""
    assert len(EXPECTED) == 10


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_fixture_gives_exactly_the_expected_findings(name: str) -> None:
    """Every check, every target, every status, defect flag, actor, and summary."""
    findings, _ = run_checks(name)

    actual = [(f.check_id, f.target, f.status, f.defect, f.actor, f.summary) for f in findings]
    assert actual == EXPECTED[name][2]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_fixture_gives_exactly_the_expected_recommendations(name: str) -> None:
    """A recommendation for each defect the author can act on, and none for anything else."""
    findings, advice = run_checks(name)
    by_id = {finding.id: finding for finding in findings}

    actual = [(r.target.split(":")[0], by_id[r.based_on[0]].check_id) for r in advice]
    assert actual == EXPECTED[name][3]
    for recommendation in advice:
        assert recommendation.status is Status.RECOMMENDATION
        (based,) = recommendation.based_on
        assert by_id[based].defect
        assert recommendation.actor is by_id[based].actor


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_only_the_tables_defect_conditions_set_defect(name: str) -> None:
    """Defects come only from the four checks DESIGN.md section 4 gives a defect condition.

    Those are canonical.single, canonical.absolute, og.url_matches_canonical,
    and jsonld.parses; the others never set defect.
    """
    findings, _ = run_checks(name)

    never = {
        "peri.canonical.present",
        "peri.meta.description",
        "peri.og.core",
        "peri.lang",
        "peri.title",
    }
    assert not [f for f in findings if f.check_id in never and f.defect]


def test_every_finding_cites_the_page_receipt() -> None:
    """Every observed finding carries evidence from the receipt it was read from."""
    for name in EXPECTED:
        for finding in run_checks(name)[0]:
            assert finding.evidence, (name, finding.check_id)
            assert {item.receipt_id for item in finding.evidence} == {"r-001"}


def test_absence_records_what_was_searched_for() -> None:
    """A missing canonical is evidence of a search, not a missing value."""
    findings, _ = run_checks("missing-canonical")
    (present,) = [f for f in findings if f.check_id == "peri.canonical.present"]

    (evidence,) = present.evidence
    assert evidence.observed is None
    assert evidence.searched_for == 'a <link> element whose rel includes "canonical"'


def test_canonical_evidence_records_each_href_as_written() -> None:
    """Two canonicals: two pieces of evidence, values as written."""
    findings, _ = run_checks("two-canonicals")
    (single,) = [f for f in findings if f.check_id == "peri.canonical.single"]

    assert [e.observed for e in single.evidence] == [
        "https://blog.example.com/two-canonicals/",
        "https://dev.to/example-author/two-canonicals-5e6f",
    ]


def test_a_canonical_outside_head_is_located_there() -> None:
    """Evidence says where the element actually was."""
    body = (
        b'<html><head></head><body><link rel="canonical" href="https://a.example/"></body></html>'
    )
    receipt = receipt_for(body, "https://a.example/")
    page = parse_page(receipt, body)

    findings = peritext_findings(
        page, receipt, subject_url="https://a.example/", site=None, new_id=lambda: "f-1"
    )

    (present,) = [f for f in findings if f.check_id == "peri.canonical.present"]
    assert present.evidence[0].location == 'body > link[rel="canonical"] href'


def test_without_a_known_site_every_actor_is_unknown() -> None:
    """Who controls an element cannot be told without knowing the site."""
    body = fixture("wordpress-entry")
    receipt = receipt_for(body, WORDPRESS_URL)
    page = parse_page(receipt, body)

    findings = peritext_findings(
        page, receipt, subject_url=WORDPRESS_URL, site=None, new_id=lambda: "f-1"
    )

    assert {f.actor for f in findings} == {Actor.UNKNOWN}


@pytest.mark.parametrize(
    ("canonical", "og_url", "status", "defect", "summary"),
    [
        (
            "https://a.example/p/",
            "https://a.example/p/",
            OBS,
            False,
            "og:url and the canonical URL are identical.",
        ),
        (
            "https://a.example/p/",
            "https://A.example/p",
            OBS,
            False,
            "og:url and the canonical URL are equivalent (host case, trailing slash).",
        ),
        (
            "/p/",
            "https://a.example/p/",
            OBS,
            False,
            "og:url and the canonical URL are identical (the canonical is relative, so it was "
            "resolved against the page's URL first).",
        ),
        (
            "https://a.example/p/?ref=x",
            "https://a.example/p/",
            OBS,
            True,
            "og:url (https://a.example/p/) and the canonical URL (https://a.example/p/?ref=x) are different.",
        ),
    ],
)
def test_og_url_against_the_canonical(
    canonical: str, og_url: str, status: Status, defect: bool, summary: str
) -> None:
    """IDENTICAL and EQUIVALENT are facts; DIFFERENT is the defect."""
    body = (
        f'<html><head><link rel="canonical" href="{canonical}">'
        f'<meta property="og:url" content="{og_url}"></head></html>'
    ).encode()
    receipt = receipt_for(body, "https://a.example/p/")
    page = parse_page(receipt, body)

    findings = peritext_findings(
        page,
        receipt,
        subject_url="https://a.example/p/",
        site=SiteType.WORDPRESS,
        new_id=lambda: "f-1",
    )

    (match,) = [f for f in findings if f.check_id == "peri.og.url_matches_canonical"]
    assert (match.status, match.defect, match.summary) == (status, defect, summary)


def test_og_url_against_two_disagreeing_canonicals_is_ambiguous() -> None:
    """With two canonicals that differ, which one og:url should match cannot be told."""
    body = (
        b'<html><head><link rel="canonical" href="https://a.example/1">'
        b'<link rel="canonical" href="https://a.example/2">'
        b'<meta property="og:url" content="https://a.example/1"></head></html>'
    )
    receipt = receipt_for(body, "https://a.example/1")
    page = parse_page(receipt, body)

    findings = peritext_findings(
        page,
        receipt,
        subject_url="https://a.example/1",
        site=SiteType.WORDPRESS,
        new_id=lambda: "f-1",
    )

    (match,) = [f for f in findings if f.check_id == "peri.og.url_matches_canonical"]
    assert match.status is ND
    assert match.reason_code is not None
    assert match.reason_code.value == "AMBIGUOUS"
    assert match.question == "Whether og:url agrees with the canonical URL"
    assert len(match.evidence) == 3


def test_a_redirect_makes_og_url_and_the_canonical_equivalent() -> None:
    """og:url naming the requested URL, which redirected to the canonical, is EQUIVALENT."""
    body = (
        b'<html><head><link rel="canonical" href="https://a.example/new">'
        b'<meta property="og:url" content="https://a.example/old"></head></html>'
    )
    receipt = receipt_for(body, "https://a.example/new")
    redirected = dataclasses.replace(
        receipt, requested_url="https://a.example/old", redirect_chain=("https://a.example/old",)
    )
    page = parse_page(redirected, body)

    findings = peritext_findings(
        page,
        redirected,
        subject_url="https://a.example/old",
        site=SiteType.WORDPRESS,
        new_id=lambda: "f-1",
    )

    (match,) = [f for f in findings if f.check_id == "peri.og.url_matches_canonical"]
    assert (match.defect, match.summary) == (
        False,
        "og:url and the canonical URL are equivalent (redirect, receipt r-001).",
    )
