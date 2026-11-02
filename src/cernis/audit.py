"""Run assembly: fetch, read, check, and gather everything into one validated Run.

:func:`audit` takes pages to audit, and original and copy pairs, and runs in
three steps:

1. **Pages.** Each page, single or in a pair, is fetched once (robots.txt,
   pacing, retries, the address screen; Phase 2). If Cernis saw it whole, it
   is parsed, snapshotted, and given the nine peritext checks, with a
   recommendation for each defect the author can act on. If not, each
   question the checks would have answered is ``NOT_DETERMINABLE``, with the
   reason and the receipts, and no check runs.
2. **Around each page read whole.** Each canonical URL is fetched for
   ``epi.canonical.resolves``, and the ``og:image`` for
   ``epi.og.image.resolves`` (without storing the image).
3. **Pairs.** ``epi.pair.canonical`` compares each copy's canonical with
   its original, and the original's with itself.

Within a run, each distinct URL is fetched once and its receipts reused
(:class:`RunFetches`): a canonical that is the page's own URL, or the URL a
page redirected to, costs no second request.

The :class:`~cernis.model.Run` it returns validated itself at construction
(every ``based_on`` resolves to an ``OBSERVED`` finding, keys are unique,
and every piece of evidence names a receipt in the run). A run that fails is
a bug in Cernis, so the error propagates; it is never caught and emitted.
"""

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import httpx

from cernis import __version__
from cernis.checks.epitext import (
    FetchedPage,
    canonical_resolves,
    canonical_urls,
    og_image_resolves,
    og_image_url,
    pair_canonical,
)
from cernis.checks.outcomes import Readable, classify, not_determinable_findings
from cernis.checks.peritext import peritext_findings
from cernis.checks.recommend import (
    pair_recommendations,
    recommendations_for,
    resource_recommendations,
)
from cernis.fetch import Fetcher, FetchError, FetchResult
from cernis.model import ErrorKind, Finding, Receipt, Run, RunPair, Snapshot
from cernis.parse import SitePrefix, SiteType, build_snapshot, effective_site, parse_page
from cernis.urls import normalize_url

__all__ = ["PairTarget", "RunFetches", "Target", "audit", "peritext_findings", "run_id_for"]


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


@dataclass(frozen=True, kw_only=True)
class PairTarget:
    """A declared original and copy to audit together.

    :param original: The original.
    :param copy: The copy, which should name the original as its canonical.
    """

    original: Target
    copy: Target


def run_id_for(started_at: datetime) -> str:
    """Name a run after the moment it started (DESIGN.md section 7).

    :param started_at: When the run started, in UTC.
    :return: The id, such as ``20261030T120000Z``.
    """
    return started_at.strftime("%Y%m%dT%H%M%SZ")


class RunFetches:
    """Fetch each distinct URL once per run, and keep every receipt.

    A fetch is reused for the same URL (as the fetcher requests it), and for
    the URL a successful fetch ended at after redirects, since a response
    from that URL is on record. A fetch made without its body is not reused
    for a request that needs the body.

    :param fetcher: The fetcher; one fetcher is one run.
    """

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher
        self._by_url: dict[str, FetchResult] = {}
        self.receipts: dict[str, Receipt] = {}

    def fetch(self, url: str, *, store_body: bool = True) -> FetchResult:
        """Fetch a URL, or return the run's earlier fetch of it.

        A ``FetchError`` from the fetcher (a URL it cannot fetch at all)
        propagates.

        :param url: The URL.
        :param store_body: ``False`` to keep only the receipts (for an image).
        :return: The fetch.
        """
        key = str(httpx.URL(url))
        known = self._by_url.get(key)
        if known is not None and (not store_body or known.body is not None or not _whole(known)):
            return known
        result = self._fetcher.fetch(url, store_body=store_body)
        for receipt in (*result.robots_receipts, *result.receipts):
            self.receipts.setdefault(receipt.id, receipt)
        self._by_url[result.requested_url] = result
        final = result.final
        if final is not None and final.final_url and _whole(result):
            self._by_url.setdefault(final.final_url, result)
        return result


def _whole(result: FetchResult) -> bool:
    """Tell whether a fetch got a successful response.

    :param result: The fetch.
    :return: Whether its last attempt answered 2xx with no error.
    """
    final = result.final
    return (
        final is not None
        and final.error_kind is ErrorKind.NONE
        and final.status_code is not None
        and 200 <= final.status_code <= 299
    )


def audit(
    targets: Sequence[Target],
    fetcher: Fetcher,
    *,
    now: Callable[[], datetime],
    prefixes: Sequence[SitePrefix] = (),
    pairs: Sequence[PairTarget] = (),
) -> Run:
    """Audit pages and pairs, and return the validated run.

    A page given more than once (after URL normalization), as a target or in
    pairs, is audited once, with the first site type given for it.

    :param targets: Single pages, with their declared site types.
    :param fetcher: The fetcher; one fetcher is one run.
    :param now: The current time, timezone-aware, in UTC.
    :param prefixes: Prefix rules from the pair map. A page's own site type
        wins over them; they win over host detection. They are matched
        against the URL that answered, after redirects.
    :param pairs: Original and copy pairs; both pages are audited, then the
        pair check runs.
    :return: The run.
    :raises ValueError: If there is nothing to audit. A
        :class:`~cernis.fetch.FetchError` for a page URL that cannot be
        fetched at all, and a :class:`~cernis.model.RunError` for a run that
        fails its own rules (a bug), propagate.
    """
    if not targets and not pairs:
        raise ValueError("audit needs at least one URL")
    started_at = now()
    counter = itertools.count(1)

    def new_id() -> str:
        return f"f-{next(counter):03d}"

    fetches = RunFetches(fetcher)
    snapshots: list[Snapshot] = []
    findings: list[Finding] = []
    pages: dict[str, FetchedPage] = {}

    wanted = [*targets, *(t for pair in pairs for t in (pair.original, pair.copy))]
    for target in wanted:
        key = normalize_url(target.url)
        if key in pages:
            continue
        pages[key] = _audit_page(target, fetches, prefixes, snapshots, findings, new_id)

    for page in pages.values():
        findings.extend(_around_page(page, fetches, new_id))

    run_pairs: list[RunPair] = []
    for pair in pairs:
        original = pages[normalize_url(pair.original.url)]
        copy = pages[normalize_url(pair.copy.url)]
        run_pair = RunPair(original=original.subject, copy=copy.subject)
        if run_pair in run_pairs:
            continue
        run_pairs.append(run_pair)
        found = pair_canonical(
            original, copy, redirects=tuple(fetches.receipts.values()), new_id=new_id
        )
        findings.extend(found)
        copy_canonicals = canonical_urls(copy)
        original_canonicals = canonical_urls(original)
        findings.extend(
            pair_recommendations(
                found,
                original_url=original.subject,
                copy_canonical=copy_canonicals[0] if copy_canonicals else None,
                original_canonical=original_canonicals[0] if original_canonicals else None,
                copy_on_dev=copy.site is SiteType.DEV,
                new_id=new_id,
            )
        )
    return Run(
        id=run_id_for(started_at),
        started_at=started_at,
        finished_at=now(),
        cernis_version=__version__,
        subjects=tuple(page.subject for page in pages.values()),
        receipts=tuple(fetches.receipts.values()),
        snapshots=tuple(snapshots),
        findings=tuple(findings),
        pairs=tuple(run_pairs),
    )


def _audit_page(
    target: Target,
    fetches: RunFetches,
    prefixes: Sequence[SitePrefix],
    snapshots: list[Snapshot],
    findings: list[Finding],
    new_id: Callable[[], str],
) -> FetchedPage:
    """Fetch one page and run the peritext checks if Cernis saw it whole.

    :param target: The page.
    :param fetches: The run's fetches.
    :param prefixes: Prefix rules.
    :param snapshots: Where to add its snapshot.
    :param findings: Where to add its findings.
    :param new_id: The run's finding id source.
    :return: What was fetched and read.
    """
    result = fetches.fetch(target.url)
    subject = result.requested_url
    outcome = classify(result, effective_site(subject, target.site, prefixes))
    if not isinstance(outcome, Readable):
        findings.extend(not_determinable_findings(outcome, subject_url=subject, new_id=new_id))
        site = effective_site(subject, target.site, prefixes)
        return FetchedPage(subject=subject, site=site, result=result, outcome=outcome, page=None)
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
    return FetchedPage(subject=subject, site=site, result=result, outcome=outcome, page=page)


def _around_page(
    page: FetchedPage, fetches: RunFetches, new_id: Callable[[], str]
) -> list[Finding]:
    """Run the resource checks for a page read whole: its canonicals and og:image.

    A URL that cannot be fetched at all (an ``href`` the fetcher refuses
    outright) gets no finding here; the peritext checks already report it.

    :param page: The page.
    :param fetches: The run's fetches.
    :param new_id: The run's finding id source.
    :return: The findings and their recommendations.
    """
    found: list[Finding] = []
    for url in canonical_urls(page):
        try:
            result = fetches.fetch(url)
        except FetchError:
            continue
        found.append(canonical_resolves(page, url, result, new_id=new_id))
    image = og_image_url(page)
    if image is not None:
        try:
            image_result = fetches.fetch(image, store_body=False)
        except FetchError:
            pass
        else:
            found.append(og_image_resolves(page, image, image_result, new_id=new_id))
    return found + resource_recommendations(found, new_id=new_id)
