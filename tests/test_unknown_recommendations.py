"""Recommendations on ``UNKNOWN`` defects never assume the author controls what they name.

Since Session 6e a defect whose actor is ``UNKNOWN`` gets a recommendation
(DESIGN.md section 3, Actor). Cernis cannot tell who controls what such a
defect names, so its text must be conditional: "If you control X, change it;
if a theme or platform writes it, the change is theirs to make." These tests
render every template reachable with actor ``UNKNOWN``, through the real
recommendation functions, and check the text with a small fixed pattern list.

The pattern list (:data:`IMPERATIVES`, matched by
:func:`unconditional_instructions`): text is split into clauses at a
sentence end, ``;``, or ``:``, and an imperative verb from the list at the
start of a clause, or after a comma (optionally followed by "and", "or", or
"then"), is unconditional unless an "if" comes earlier in the same clause.
Every conditional wording must also say whose change it is otherwise
(:data:`HEDGES`). Like the no-promise phrase list, it is a floor, not a
proof: an imperative verb not on the list is not caught. When review finds a
case the list missed, add it here (the Session 7 audit, ``aud_BzbIG6RavZ``,
added the clause rule, the hedge, and three verbs).
"""

import itertools
import re
from collections.abc import Callable

import pytest
from parse_support import DEV_URL, receipt_for

from cernis.checks.epitext import epi_actor
from cernis.checks.peritext import peritext_findings
from cernis.checks.recommend import (
    recommendations_for,
    resource_recommendations,
    sitemap_recommendation,
)
from cernis.checks.recommendations import TEMPLATES, template_for
from cernis.checks.registry import check
from cernis.model import Actor, Evidence, Finding, Status
from cernis.parse import SiteType, parse_page
from cernis.promises import find_outcome_language

IMPERATIVES: tuple[str, ...] = (
    "add",
    "change",
    "check",
    "correct",
    "delete",
    "edit",
    "ensure",
    "fix",
    "give",
    "make",
    "remove",
    "replace",
    "set",
    "update",
    "use",
    "verify",
)
"""Imperative openings that instruct the reader to change something."""

HEDGES: tuple[str, ...] = ("the change is theirs to make", "only DEV can")
"""How a conditional wording says whose change it is when it is not the author's."""

_CLAUSE_START = re.compile(
    r"(?:^|,\s+(?:(?:and|or|then)\s+)?)(" + "|".join(IMPERATIVES) + r")\b",
    re.IGNORECASE,
)
_CLAUSE_END = re.compile(r"(?<=[.!?;:])\s+")
_IF = re.compile(r"\bif\b", re.IGNORECASE)

GENERIC_URL = "https://pages.example.org/a-post/"
"""A page with no site type: Cernis cannot tell who controls any field."""

PAIR_TEMPLATES = frozenset(
    {
        "epi.pair.canonical.set-copy-canonical",
        "epi.pair.canonical.set-dev-canonical-url",
        "epi.pair.canonical.add-copy-canonical",
        "epi.pair.canonical.set-original-canonical",
    }
)
"""The templates never reachable with ``UNKNOWN``: the pair check's findings are
always ``AUTHOR``, since the author declared the pair (DESIGN.md section 4)."""

REACHABLE_GENERIC = frozenset(
    {
        "peri.canonical.single.keep-one",
        "peri.canonical.absolute.make-absolute",
        "peri.canonical.absolute.add-href",
        "peri.canonical.absolute.fix-url",
        "peri.og.core.add-required",
        "peri.lang.add-lang",
        "peri.og.url_matches_canonical.align",
        "peri.jsonld.parses.fix-json",
        "epi.canonical.resolves.fix-canonical",
        "epi.og.image.resolves.fix-image",
        "epi.links.resolve.fix-link",
        "epi.sitemap.listed.add-page",
    }
)
"""Every template an ``UNKNOWN`` defect reaches on a page with no site type."""

REACHABLE_DEV = frozenset(
    {
        "peri.og.core.add-required",
        "peri.jsonld.parses.fix-json",
        "epi.og.image.resolves.fix-image",
    }
)
"""Every template an ``UNKNOWN`` defect reaches on DEV: og:image and JSON-LD,
which head_fields.toml lists as ``UNKNOWN`` there."""


def unconditional_instructions(text: str) -> list[str]:
    """Find each imperative instruction in ``text`` with no "if" before it.

    :param text: Recommendation text.
    :return: Each unconditional imperative, as matched; empty if none.
    """
    found: list[str] = []
    for clause in _CLAUSE_END.split(text):
        for match in _CLAUSE_START.finditer(clause):
            if not _IF.search(clause[: match.start(1)]):
                found.append(match.group(1))
    return found


def _ids() -> Callable[[], str]:
    """Return a finding id source.

    :return: A callable giving ``f-001``, ``f-002``, and so on.
    """
    counter = itertools.count(1)
    return lambda: f"f-{next(counter):03d}"


GENERIC_PAGES: tuple[bytes, ...] = (
    # Three canonicals, each a different problem; Open Graph in use but
    # incomplete; no lang; a JSON-LD block that is not JSON.
    b"<html><head><link rel='canonical' href='/a-post/'><link rel='canonical'>"
    b"<link rel='canonical' href='ftp://pages.example.org/a-post/'>"
    b"<meta property='og:title' content='A post'>"
    b"<script type='application/ld+json'>{not json</script></head><body></body></html>",
    # og:url names another page than the canonical.
    b"<html lang='en'><head><link rel='canonical' href='https://pages.example.org/a-post/'>"
    b"<meta property='og:title' content='A post'><meta property='og:type' content='article'>"
    b"<meta property='og:image' content='https://pages.example.org/i.png'>"
    b"<meta property='og:url' content='https://pages.example.org/another/'>"
    b"</head><body></body></html>",
)

DEV_PAGE = (
    f"<html lang='en'><head><link rel='canonical' href='{DEV_URL}'>"
    "<meta property='og:title' content='A post'><meta property='og:type' content='article'>"
    f"<meta property='og:url' content='{DEV_URL}'>"
    "<script type='application/ld+json'>{not json</script></head><body></body></html>"
).encode()


def _peritext(body: bytes, url: str, site: SiteType | None) -> list[Finding]:
    """Run the peritext checks and their recommendations over one page.

    :param body: The page.
    :param url: Its URL.
    :param site: Its site type.
    :return: The recommendations.
    """
    receipt = receipt_for(body, url)
    page = parse_page(receipt, body)
    new_id = _ids()
    observed = peritext_findings(page, receipt, subject_url=url, site=site, new_id=new_id)
    return recommendations_for(observed, page=page, receipt=receipt, site=site, new_id=new_id)


def _defect(
    check_id: str, site: SiteType | None, url: str, target: str, *evidence: tuple[str, str]
) -> Finding:
    """Build an observed defect about a resource, with the check's real actor.

    :param check_id: The check.
    :param site: The page's site type, for the actor.
    :param url: The page's URL.
    :param target: The resource's URL.
    :param *evidence: ``(location, observed)`` pairs.
    :return: The finding.
    """
    return Finding(
        id="f-900",
        check_id=check_id,
        check_version=check(check_id).version,
        status=Status.OBSERVED,
        actor=epi_actor(site, check_id),
        subject_url=url,
        summary="A synthetic defect.",
        target=target,
        evidence=tuple(
            Evidence(receipt_id="r-002", location=location, observed=value)
            for location, value in evidence
        ),
        defect=True,
    )


def _resources(url: str, site: SiteType | None) -> list[Finding]:
    """Recommend for every kind of resource defect.

    :param url: The page's URL.
    :param site: Its site type.
    :return: The recommendations.
    """
    defects = [
        _defect("epi.canonical.resolves", site, url, url, ("HTTP status", "404")),
        _defect("epi.links.resolve", site, url, "https://gone.example/x", ("HTTP status", "410")),
        _defect(
            "epi.og.image.resolves", site, url, "https://img.example/a.png", ("HTTP status", "404")
        ),
        _defect(
            "epi.og.image.resolves",
            site,
            url,
            "https://img.example/b.png",
            ("HTTP status", "200"),
            ("Content-Type", "text/html"),
        ),
    ]
    return resource_recommendations(defects, site=site, new_id=_ids())


def rendered(site: SiteType | None) -> list[Finding]:
    """Every recommendation an ``UNKNOWN`` defect gets on a site.

    :param site: ``None`` for a page with no site type, or ``SiteType.DEV``.
    :return: The recommendations, all with actor ``UNKNOWN``.
    """
    if site is SiteType.DEV:
        advice = _peritext(DEV_PAGE, DEV_URL, site)
        return [r for r in advice + _resources(DEV_URL, site) if r.actor is Actor.UNKNOWN]
    advice = [r for body in GENERIC_PAGES for r in _peritext(body, GENERIC_URL, None)]
    advice += _resources(GENERIC_URL, None)
    advice += sitemap_recommendation(
        _defect(
            "epi.sitemap.listed",
            None,
            GENERIC_URL,
            "",
            ("https://pages.example.org/sitemap.xml", "3 other pages"),
        ),
        url=GENERIC_URL,
        section="https://pages.example.org/",
        others=3,
        site=None,
        new_id=_ids(),
    )
    assert {r.actor for r in advice} == {Actor.UNKNOWN}
    return advice


def _base_id(recommendation: Finding) -> str:
    """Return the template id a recommendation's target starts with.

    :param recommendation: The recommendation.
    :return: The base template id.
    """
    return recommendation.target.split(":", 1)[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Set og:image to the URL of an image that exists.", ["Set"]),
        ("Give the link an href, or remove the link.", ["Give", "remove"]),
        ("The page is fine. Add a lang attribute.", ["Add"]),
        ("You declared it; change the canonical.", ["change"]),
        ("If you control the page, change it; fix the link.", ["fix"]),
        ("Check the front matter.", ["Check"]),
        ("If you control the page, add a lang attribute; if not, it is theirs to make.", []),
        ("The Open Graph protocol defines og:image as an image URL, and it answers 404.", []),
    ],
)
def test_the_pattern_list_catches_unconditional_instructions(
    text: str, expected: list[str]
) -> None:
    """The checker flags an imperative with no "if" before it, and nothing else."""
    assert unconditional_instructions(text) == expected


def test_every_base_template_opens_with_an_instruction() -> None:
    """The checker is not vacuous: every unconditional wording is flagged by it."""
    for template in TEMPLATES:
        if not template.variant_of:
            assert unconditional_instructions(template.action), template.id


@pytest.mark.parametrize(
    ("site", "expected"),
    [(None, REACHABLE_GENERIC), (SiteType.DEV, REACHABLE_DEV)],
    ids=["generic", "dev"],
)
def test_every_template_reachable_with_unknown_is_rendered(
    site: SiteType | None, expected: frozenset[str]
) -> None:
    """The rendering covers exactly the templates listed as reachable."""
    assert {_base_id(r) for r in rendered(site)} == expected


def test_only_the_pair_templates_are_unreachable_with_unknown() -> None:
    """A new template must be added to the reachable list or shown unreachable."""
    bases = {t.id for t in TEMPLATES if not t.variant_of}
    assert bases - REACHABLE_GENERIC - REACHABLE_DEV == PAIR_TEMPLATES


@pytest.mark.parametrize("site", [None, SiteType.DEV], ids=["generic", "dev"])
def test_no_unknown_recommendation_gives_an_unconditional_instruction(
    site: SiteType | None,
) -> None:
    """Every text an ``UNKNOWN`` defect gets is conditional, and makes no promise."""
    advice = rendered(site)
    assert advice
    for recommendation in advice:
        for text in (recommendation.summary, recommendation.rationale or ""):
            assert unconditional_instructions(text) == [], (recommendation.target, text)
            assert find_outcome_language(text) == (), (recommendation.target, text)


@pytest.mark.parametrize("site", [None, SiteType.DEV], ids=["generic", "dev"])
def test_every_unknown_wording_says_whose_change_it_is_otherwise(
    site: SiteType | None,
) -> None:
    """A condition alone is not enough: the other case is named, never left implied."""
    for recommendation in rendered(site):
        assert any(hedge in recommendation.summary for hedge in HEDGES), recommendation.target


def test_every_check_with_a_conditional_wording_moved_its_version() -> None:
    """Session 7 changed what these checks produce, so none is still at version 1."""
    for template in TEMPLATES:
        if template.variant_of:
            assert check(template.check_id).version != "1", template.check_id


def test_the_dev_cover_image_wording_is_only_for_og_image() -> None:
    """Any other og: property with an UNKNOWN defect on DEV gets the wording for any site."""
    body = (
        f"<html lang='en'><head><link rel='canonical' href='{DEV_URL}'>"
        "<meta property='og:type' content='article'>"
        "<meta property='og:image' content='https://img.example/a.png'>"
        f"<meta property='og:url' content='{DEV_URL}'></head><body></body></html>"
    ).encode()
    receipt = receipt_for(body, DEV_URL)
    page = parse_page(receipt, body)
    defect = Finding(
        id="f-900",
        check_id="peri.og.core",
        check_version=check("peri.og.core").version,
        status=Status.OBSERVED,
        actor=Actor.UNKNOWN,
        subject_url=DEV_URL,
        summary="og:title is absent.",
        target="og:title",
        evidence=(Evidence(receipt_id="r-001", location="head", searched_for="og:title"),),
        defect=True,
    )

    (advice,) = recommendations_for(
        [defect], page=page, receipt=receipt, site=SiteType.DEV, new_id=_ids()
    )

    assert "cover_image" not in advice.summary
    assert advice.summary.startswith("If you control the page's Open Graph tags, add og:title")


def test_dev_wordings_name_dev_and_the_front_matter() -> None:
    """On DEV, the condition is what the evidence can show: the cover image, or DEV's own."""
    for recommendation in rendered(SiteType.DEV):
        assert "DEV" in recommendation.summary, recommendation.target
        assert "front matter" in recommendation.summary, recommendation.target


def test_an_author_defect_keeps_the_direct_wording() -> None:
    """An ``AUTHOR`` defect is the author's, so its recommendation stays an instruction."""
    advice = _peritext(GENERIC_PAGES[0], GENERIC_URL, SiteType.WORDPRESS)

    assert advice
    for recommendation in advice:
        assert recommendation.actor is Actor.AUTHOR
        assert unconditional_instructions(recommendation.summary), recommendation.target


def test_a_conditional_wording_keeps_the_base_templates_key() -> None:
    """The wording changes, the finding's key does not: history still matches it."""
    unknown = _peritext(GENERIC_PAGES[0], GENERIC_URL, None)
    author = _peritext(GENERIC_PAGES[0], GENERIC_URL, SiteType.WORDPRESS)

    assert [r.target for r in unknown] == [r.target for r in author]
    assert [r.key for r in unknown] == [r.key for r in author]
    assert [r.summary for r in unknown] != [r.summary for r in author]


def test_every_conditional_wording_names_a_base_of_its_own_check() -> None:
    """One wording per base and site type, and every reachable base has one for any site."""
    bases = {t.id: t for t in TEMPLATES if not t.variant_of}
    seen: set[tuple[str, SiteType | None]] = set()
    for template in TEMPLATES:
        if not template.variant_of:
            assert template.site_type is None, template.id
            continue
        assert bases[template.variant_of].check_id == template.check_id, template.id
        assert (template.variant_of, template.site_type) not in seen, template.id
        seen.add((template.variant_of, template.site_type))
    for base in REACHABLE_GENERIC | REACHABLE_DEV:
        assert (base, None) in seen, base
    for base in REACHABLE_DEV:
        assert (base, SiteType.DEV) in seen, base


def test_an_unknown_defect_with_no_conditional_wording_is_refused() -> None:
    """Fail closed: never fall back to an unconditional instruction."""
    with pytest.raises(KeyError, match=re.escape("epi.pair.canonical.set-copy-canonical")):
        template_for("epi.pair.canonical.set-copy-canonical", Actor.UNKNOWN, None)

    direct = template_for("epi.pair.canonical.set-copy-canonical", Actor.AUTHOR, None)
    assert direct.id == "epi.pair.canonical.set-copy-canonical"
