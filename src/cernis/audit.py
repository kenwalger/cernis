"""Run assembly: fetch, read, check, and gather everything into one validated Run.

:func:`audit` takes the URLs to audit, each with its declared site type, and
for each one:

1. fetches it (robots.txt, pacing, retries, the address screen; Phase 2);
2. decides whether Cernis saw the page whole (:func:`cernis.checks.outcomes.classify`);
3. if it did, parses it, builds its snapshot, runs the nine peritext checks,
   and makes a recommendation for each defect the author can act on;
4. if it did not, records each question the checks would have answered as
   ``NOT_DETERMINABLE``, with the reason and the receipts, and runs no check.

The :class:`~cernis.model.Run` it returns validated itself at construction
(every ``based_on`` resolves to an ``OBSERVED`` finding, keys are unique,
and every piece of evidence names a receipt in the run). A run that fails is
a bug in Cernis, so the error propagates; it is never caught and emitted.
"""

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from cernis import __version__
from cernis.checks.outcomes import Readable, classify, not_determinable_findings
from cernis.checks.peritext import peritext_findings
from cernis.checks.recommend import recommendations_for
from cernis.fetch import Fetcher
from cernis.model import Finding, Receipt, Run, Snapshot
from cernis.parse import SitePrefix, SiteType, build_snapshot, effective_site, parse_page
from cernis.urls import normalize_url

__all__ = ["Target", "audit", "peritext_findings", "run_id_for"]


@dataclass(frozen=True, kw_only=True)
class Target:
    """One URL to audit.

    :param url: The URL.
    :param site: Its declared site type (from ``--site-type`` or its own
        entry in the pair map), or ``None`` to use prefix rules and host
        detection.
    """

    url: str
    site: SiteType | None = None


def run_id_for(started_at: datetime) -> str:
    """Name a run after the moment it started (DESIGN.md section 7).

    :param started_at: When the run started, in UTC.
    :return: The id, such as ``20261030T120000Z``.
    """
    return started_at.strftime("%Y%m%dT%H%M%SZ")


def audit(
    targets: Sequence[Target],
    fetcher: Fetcher,
    *,
    now: Callable[[], datetime],
    prefixes: Sequence[SitePrefix] = (),
) -> Run:
    """Audit each URL once, in order, and return the validated run.

    A URL given twice (after URL normalization) is audited once.

    :param targets: The URLs, with their declared site types.
    :param fetcher: The fetcher; one fetcher is one run.
    :param now: The current time, timezone-aware, in UTC.
    :param prefixes: Prefix rules from the pair map. A target's own site type
        wins over them; they win over host detection. They are matched
        against the URL that answered, after redirects.
    :return: The run.
    :raises ValueError: If no URL is given. A
        :class:`~cernis.fetch.FetchError` for a URL that cannot be fetched at
        all, and a :class:`~cernis.model.RunError` for a run that fails its
        own rules (a bug), propagate.
    """
    if not targets:
        raise ValueError("audit needs at least one URL")
    started_at = now()
    counter = itertools.count(1)

    def new_id() -> str:
        return f"f-{next(counter):03d}"

    receipts: dict[str, Receipt] = {}
    snapshots: list[Snapshot] = []
    findings: list[Finding] = []
    subjects: list[str] = []
    seen: set[str] = set()
    for target in targets:
        key = normalize_url(target.url)
        if key in seen:
            continue
        seen.add(key)
        result = fetcher.fetch(target.url)
        subject = result.requested_url
        subjects.append(subject)
        for receipt in (*result.robots_receipts, *result.receipts):
            receipts.setdefault(receipt.id, receipt)
        outcome = classify(result, effective_site(subject, target.site, prefixes))
        if not isinstance(outcome, Readable):
            findings.extend(not_determinable_findings(outcome, subject_url=subject, new_id=new_id))
            continue
        page_url = outcome.receipt.final_url or subject
        site = effective_site(page_url, target.site, prefixes)
        page = parse_page(outcome.receipt, outcome.body)
        snapshots.append(
            build_snapshot(outcome.receipt, outcome.body, site=target.site, prefixes=prefixes)
        )
        observed = peritext_findings(
            page, outcome.receipt, subject_url=subject, site=site, new_id=new_id
        )
        findings.extend(observed)
        findings.extend(
            recommendations_for(observed, page=page, receipt=outcome.receipt, new_id=new_id)
        )
    return Run(
        id=run_id_for(started_at),
        started_at=started_at,
        finished_at=now(),
        cernis_version=__version__,
        subjects=tuple(subjects),
        receipts=tuple(receipts.values()),
        snapshots=tuple(snapshots),
        findings=tuple(findings),
    )
