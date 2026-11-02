"""``epi.links.resolve``: whether the links in the article body resolve.

Only the article body is read (the extractor's body element), never
navigation, sidebars, or footers. Each distinct link is fetched once per run,
without storing its body, through the normal fetcher (robots.txt, the
address screen, pacing, retries).

- **Skipped by design**: ``mailto:``, ``tel:``, ``javascript:``, any other
  scheme that is not http(s), fragment-only links (``#notes``), empty
  ``href`` values, and URLs the fetcher never fetches (``not fetchable``:
  user information, or a URL that does not parse). They are counted in one
  fact (target ``skipped links``), never dropped silently.
- **Deduplicated**: by the URL as requested, without its fragment.
- **Limits** (:class:`LinkLimits`, configurable): at most ``per_page`` links
  per page, in document order, and at most ``per_external_host`` links to
  any one host other than the page's own, per run. The host budget is
  charged once per distinct URL (a link the run already fetched costs
  nothing), and also for each external host a link redirected to. Links
  left unchecked by a limit get one ``NOT_DETERMINABLE`` finding per page
  (target ``unchecked links``, ``LIMIT_REACHED``) that says how many and why.
- **Each link checked** is one finding, the URL being the ``target``: its
  status, and a redirect as a fact naming the final URL. A defect only for
  404 or 410. 401 and 403 are ``ACCESS_DENIED``, 429 ``RATE_LIMITED``,
  robots.txt ``DISALLOWED_BY_ROBOTS``, a non-public address
  ``ADDRESS_REFUSED``, and a failure or 5xx ``FETCH_FAILED``.
- **No article body**: with the generic extractor, which finds none by
  design, ``NOT_DETERMINABLE`` (``REQUIRES_EXTERNAL_DATA``: a site type
  with an article extractor would answer it); when an extractor found no
  body or several, ``AMBIGUOUS``. An unread page gets one
  ``NOT_DETERMINABLE`` finding with the page's own reason code
  (:func:`not_read`).

Actors follow the page: ``AUTHOR`` on DEV, WordPress, and owned sites (the
links are the author's text), ``UNKNOWN`` otherwise.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin

import httpx

from cernis.checks.epitext import (
    FetchedPage,
    NewId,
    chain_from,
    epi_actor,
    unanswered,
)
from cernis.checks.outcomes import Unreadable
from cernis.checks.registry import check
from cernis.fetch import FetchError, FetchResult
from cernis.fetch.client import url_problem
from cernis.model import Evidence, Finding, ReasonCode, Status
from cernis.parse.extractors import Article
from cernis.urls import is_absolute_http_url

CHECK_ID = "epi.links.resolve"

SKIPPED_SCHEMES: tuple[str, ...] = ("mailto", "tel", "javascript")
"""Schemes named in the skipped-links fact; any other non-http(s) scheme is "other"."""


@dataclass(frozen=True, kw_only=True)
class LinkLimits:
    """How many links Cernis checks.

    :param per_page: The most links checked on one page.
    :param per_external_host: The most links checked to any one host other
        than the page's own, across the run.
    :raises ValueError: If a limit is negative.
    """

    per_page: int = 100
    per_external_host: int = 5

    def __post_init__(self) -> None:
        """Check the limits.

        :raises ValueError: If a limit is negative.
        """
        if self.per_page < 0 or self.per_external_host < 0:
            raise ValueError("LinkLimits: limits must not be negative")


@dataclass
class HostBudget:
    """Links checked per external host so far in the run.

    :param counts: Links checked, by lowercase host.
    """

    counts: dict[str, int] = field(default_factory=dict)

    def take(self, host: str, limit: int) -> bool:
        """Spend one link for a host, if the host has any left.

        :param host: The host, lowercase.
        :param limit: The per-host limit.
        :return: Whether the link may be checked.
        """
        used = self.counts.get(host, 0)
        if used >= limit:
            return False
        self.counts[host] = used + 1
        return True

    def spend(self, host: str) -> None:
        """Count a request already made to a host (a redirect's destination).

        :param host: The host, lowercase.
        """
        self.counts[host] = self.counts.get(host, 0) + 1


@dataclass(frozen=True, kw_only=True)
class BodyLinks:
    """An article body's links, sorted into what Cernis checks and what it skips.

    :param urls: The distinct http(s) URLs to check, in document order.
    :param skipped: How many links were skipped by design, by kind
        (``mailto:``, ``fragment-only``, ...).
    :param total: How many links the body has.
    """

    urls: tuple[str, ...]
    skipped: dict[str, int]
    total: int


def sort_links(article: Article, base: str) -> BodyLinks:
    """Resolve, filter, and deduplicate an article body's links.

    :param article: The article body.
    :param base: The page's URL, for relative links.
    :return: The links to check and the ones skipped.
    """
    urls: list[str] = []
    seen: set[str] = set()
    skipped: dict[str, int] = {}
    for link in article.links:
        href = link.href.strip()
        kind = None
        if not href:
            kind = "empty"
        elif href.startswith("#"):
            kind = "fragment-only"
        else:
            scheme = href.split(":", 1)[0].lower() if ":" in href.split("/", 1)[0] else ""
            if scheme in SKIPPED_SCHEMES:
                kind = f"{scheme}:"
            elif scheme and scheme not in ("http", "https"):
                kind = "other scheme"
        if kind is None:
            try:
                resolved = urldefrag(urljoin(base, href))[0]
            except ValueError:
                resolved = ""
            if not is_absolute_http_url(resolved):
                kind = "not a URL"
            elif url_problem(resolved) is not None:
                kind = "not fetchable"
            else:
                try:
                    key = str(httpx.URL(resolved))
                except httpx.InvalidURL:
                    kind = "not a URL"
                else:
                    if key not in seen:
                        seen.add(key)
                        urls.append(resolved)
                    continue
        skipped[kind] = skipped.get(kind, 0) + 1
    return BodyLinks(urls=tuple(urls), skipped=skipped, total=len(article.links))


def _host(url: str) -> str:
    """Return a URL's host, lowercase.

    :param url: An absolute URL.
    :return: The host.
    """
    return (httpx.URL(url).host or "").lower()


def _non_liquet(
    page: FetchedPage,
    *,
    new_id: NewId,
    target: str,
    question: str,
    why: str,
    code: ReasonCode,
    evidence: tuple[Evidence, ...] = (),
    would_require: str | None = None,
) -> Finding:
    """Build a NOT_DETERMINABLE finding.

    :param page: The page.
    :param new_id: The run's finding id source.
    :param target: The target.
    :param question: What could not be answered.
    :param why: Why, in a clause.
    :param code: The reason code.
    :param evidence: Evidence of the attempt.
    :param would_require: For a no-attempt code, what would answer it.
    :return: The finding.
    """
    return Finding(
        id=new_id(),
        check_id=CHECK_ID,
        check_version=check(CHECK_ID).version,
        status=Status.NOT_DETERMINABLE,
        actor=epi_actor(page.site, CHECK_ID),
        subject_url=page.subject,
        summary=f"{question} is not determinable: {why}.",
        target=target,
        evidence=evidence,
        reason_code=code,
        question=question,
        would_require=would_require,
    )


def _observed(
    page: FetchedPage,
    *,
    new_id: NewId,
    target: str,
    summary: str,
    evidence: list[Evidence],
    defect: bool = False,
) -> Finding:
    """Build an OBSERVED finding.

    :param page: The page.
    :param new_id: The run's finding id source.
    :param target: The target.
    :param summary: One sentence.
    :param evidence: The evidence.
    :param defect: Whether the defect condition holds.
    :return: The finding.
    """
    return Finding(
        id=new_id(),
        check_id=CHECK_ID,
        check_version=check(CHECK_ID).version,
        status=Status.OBSERVED,
        actor=epi_actor(page.site, CHECK_ID),
        subject_url=page.subject,
        summary=summary,
        target=target,
        evidence=tuple(evidence),
        defect=defect,
    )


def not_read(page: FetchedPage, reason: Unreadable, *, new_id: NewId) -> Finding:
    """Say that an unread page's link question is not determinable.

    :param page: The page, not read whole.
    :param reason: Why it was not read.
    :param new_id: The run's finding id source.
    :return: The finding, with the page's reason code and evidence.
    """
    return _non_liquet(
        page,
        new_id=new_id,
        target="",
        question="Whether the article body's links resolve",
        why=f"the page was not read ({reason.why})",
        code=reason.reason_code,
        evidence=reason.evidence,
    )


def link_finding(page: FetchedPage, url: str, result: FetchResult, *, new_id: NewId) -> Finding:
    """Report what one link answered.

    :param page: The page the link is on.
    :param url: The link, resolved, without its fragment.
    :param result: Its fetch.
    :param new_id: The run's finding id source.
    :return: The finding.
    """
    reason = unanswered(result, epi_actor(page.site, CHECK_ID))
    if reason is not None:
        return _non_liquet(
            page,
            new_id=new_id,
            target=url,
            question=f"Whether the link {url} resolves",
            why=reason.why,
            code=reason.reason_code,
            evidence=reason.evidence,
        )
    final = result.final
    assert final is not None
    status = final.status_code
    evidence = [Evidence(receipt_id=final.id, location="HTTP status", observed=str(status))]
    chain = chain_from(url, final)
    if chain:
        hops = len(chain)
        evidence.append(
            Evidence(
                receipt_id=final.id,
                location="redirect chain",
                observed=" -> ".join((*chain, final.final_url or "")),
            )
        )
        summary = (
            f"The link {url} redirects ({hops} {'hop' if hops == 1 else 'hops'}) to "
            f"{final.final_url}, which answers {status}."
        )
    else:
        summary = f"The link {url} answers {status}."
    gone = status in (404, 410)
    if gone:
        summary = summary.removesuffix(".") + ", so it leads to no page."
    return _observed(
        page, new_id=new_id, target=url, summary=summary, evidence=evidence, defect=gone
    )


def links_resolve(
    page: FetchedPage,
    article: Article,
    fetch: Callable[[str], FetchResult],
    *,
    limits: LinkLimits,
    budget: HostBudget,
    new_id: NewId,
    known: Callable[[str], bool] = lambda url: False,
) -> list[Finding]:
    """Check the links in one page's article body.

    :param page: The page, read whole.
    :param article: Its article body, as the extractor found it.
    :param fetch: Fetches a URL for the run without storing its body.
    :param limits: The limits.
    :param budget: Links checked per external host so far in the run.
    :param new_id: The run's finding id source.
    :param known: Whether the run already fetched a URL, so checking it
        again makes no request and costs no host budget.
    :return: The findings: one per link checked, then the skipped-links
        fact and the unchecked-links finding when there are any.
    """
    assert page.page is not None
    receipt_id = page.page.receipt_id
    question = "Whether the article body's links resolve"
    if not article.found:
        if not article.extractor.selectors:
            return [
                _non_liquet(
                    page,
                    new_id=new_id,
                    target="",
                    question=question,
                    why=(
                        f"the {article.extractor.id} extractor finds no article body, so the "
                        "article's links cannot be told from the page's navigation"
                    ),
                    code=ReasonCode.REQUIRES_EXTERNAL_DATA,
                    would_require=(
                        "a site type whose extractor finds the article body (dev or wordpress)"
                    ),
                )
            ]
        return [
            _non_liquet(
                page,
                new_id=new_id,
                target="",
                question=question,
                why=article.problem or "no article body was found",
                code=ReasonCode.AMBIGUOUS,
                evidence=(
                    Evidence(
                        receipt_id=receipt_id,
                        location="article body",
                        observed=article.problem or "no article body",
                    ),
                ),
            )
        ]
    sorted_links = sort_links(article, page.base)
    findings: list[Finding] = []
    own_host = _host(page.base)
    over_page: list[str] = []
    over_host: dict[str, list[str]] = {}
    checked = 0
    for url in sorted_links.urls:
        if checked >= limits.per_page:
            over_page.append(url)
            continue
        host = _host(url)
        fresh = not known(url)
        if fresh and host != own_host and not budget.take(host, limits.per_external_host):
            over_host.setdefault(host, []).append(url)
            continue
        try:
            result = fetch(url)
        except FetchError:
            sorted_links.skipped["not fetchable"] = sorted_links.skipped.get("not fetchable", 0) + 1
            continue
        if fresh:
            final = result.final
            hops = (*final.redirect_chain[1:], final.final_url or "") if final else ()
            for hop_host in {_host(hop) for hop in hops if hop} - {host, own_host}:
                budget.spend(hop_host)
        checked += 1
        findings.append(link_finding(page, url, result, new_id=new_id))
    if not sorted_links.urls and not sorted_links.skipped:
        findings.append(
            _observed(
                page,
                new_id=new_id,
                target="",
                summary="The article body has no links.",
                evidence=[
                    Evidence(
                        receipt_id=receipt_id,
                        location="article body",
                        searched_for="an <a href> element",
                    )
                ],
            )
        )
    if sorted_links.skipped:
        kinds = ", ".join(f"{count} {kind}" for kind, count in sorted(sorted_links.skipped.items()))
        count = sum(sorted_links.skipped.values())
        findings.append(
            _observed(
                page,
                new_id=new_id,
                target="skipped links",
                summary=(
                    f"{count} of the article body's {sorted_links.total} links "
                    f"{'is' if count == 1 else 'are'} not checked, by design: {kinds}."
                ),
                evidence=[
                    Evidence(receipt_id=receipt_id, location="article body links", observed=kinds)
                ],
            )
        )
    unchecked = len(over_page) + sum(len(urls) for urls in over_host.values())
    if unchecked:
        reasons = []
        if over_page:
            reasons.append(f"{len(over_page)} past the limit of {limits.per_page} links per page")
        if over_host:
            hosts = ", ".join(sorted(over_host))
            count = sum(len(urls) for urls in over_host.values())
            reasons.append(
                f"{count} past the limit of {limits.per_external_host} links per external "
                f"host per run ({hosts})"
            )
        left = [*over_page, *(url for urls in over_host.values() for url in urls)]
        findings.append(
            _non_liquet(
                page,
                new_id=new_id,
                target="unchecked links",
                question=f"Whether {unchecked} of the article body's links resolve",
                why=f"Cernis did not fetch them: {'; '.join(reasons)}",
                code=ReasonCode.LIMIT_REACHED,
                evidence=(
                    Evidence(
                        receipt_id=receipt_id,
                        location="article body links not checked",
                        observed=" ".join(left),
                    ),
                ),
            )
        )
    return findings
