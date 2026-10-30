"""Recommendations for the defects the peritext checks find (DESIGN.md sections 2 and 3).

Each recommendation comes from a template in
:data:`cernis.checks.recommendations.TEMPLATES`, so the no-promise test
covers its text. It rests on the ``OBSERVED`` defect it addresses
(``based_on``), says what to change as an action, and gives a rationale
citing a standard or the page's own evidence, never an outcome.

A recommendation is made only for a defect the author can act on, or might
(``AUTHOR`` or ``UNKNOWN``). A defect only the platform can change (on DEV,
``og:url`` against the author's canonical) is reported as observed, with no
recommendation: telling the author to change what they cannot would be
noise.

A recommendation's ``target`` is the template id, then ``:`` and what it is
about (the observed finding's target, or ``canonical N``), so every
recommendation in a run has its own key.
"""

from collections.abc import Callable
from urllib.parse import urljoin

from cernis.checks.peritext import canonical_problem
from cernis.checks.recommendations import TEMPLATES_BY_ID
from cernis.checks.registry import check
from cernis.model import Actor, Finding, Receipt, Status
from cernis.parse.html import ParsedPage

NewId = Callable[[], str]
"""Returns the next finding id in the run."""

_ACTIONABLE = frozenset({Actor.AUTHOR, Actor.UNKNOWN})
_ABSOLUTE_TEMPLATES = {
    "relative": "peri.canonical.absolute.make-absolute",
    "no href": "peri.canonical.absolute.add-href",
    "not http": "peri.canonical.absolute.fix-url",
}


def _recommend(
    template_id: str,
    finding: Finding,
    about: str,
    new_id: NewId,
    **values: str,
) -> Finding:
    """Fill a template into a recommendation resting on one observed defect.

    :param template_id: The template.
    :param finding: The defect it rests on.
    :param about: What it is about, for the target (may be empty).
    :param new_id: The run's finding id source.
    :param **values: The template's placeholders. Page content is passed
        here, never used as a format string.
    :return: The recommendation.
    """
    template = TEMPLATES_BY_ID[template_id]
    return Finding(
        id=new_id(),
        check_id=template.check_id,
        check_version=check(template.check_id).version,
        status=Status.RECOMMENDATION,
        actor=finding.actor,
        subject_url=finding.subject_url,
        summary=template.action.format(**values),
        target=f"{template.id}:{about}" if about else template.id,
        rationale=template.rationale.format(**values),
        based_on=(finding.id,),
    )


def recommendations_for(
    findings: list[Finding],
    *,
    page: ParsedPage,
    receipt: Receipt,
    new_id: NewId,
) -> list[Finding]:
    """Recommend a change for each defect the author can act on.

    :param findings: The page's observed findings.
    :param page: The parsed page, for the values the templates name.
    :param receipt: The page's receipt, for resolving relative URLs.
    :param new_id: The run's finding id source.
    :return: The recommendations, in the order of the defects they address.
    """
    base = receipt.final_url or receipt.requested_url
    advice: list[Finding] = []
    for finding in findings:
        if not (
            finding.status is Status.OBSERVED and finding.defect and finding.actor in _ACTIONABLE
        ):
            continue
        if finding.check_id == "peri.canonical.single":
            hrefs = [c.href for c in page.canonicals if c.href is not None]
            advice.append(
                _recommend(
                    "peri.canonical.single.keep-one",
                    finding,
                    "",
                    new_id,
                    count=str(len(page.canonicals)),
                    urls=", ".join(hrefs),
                )
            )
        elif finding.check_id == "peri.canonical.absolute":
            for position, link in enumerate(page.canonicals, start=1):
                problem = canonical_problem(link.href)
                if problem is None:
                    continue
                href = link.href or ""
                advice.append(
                    _recommend(
                        _ABSOLUTE_TEMPLATES[problem],
                        finding,
                        f"canonical {position}",
                        new_id,
                        href=href,
                        resolved=urljoin(base, href.strip()) if problem == "relative" else "",
                    )
                )
        elif finding.check_id == "peri.og.url_matches_canonical":
            og = [e.observed for e in finding.evidence if e.location.endswith('og:url"] content')]
            named = [e.observed for e in finding.evidence if "canonical" in e.location]
            advice.append(
                _recommend(
                    "peri.og.url_matches_canonical.align",
                    finding,
                    "",
                    new_id,
                    og_url=og[0] or "" if og else "",
                    canonical=named[0] or "" if named else "",
                )
            )
        elif finding.check_id == "peri.jsonld.parses":
            block_number = finding.target.removeprefix("block ")
            block = page.json_ld[int(block_number) - 1]
            advice.append(
                _recommend(
                    "peri.jsonld.parses.fix-json",
                    finding,
                    finding.target,
                    new_id,
                    number=block_number,
                    error=block.error or "",
                )
            )
    return advice
