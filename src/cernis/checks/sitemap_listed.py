"""``epi.sitemap.listed``: whether the site's sitemap lists the page.

One finding per page (empty ``target``), on every site but DEV, whose
sitemaps are the platform's and list every article (the check is skipped
there). The sitemap is found and read by :mod:`cernis.sitemaps`, once per
site per run.

- **Listed**: a fact, naming the sitemap and, when the ``<loc>`` is not
  identical to the page's URL, each normalization that mattered (the shared
  URL comparison, with the page's own redirect as evidence).
- **No sitemap found**: a fact, naming every place searched. If a place
  could not be read (robots.txt disallows it, it failed, or it answered
  5xx, 429, 401, or 403), the question is ``NOT_DETERMINABLE`` instead.
- **Not listed**: a **defect** only when the sitemap was read completely
  and lists other pages in the same section: under the page's ``[[site]]``
  prefix if one covers it, else under the page's parent path (the URL up to
  its last ``/``). A sitemap that lists nothing in the section is a fact. A
  read that was not complete (a document unread, or a limit reached) is
  ``NOT_DETERMINABLE``, since the page could be in what was not read; so is
  an omission when a Google News sitemap was read (it lists only recent
  articles). A page that is expected to be left out (its canonical names
  another URL, or it declares ``noindex``) is a fact, never a defect.
- **Matching** follows the shared URL comparison: a ``<loc>`` matches when
  it is equivalent to the page's URL, to the URL it answered at, or to a
  URL its redirect chain passed through.
- **Unread pages** get one ``NOT_DETERMINABLE`` finding with the page's own
  reason code (:func:`not_read`).

Actors: ``AUTHOR`` on WordPress and owned sites, ``UNKNOWN`` otherwise.
"""

from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

from cernis.checks.epitext import NewId, epi_actor
from cernis.checks.outcomes import Unreadable
from cernis.checks.recommend import sitemap_recommendation
from cernis.checks.registry import check
from cernis.model import Evidence, Finding, ReasonCode, Receipt, Status
from cernis.parse.extractors import SitePrefix, SiteType, longest_prefix, under_prefix
from cernis.sitemaps import SitemapRead
from cernis.urls import UrlMatch, compare_urls, normalize_url

CHECK_ID = "epi.sitemap.listed"


def section_of(url: str, prefixes: Sequence[SitePrefix]) -> str:
    """Name the section of a site a page is in, for the defect rule.

    :param url: The page's URL.
    :param prefixes: Prefix rules from the pair map.
    :return: The longest ``[[site]]`` prefix covering the URL, else the URL
        up to the last ``/`` of its path (``https://h/blog/a/post`` gives
        ``https://h/blog/a/``), normalized.
    """
    best = longest_prefix(url, prefixes)
    if best is not None:
        return best
    parts = urlsplit(normalize_url(url))
    parent = parts.path.rstrip("/").rsplit("/", 1)[0] + "/"
    return urlunsplit((parts.scheme, parts.netloc, parent, "", ""))


def _finding(
    *,
    new_id: NewId,
    subject: str,
    site: SiteType | None,
    summary: str,
    evidence: Sequence[Evidence],
    defect: bool = False,
) -> Finding:
    """Build an OBSERVED finding.

    :param new_id: The run's finding id source.
    :param subject: The audited URL.
    :param site: The page's site type.
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
        actor=epi_actor(site, CHECK_ID),
        subject_url=subject,
        summary=summary,
        evidence=tuple(evidence),
        defect=defect,
    )


def _non_liquet(
    *,
    new_id: NewId,
    subject: str,
    site: SiteType | None,
    why: str,
    code: ReasonCode,
    evidence: Sequence[Evidence],
) -> Finding:
    """Build a NOT_DETERMINABLE finding.

    :param new_id: The run's finding id source.
    :param subject: The audited URL.
    :param site: The page's site type.
    :param why: Why, in a clause.
    :param code: The reason code.
    :param evidence: Evidence of what was read.
    :return: The finding.
    """
    question = "Whether the site's sitemap lists the page"
    return Finding(
        id=new_id(),
        check_id=CHECK_ID,
        check_version=check(CHECK_ID).version,
        status=Status.NOT_DETERMINABLE,
        actor=epi_actor(site, CHECK_ID),
        subject_url=subject,
        summary=f"{question} is not determinable: {why}.",
        evidence=tuple(evidence),
        reason_code=code,
        question=question,
    )


def not_read(*, subject: str, site: SiteType | None, reason: Unreadable, new_id: NewId) -> Finding:
    """Say that an unread page's sitemap question is not determinable.

    :param subject: The audited URL.
    :param site: The page's site type.
    :param reason: Why the page was not read.
    :param new_id: The run's finding id source.
    :return: The finding, with the page's reason code and evidence.
    """
    return _non_liquet(
        new_id=new_id,
        subject=subject,
        site=site,
        why=f"the page was not read ({reason.why})",
        code=reason.reason_code,
        evidence=reason.evidence,
    )


def _searched(read: SitemapRead, page_url: str) -> list[Evidence]:
    """Record each document read and each place searched.

    :param read: The sitemap read.
    :param page_url: The page's URL, for the search.
    :return: The evidence, one per document (and one for robots.txt).
    """
    evidence: list[Evidence] = []
    if read.robots_receipt_id is not None:
        evidence.append(
            Evidence(
                receipt_id=read.robots_receipt_id,
                location="robots.txt Sitemap lines",
                observed=", ".join(read.robots_sitemaps),
            )
            if read.robots_sitemaps
            else Evidence(
                receipt_id=read.robots_receipt_id,
                location="robots.txt",
                searched_for="a Sitemap: line",
            )
        )
    for doc in read.documents:
        if doc.kind == "urlset":
            evidence.append(
                Evidence(
                    receipt_id=doc.receipt_id,
                    location=doc.url,
                    searched_for=f"a <loc> equivalent to {page_url}",
                )
            )
        else:
            observed = "sitemap index" if doc.kind == "sitemapindex" else f"answered {doc.status}"
            if doc.unreadable is not None:
                observed = doc.unreadable.why
            evidence.append(
                Evidence(receipt_id=doc.receipt_id, location=doc.url, observed=observed)
            )
    first = read.documents[0].receipt_id if read.documents else read.robots_receipt_id
    if first is not None and read.offsite_children:
        evidence.append(
            Evidence(
                receipt_id=first,
                location="sitemap index children on other hosts, not followed",
                observed=" ".join(read.offsite_children),
            )
        )
    if first is not None and read.unusable_locs:
        evidence.append(
            Evidence(
                receipt_id=first,
                location="<loc> values that are not fetchable URLs, not used",
                observed=str(read.unusable_locs),
            )
        )
    return evidence


def sitemap_listed(
    *,
    subject: str,
    page_receipt: Receipt,
    site: SiteType | None,
    read: SitemapRead,
    prefixes: Sequence[SitePrefix],
    new_id: NewId,
    expected_absent: str | None = None,
) -> list[Finding]:
    """Report whether the sitemap lists one page.

    :param subject: The audited URL.
    :param page_receipt: The page's receipt (its redirect counts as equivalence).
    :param site: The page's site type, for the actor.
    :param read: The site's sitemap read.
    :param prefixes: Prefix rules, for the page's section.
    :param new_id: The run's finding id source.
    :param expected_absent: Why the page is expected to be left out of a
        sitemap (its canonical names another URL, or it declares
        ``noindex``), or ``None``; an omission is then a fact.
    :return: The finding, and a recommendation for an author-actionable defect.
    """
    page_url = page_receipt.final_url or subject
    keys = {normalize_url(url) for url in (subject, page_url, *page_receipt.redirect_chain)}
    for entry in read.entries:
        if entry.key not in keys:
            continue
        comparison = compare_urls(entry.loc, subject, redirects=(page_receipt,))
        if comparison.outcome is UrlMatch.IDENTICAL:
            how = ""
        else:
            reasons = ", ".join(comparison.reasons) or "redirect"
            if comparison.receipt_id is not None:
                reasons += f", receipt {comparison.receipt_id}"
            how = f" as {entry.loc}, which is equivalent ({reasons})"
        found = _finding(
            new_id=new_id,
            subject=subject,
            site=site,
            summary=f"The sitemap {entry.sitemap_url} lists the page{how}.",
            evidence=[
                Evidence(
                    receipt_id=entry.receipt_id,
                    location=f"{entry.sitemap_url} <loc>",
                    observed=entry.loc,
                )
            ],
        )
        return [found]
    evidence = _searched(read, page_url)
    unread = [doc for doc in read.documents if doc.unreadable is not None]
    if not read.found:
        if unread:
            first = unread[0].unreadable
            assert first is not None
            unknown = _non_liquet(
                new_id=new_id,
                subject=subject,
                site=site,
                why=f"no sitemap was read, and {first.why}",
                code=first.reason_code,
                evidence=evidence,
            )
            return [unknown]
        tried = "; ".join(f"{doc.url} (answered {doc.status})" for doc in read.documents)
        absent = _finding(
            new_id=new_id,
            subject=subject,
            site=site,
            summary=f"No sitemap was found: Cernis looked in robots.txt and at {tried}.",
            evidence=evidence,
        )
        return [absent]
    if not read.complete:
        if read.limit_reached:
            why = (
                f"the page is not in the {len(read.documents)} sitemap documents read, and "
                "Cernis's limit on sitemap documents or index depth left others unread"
            )
            code = ReasonCode.LIMIT_REACHED
        else:
            first = unread[0].unreadable
            assert first is not None
            why = f"the page is not in what was read, but {first.why}"
            code = first.reason_code
        partial = _non_liquet(
            new_id=new_id, subject=subject, site=site, why=why, code=code, evidence=evidence
        )
        return [partial]
    section = section_of(page_url, prefixes)
    others = {entry.key for entry in read.entries if under_prefix(entry.key, section)} - keys
    sitemaps = ", ".join(doc.url for doc in read.documents if doc.kind == "urlset")
    if others and expected_absent is not None:
        expected = _finding(
            new_id=new_id,
            subject=subject,
            site=site,
            summary=(
                f"The sitemap does not list the page, which is expected: {expected_absent} "
                f"(read: {sitemaps})."
            ),
            evidence=evidence,
        )
        return [expected]
    if others and read.news:
        news = _non_liquet(
            new_id=new_id,
            subject=subject,
            site=site,
            why=(
                "the page is not in the sitemaps read, but one is a Google News sitemap, "
                "which lists only recent articles, so the omission may be by design"
            ),
            code=ReasonCode.AMBIGUOUS,
            evidence=evidence,
        )
        return [news]
    if others:
        missing = _finding(
            new_id=new_id,
            subject=subject,
            site=site,
            summary=(
                f"The sitemap does not list the page, though it lists {len(others)} other "
                f"pages under {section} (read: {sitemaps})."
            ),
            evidence=evidence,
            defect=True,
        )
        return [
            missing,
            *sitemap_recommendation(
                missing, url=page_url, section=section, others=len(others), new_id=new_id
            ),
        ]
    alone = _finding(
        new_id=new_id,
        subject=subject,
        site=site,
        summary=(
            f"The sitemap does not list the page, and lists no other page under {section} "
            f"(read: {sitemaps})."
        ),
        evidence=evidence,
    )
    return [alone]
