"""Run assembly: fetch, read, check, and gather everything into one validated Run.

:func:`audit` takes pages to audit, and original and copy pairs, and runs in
three steps:

1. **Pages.** Each page, single or in a pair, is fetched once (robots.txt,
   pacing, retries, the address screen; Phase 2). If Cernis saw it whole, it
   is parsed, snapshotted, and given the nine peritext checks, with a
   recommendation for each defect the author can act on. If not, each
   question the checks would have answered is ``NOT_DETERMINABLE``, with the
   reason and the receipts, and no check runs.
2. **Around each page.** For a page read whole, each canonical URL is
   fetched for ``epi.canonical.resolves``, the ``og:image`` for
   ``epi.og.image.resolves`` (without storing the image), the site's
   sitemap for ``epi.sitemap.listed`` (not on DEV; once per site per run),
   and each article-body link for ``epi.links.resolve`` (without storing
   bodies, within :class:`AuditLimits`). For every page whose robots.txt
   Cernis fetched, read whole or not, ``epi.robots.access`` reads that same
   robots.txt for ``*`` and each AI crawler.
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
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from cernis import __version__
from cernis.checks import links as links_check
from cernis.checks import robots_access as robots_check
from cernis.checks import sitemap_listed as sitemap_check
from cernis.checks.epitext import (
    FetchedPage,
    canonical_resolves,
    canonical_urls,
    og_image_resolves,
    og_image_shared,
    og_image_url,
    pair_canonical,
)
from cernis.checks.links import HostBudget, LinkLimits, links_resolve
from cernis.checks.outcomes import Readable, Unreadable, classify, not_determinable_findings
from cernis.checks.peritext import peritext_findings
from cernis.checks.recommend import (
    pair_recommendations,
    recommendations_for,
    resource_recommendations,
)
from cernis.checks.robots_access import robots_access
from cernis.checks.sitemap_listed import sitemap_listed
from cernis.fetch import Fetcher, FetchError, FetchResult, RobotsPolicy
from cernis.fetch.robots import robots_url_for
from cernis.model import ErrorKind, Finding, Receipt, Run, RunPair, RunSource, Snapshot
from cernis.parse import SitePrefix, SiteType, build_snapshot, effective_site, parse_page
from cernis.parse.extractors import longest_prefix, read_article
from cernis.parse.html import ParsedPage, parse_tree
from cernis.sitemaps import SitemapRead, discover_sitemaps
from cernis.urls import UrlMatch, compare_urls, normalize_url

__all__ = [
    "AuditLimits",
    "PairTarget",
    "RunFetches",
    "Target",
    "audit",
    "peritext_findings",
    "run_id_for",
]


@dataclass(frozen=True, kw_only=True)
class AuditLimits:
    """How much a run fetches around each page. Every limit is configurable.

    :param links: The link limits (per page, and per external host per run).
    :param sitemap_documents: The most sitemap documents read per site.
    :raises ValueError: If ``sitemap_documents`` is less than 1.
    """

    links: LinkLimits = field(default_factory=LinkLimits)
    sitemap_documents: int = 50

    def __post_init__(self) -> None:
        """Check the limits.

        :raises ValueError: If ``sitemap_documents`` is less than 1.
        """
        if self.sitemap_documents < 1:
            raise ValueError("AuditLimits: sitemap_documents must be at least 1")


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

    @property
    def fetcher(self) -> Fetcher:
        """The run's fetcher."""
        return self._fetcher

    def known(self, url: str) -> bool:
        """Tell whether the run already fetched a URL, so fetching it again costs nothing.

        :param url: The URL.
        :return: Whether a fetch of it is on record.
        """
        try:
            return str(httpx.URL(url)) in self._by_url
        except httpx.InvalidURL:
            return False

    def robots_policy(self, url: str) -> RobotsPolicy:
        """Return the robots.txt policy for a URL's origin, keeping its receipts.

        A ``FetchError`` for a URL that cannot be fetched at all propagates.

        :param url: The URL.
        :return: The policy (fetched once per origin per run).
        """
        policy, receipts = self._fetcher.robots_policy(url)
        for receipt in receipts:
            self.receipts.setdefault(receipt.id, receipt)
        return policy

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
    limits: AuditLimits | None = None,
    fetches: RunFetches | None = None,
    sources: Sequence[RunSource] = (),
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
    :param limits: The limits on fetches around each page; the defaults if
        ``None``.
    :param fetches: The run's fetches, when a URL source already made
        requests with ``fetcher`` (their receipts join the run); a new one if
        ``None``.
    :param sources: Where the URLs came from, recorded in the run.
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

    fetches = fetches or RunFetches(fetcher)
    limits = limits or AuditLimits()
    around = _Around(fetches=fetches, limits=limits, prefixes=prefixes)
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
        findings.extend(around.page(page, new_id))
    findings.extend(og_image_shared(list(pages.values()), new_id=new_id))

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
        sources=tuple(sources),
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
    tree, _ = parse_tree(outcome.body, outcome.receipt.header("content-type"))
    article = read_article(tree, page_url, target.site, prefixes)
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
    return FetchedPage(
        subject=subject, site=site, result=result, outcome=outcome, page=page, article=article
    )


class _Around:
    """The checks around each page, with what they share across the run.

    :param fetches: The run's fetches.
    :param limits: The limits.
    :param prefixes: Prefix rules, for a page's sitemap section.
    """

    def __init__(
        self, *, fetches: RunFetches, limits: AuditLimits, prefixes: Sequence[SitePrefix]
    ) -> None:
        self.fetches = fetches
        self.limits = limits
        self.prefixes = prefixes
        self.budget = HostBudget()
        self.sitemaps: dict[str, SitemapRead] = {}

    def page(self, page: FetchedPage, new_id: Callable[[], str]) -> list[Finding]:
        """Run every check around one page.

        :param page: The page.
        :param new_id: The run's finding id source.
        :return: The findings, in check order, with their recommendations.
        """
        found = _around_page(page, self.fetches, new_id)
        found += self._robots(page, new_id)
        if isinstance(page.outcome, Unreadable):
            # Every question around an unread page is open, with the page's reason.
            reason = page.outcome
            if page.site is not SiteType.DEV:
                found.append(
                    sitemap_check.not_read(
                        subject=page.subject, site=page.site, reason=reason, new_id=new_id
                    )
                )
            found.append(links_check.not_read(page, reason, new_id=new_id))
            return found
        if page.site is not SiteType.DEV:
            found += self._sitemap(page, new_id)
        if page.article is not None:
            links = links_resolve(
                page,
                page.article,
                lambda url: self.fetches.fetch(url, store_body=False),
                limits=self.limits.links,
                budget=self.budget,
                new_id=new_id,
                known=self.fetches.known,
            )
            found += links + resource_recommendations(links, new_id=new_id)
        return found

    def _robots(self, page: FetchedPage, new_id: Callable[[], str]) -> list[Finding]:
        """Run ``epi.robots.access`` if Cernis fetched the page's robots.txt.

        :param page: The page.
        :param new_id: The run's finding id source.
        :return: The findings; for a page whose robots.txt was never fetched
            (the address screen refused the host first), one NOT_DETERMINABLE
            finding per name with the page's reason.
        """
        url = page.base
        robots_url = robots_url_for(str(httpx.URL(url)))
        if not any(decision.robots_url == robots_url for decision in page.result.robots):
            assert isinstance(page.outcome, Unreadable)
            return robots_check.not_read(
                subject=page.subject, site=page.site, reason=page.outcome, new_id=new_id
            )
        policy = self.fetches.robots_policy(url)
        return robots_access(
            subject=page.subject, url=url, site=page.site, policy=policy, new_id=new_id
        )

    def _sitemap(self, page: FetchedPage, new_id: Callable[[], str]) -> list[Finding]:
        """Run ``epi.sitemap.listed``, reading each site's sitemaps once per run.

        A site is the ``[[site]]`` prefix covering the page, else its origin.

        :param page: The page, read whole.
        :param new_id: The run's finding id source.
        :return: The finding and any recommendation.
        """
        assert isinstance(page.outcome, Readable)
        url = page.base
        site_root = longest_prefix(url, self.prefixes)
        key = site_root or robots_url_for(url)
        read = self.sitemaps.get(key)
        if read is None:
            policy = self.fetches.robots_policy(url)
            read = discover_sitemaps(
                self.fetches.fetch,
                url,
                policy.sitemaps,
                policy.receipt_id,
                limit=self.fetches.fetcher.config.max_body_bytes,
                max_documents=self.limits.sitemap_documents,
                site_root=site_root,
            )
            self.sitemaps[key] = read
        return sitemap_listed(
            subject=page.subject,
            page_receipt=page.outcome.receipt,
            site=page.site,
            read=read,
            prefixes=self.prefixes,
            new_id=new_id,
            expected_absent=_expected_absent(page),
        )


def _expected_absent(page: FetchedPage) -> str | None:
    """Say why a page is expected to be left out of a sitemap, if it is.

    :param page: The page, read whole.
    :return: The reason (its one canonical names a different URL, or it
        declares ``noindex``), or ``None``.
    """
    assert page.page is not None
    assert isinstance(page.outcome, Readable)
    canonicals = canonical_urls(page)
    if len(canonicals) == 1:
        match = compare_urls(canonicals[0], page.base, redirects=(page.outcome.receipt,))
        if match.outcome is UrlMatch.DIFFERENT:
            return f"its canonical URL names another page ({canonicals[0]})"
    if _noindex(page.page, page.outcome.receipt):
        return "it declares noindex"
    return None


def _noindex(parsed: ParsedPage, receipt: Receipt) -> bool:
    """Tell whether a page declares ``noindex`` (or ``none``) for crawlers in general.

    :param parsed: The parsed page.
    :param receipt: Its receipt, for the ``X-Robots-Tag`` header.
    :return: Whether a ``robots`` meta tag or the header says so.
    """
    values = [
        tag.content or ""
        for tag in parsed.meta
        if tag.attribute == "name" and tag.key.strip().lower() == "robots"
    ]
    values.append(receipt.header("x-robots-tag") or "")
    for value in values:
        for token in value.lower().split(","):
            if token.strip() in ("noindex", "none"):
                return True
    return False


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
