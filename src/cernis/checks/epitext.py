"""Epitext checks: around the page (DESIGN.md section 4, "Epitext").

Three checks, each fed by the run's fetches (:mod:`cernis.audit` fetches
each distinct URL once):

- ``epi.canonical.resolves``: each canonical URL's status and redirect
  chain, one finding per canonical (the URL is the ``target``). Defect only
  for 404 or 410. A redirect is a fact naming the final URL.
- ``epi.og.image.resolves``: the ``og:image`` URL's status and content
  type (the URL is the ``target``). Defect for 404 or 410, or a 200 whose
  ``Content-Type`` is not ``image/*``. The image is never decoded or stored;
  only its receipt is kept.
- ``epi.pair.canonical``: the flagship check, for a declared original and
  copy. Two findings: target ``copy`` compares the copy's canonical with the
  original's URL, target ``original`` compares the original's canonical
  with its own URL, both with the shared URL comparison
  (:func:`cernis.urls.compare_urls`). ``DIFFERENT``, or a copy with no
  canonical, is a defect; ``EQUIVALENT`` is a fact naming each normalization
  that mattered. Both findings take the copy's URL as their subject, so an
  original with several copies still gives every finding its own key.

A resource Cernis did not get an answer about is ``NOT_DETERMINABLE``, with
the same reason codes as an unread page (:mod:`cernis.checks.outcomes`):
``DISALLOWED_BY_ROBOTS``, ``ADDRESS_REFUSED``, ``RATE_LIMITED``,
``ACCESS_DENIED`` (401, 403), and ``FETCH_FAILED`` (no response, or 5xx).

When the original cannot be read whole, both pair findings are
``NOT_DETERMINABLE`` with the original's reason code: the copy's canonical
can only be judged against what the original is, including where it
redirects. When only the copy cannot be read, the copy finding is.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from cernis.checks.outcomes import Readable, Unreadable
from cernis.checks.peritext import actor_for
from cernis.checks.registry import check
from cernis.fetch import FetchResult
from cernis.model import Actor, ErrorKind, Evidence, Finding, ReasonCode, Receipt, Status
from cernis.parse.extractors import Article, SiteType
from cernis.parse.html import ParsedPage
from cernis.urls import UrlMatch, compare_urls, is_absolute_http_url, normalize_url

NewId = Callable[[], str]
"""Returns the next finding id in the run."""

_DEV_PLATFORM_EPI = frozenset({"epi.og.image.resolves", "epi.robots.access"})


def epi_actor(site: SiteType | None, check_id: str) -> Actor:
    """Say who can change what an epitext resource check looks at.

    :param site: The page's site type.
    :param check_id: The check.
    :return: As for peritext; on DEV, the ``og:image`` (DEV's generated
        social image) and robots.txt are the platform's, and the canonical
        and the article's links are the author's.
    """
    if site is SiteType.DEV and check_id in _DEV_PLATFORM_EPI:
        return Actor.PLATFORM
    return actor_for(site, check_id)


@dataclass(frozen=True, kw_only=True)
class FetchedPage:
    """One audited page: how it was fetched, and what was read from it.

    :param subject: The audited URL, as the fetcher requested it.
    :param site: The page's site type, declared, by prefix, or by host.
    :param result: The fetch.
    :param outcome: Whether Cernis read it whole, and if not, why not.
    :param page: What was read, or ``None`` if it was not read whole.
    :param article: The article body as the extractor found it, or ``None``
        if the page was not read whole.
    """

    subject: str
    site: SiteType | None
    result: FetchResult
    outcome: Readable | Unreadable
    page: ParsedPage | None
    article: Article | None = None

    @property
    def base(self) -> str:
        """The URL relative references on the page resolve against."""
        if isinstance(self.outcome, Readable):
            return self.outcome.receipt.final_url or self.subject
        return self.subject


def _resolve(base: str, href: str) -> str | None:
    """Resolve an ``href`` to an absolute http(s) URL, if it is one.

    :param base: The page's URL.
    :param href: The ``href`` as written.
    :return: The absolute URL, or ``None`` if it does not resolve to one.
    """
    try:
        url = urljoin(base, href.strip())
    except ValueError:
        return None
    return url if is_absolute_http_url(url) else None


def canonical_urls(page: FetchedPage) -> list[str]:
    """Return the page's canonical URLs, resolved and distinct after normalization.

    :param page: The page.
    :return: The URLs, in document order; empty if the page was not read or
        has no canonical that resolves to an http(s) URL.
    """
    if page.page is None:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for canonical in page.page.canonicals:
        if canonical.href is None or not canonical.href.strip():
            continue
        url = _resolve(page.base, canonical.href)
        if url is not None and normalize_url(url) not in seen:
            seen.add(normalize_url(url))
            urls.append(url)
    return urls


def og_image_url(page: FetchedPage) -> str | None:
    """Return the page's ``og:image`` URL, resolved.

    :param page: The page.
    :return: The first ``og:image`` with a value (``property=`` preferred), as
        an absolute http(s) URL, or ``None``.
    """
    if page.page is None:
        return None
    tags = sorted(page.page.og("og:image"), key=lambda tag: tag.attribute != "property")
    for tag in tags:
        if tag.content and tag.content.strip():
            return _resolve(page.base, tag.content)
    return None


def unanswered(result: FetchResult, actor: Actor) -> Unreadable | None:
    """Decide whether a resource fetch got no answer Cernis can report on.

    :param result: The fetch.
    :param actor: The actor for the not-determinable finding.
    :return: The reason, or ``None`` if a status was received that the check
        can report (2xx, 3xx, or a 4xx other than 401, 403, and 429).
    :raises ValueError: If the fetch has neither a receipt nor a robots
        decision, which the fetcher never returns.
    """
    final = result.final
    if result.disallowed_url is not None:
        decision = next(d for d in result.robots if d.url == result.disallowed_url)
        return Unreadable(
            reason_code=ReasonCode.DISALLOWED_BY_ROBOTS,
            why=f"robots.txt disallows {result.disallowed_url} for Cernis",
            evidence=(
                Evidence(
                    receipt_id=decision.receipt_id,
                    location=f"robots.txt for {decision.url} ({decision.basis})",
                    observed=decision.rule or f"no rule; robots.txt is {decision.basis.lower()}",
                ),
            ),
            actor=actor,
        )
    if final is None:
        raise ValueError(f"fetch of {result.requested_url} has no receipt and no robots decision")
    if final.error_kind is ErrorKind.ADDRESS_REFUSED:
        reason = next(
            (r.reason for r in result.refusals if r.receipt_id == final.id), "a non-public address"
        )
        return Unreadable(
            reason_code=ReasonCode.ADDRESS_REFUSED,
            why=f"Cernis refused to contact it: {reason}",
            evidence=(Evidence(receipt_id=final.id, location="address screen", observed=reason),),
            actor=actor,
        )
    if final.error_kind is not ErrorKind.NONE:
        return Unreadable(
            reason_code=ReasonCode.FETCH_FAILED,
            why=f"the fetch failed ({final.error_kind.value})",
            evidence=(
                Evidence(
                    receipt_id=final.id, location="error_kind", observed=final.error_kind.value
                ),
            ),
            actor=actor,
        )
    status = final.status_code or 0
    status_evidence = (Evidence(receipt_id=final.id, location="HTTP status", observed=str(status)),)
    if result.rate_limited:
        return Unreadable(
            reason_code=ReasonCode.RATE_LIMITED,
            why=f"the server answered 429 on all {len(result.receipts)} attempts",
            evidence=tuple(
                Evidence(receipt_id=r.id, location="HTTP status", observed=str(r.status_code))
                for r in result.receipts
            ),
            actor=actor,
        )
    if status in (401, 403):
        return Unreadable(
            reason_code=ReasonCode.ACCESS_DENIED,
            why=f"the server answered {status}",
            evidence=status_evidence,
            actor=actor,
        )
    if status >= 500:
        return Unreadable(
            reason_code=ReasonCode.FETCH_FAILED,
            why=f"the server answered {status}",
            evidence=status_evidence,
            actor=actor,
        )
    return None


def chain_from(url: str, final: Receipt) -> tuple[str, ...]:
    """Return the redirects a URL itself went through, within a fetch.

    A run fetches each URL once, so a URL can be answered by a fetch that
    started elsewhere: a canonical that is the final URL of the page's own
    fetch answered directly, with no redirect of its own.

    :param url: The URL the finding is about.
    :param final: The fetch's last receipt.
    :return: The part of the redirect chain from ``url`` on; empty if ``url``
        is the final URL; the whole chain if ``url`` is in neither.
    """
    key = str(httpx.URL(url))
    chain = final.redirect_chain
    for index, hop in enumerate(chain):
        if str(httpx.URL(hop)) == key:
            return chain[index:]
    if final.final_url is not None and str(httpx.URL(final.final_url)) == key:
        return ()
    return chain


def _status_evidence(result: FetchResult, url: str) -> list[Evidence]:
    """Record a resource's status, redirect chain, and final URL.

    :param result: The fetch.
    :param url: The URL the finding is about.
    :return: The evidence.
    """
    final = result.final
    assert final is not None
    evidence = [
        Evidence(receipt_id=final.id, location="HTTP status", observed=str(final.status_code))
    ]
    chain = chain_from(url, final)
    if chain:
        hops = " -> ".join((*chain, final.final_url or ""))
        evidence.append(Evidence(receipt_id=final.id, location="redirect chain", observed=hops))
    return evidence


def _finding(
    *,
    new_id: NewId,
    check_id: str,
    subject: str,
    target: str,
    actor: Actor,
    summary: str,
    evidence: Sequence[Evidence],
    defect: bool = False,
) -> Finding:
    """Build an OBSERVED epitext finding.

    :param new_id: The run's finding id source.
    :param check_id: The check.
    :param subject: The audited URL.
    :param target: The target.
    :param actor: The actor.
    :param summary: One sentence.
    :param evidence: The evidence.
    :param defect: Whether the table's defect condition holds.
    :return: The finding.
    """
    return Finding(
        id=new_id(),
        check_id=check_id,
        check_version=check(check_id).version,
        status=Status.OBSERVED,
        actor=actor,
        subject_url=subject,
        summary=summary,
        target=target,
        evidence=tuple(evidence),
        defect=defect,
    )


def _non_liquet(
    *,
    new_id: NewId,
    check_id: str,
    subject: str,
    target: str,
    question: str,
    reason: Unreadable,
) -> Finding:
    """Build a NOT_DETERMINABLE epitext finding.

    :param new_id: The run's finding id source.
    :param check_id: The check.
    :param subject: The audited URL.
    :param target: The target.
    :param question: What could not be answered.
    :param reason: Why.
    :return: The finding.
    """
    return Finding(
        id=new_id(),
        check_id=check_id,
        check_version=check(check_id).version,
        status=Status.NOT_DETERMINABLE,
        actor=reason.actor,
        subject_url=subject,
        summary=f"{question} is not determinable: {reason.why}.",
        target=target,
        evidence=reason.evidence,
        reason_code=reason.reason_code,
        question=question,
    )


def canonical_resolves(
    page: FetchedPage, url: str, result: FetchResult, *, new_id: NewId
) -> Finding:
    """``epi.canonical.resolves``: one canonical URL's status and redirect chain.

    :param page: The page that declares the canonical.
    :param url: The canonical URL, resolved.
    :param result: Its fetch.
    :param new_id: The run's finding id source.
    :return: The finding.
    """
    check_id = "epi.canonical.resolves"
    actor = epi_actor(page.site, check_id)
    reason = unanswered(result, actor)
    if reason is not None:
        return _non_liquet(
            new_id=new_id,
            check_id=check_id,
            subject=page.subject,
            target=url,
            question=f"Whether the canonical URL {url} resolves",
            reason=reason,
        )
    final = result.final
    assert final is not None
    status = final.status_code
    chain = chain_from(url, final)
    if chain:
        hops = len(chain)
        summary = (
            f"The canonical URL {url} redirects ({hops} {'hop' if hops == 1 else 'hops'}) to "
            f"{final.final_url}, which answers {status}."
        )
    else:
        summary = f"The canonical URL {url} answers {status}."
    gone = status in (404, 410)
    if gone:
        summary = summary.removesuffix(".") + ", so it names no page."
    return _finding(
        new_id=new_id,
        check_id=check_id,
        subject=page.subject,
        target=url,
        actor=actor,
        summary=summary,
        evidence=_status_evidence(result, url),
        defect=gone,
    )


def og_image_resolves(
    page: FetchedPage, url: str, result: FetchResult, *, new_id: NewId
) -> Finding:
    """``epi.og.image.resolves``: the ``og:image`` URL's status and content type.

    :param page: The page that declares it.
    :param url: The ``og:image`` URL, resolved.
    :param result: Its fetch, made without storing the image.
    :param new_id: The run's finding id source.
    :return: The finding.
    """
    check_id = "epi.og.image.resolves"
    actor = epi_actor(page.site, check_id)
    reason = unanswered(result, actor)
    if reason is not None:
        return _non_liquet(
            new_id=new_id,
            check_id=check_id,
            subject=page.subject,
            target=url,
            question=f"Whether og:image {url} resolves to an image",
            reason=reason,
        )
    final = result.final
    assert final is not None
    status = final.status_code or 0
    evidence = _status_evidence(result, url)
    content_type = final.header("content-type")
    where = f" (after redirecting to {final.final_url})" if chain_from(url, final) else ""
    defect = False
    if status in (404, 410):
        defect = True
        summary = f"og:image {url} answers {status}{where}, so the page names no image."
    elif 200 <= status <= 299:
        evidence.append(
            Evidence(receipt_id=final.id, location="Content-Type", observed=content_type)
            if content_type is not None
            else Evidence(
                receipt_id=final.id,
                location="Content-Type",
                observed=None,
                searched_for="a Content-Type header",
            )
        )
        media = (content_type or "").split(";", 1)[0].strip().lower()
        if media.startswith("image/"):
            summary = f"og:image {url} answers {status}{where} with an image ({media})."
        else:
            defect = True
            declared = f"Content-Type {media}" if media else "no Content-Type"
            summary = f"og:image {url} answers {status}{where} with {declared}, not an image."
    else:
        summary = f"og:image {url} answers {status}{where}."
    return _finding(
        new_id=new_id,
        check_id=check_id,
        subject=page.subject,
        target=url,
        actor=actor,
        summary=summary,
        evidence=evidence,
        defect=defect,
    )


def _canonical_evidence(page: FetchedPage, role: str) -> list[Evidence]:
    """Record a page's canonical links for the pair check, or the search that found none.

    :param page: The page, read whole.
    :param role: ``original`` or ``copy``, for the location.
    :return: The evidence.
    """
    assert page.page is not None
    assert isinstance(page.outcome, Readable)
    receipt_id = page.outcome.receipt.id
    hrefs = [c.href for c in page.page.canonicals if c.href is not None and c.href.strip()]
    if not hrefs:
        return [
            Evidence(
                receipt_id=receipt_id,
                location=f"the {role}'s document",
                observed=None,
                searched_for='a <link rel="canonical"> with an href',
            )
        ]
    return [
        Evidence(
            receipt_id=receipt_id, location=f'the {role}\'s link[rel="canonical"] href', observed=h
        )
        for h in hrefs
    ]


def _compare_canonical(
    page: FetchedPage,
    role: str,
    against: str,
    redirects: Sequence[Receipt],
) -> tuple[str, bool, str | None] | None:
    """Compare a page's canonical with a URL.

    :param page: The page, read whole.
    :param role: ``original`` or ``copy``.
    :param against: The URL its canonical is expected to name.
    :param redirects: Receipts whose redirects can make two URLs equivalent.
    :return: ``None`` if the page's canonicals disagree with each other (no
        single canonical to compare); otherwise ``(summary, defect,
        canonical)``, where ``canonical`` is ``None`` if there is none.
    """
    canonicals = canonical_urls(page)
    if not canonicals:
        return ("", False, None)
    first = canonicals[0]
    for other in canonicals[1:]:
        if compare_urls(first, other, redirects=redirects).outcome is UrlMatch.DIFFERENT:
            return None
    result = compare_urls(first, against, redirects=redirects)
    whose = "copy's" if role == "copy" else "original's"
    target_name = "the original's URL" if role == "copy" else "the original's own URL"
    if result.outcome is UrlMatch.IDENTICAL:
        return (f"The {whose} canonical URL is {target_name}, {against}.", False, first)
    if result.outcome is UrlMatch.EQUIVALENT:
        reasons = ", ".join(result.reasons)
        if result.receipt_id is not None:
            reasons += f", receipt {result.receipt_id}"
        return (
            f"The {whose} canonical URL ({first}) is equivalent to {target_name} ({against}): "
            f"{reasons}.",
            False,
            first,
        )
    return (
        f"The {whose} canonical URL ({first}) is different from {target_name} ({against}).",
        True,
        first,
    )


def pair_canonical(
    original: FetchedPage,
    copy: FetchedPage,
    *,
    redirects: Sequence[Receipt],
    new_id: NewId,
) -> list[Finding]:
    """``epi.pair.canonical``: whether the copy names the original, and the original itself.

    :param original: The declared original.
    :param copy: The declared copy.
    :param redirects: Every receipt in the run so far, for redirect equivalence.
    :param new_id: The run's finding id source.
    :return: Two findings: target ``copy``, then target ``original``.
    """
    check_id = "epi.pair.canonical"
    subject = copy.subject
    findings: list[Finding] = []
    copy_question = f"Whether the copy's canonical URL names the original, {original.subject}"
    original_question = (
        f"Whether the original's canonical URL names the original itself, {original.subject}"
    )
    if isinstance(original.outcome, Unreadable):
        reason = Unreadable(
            reason_code=original.outcome.reason_code,
            why=f"the original could not be read whole: {original.outcome.why}",
            evidence=original.outcome.evidence,
            actor=Actor.AUTHOR,
        )
        for target, question in (("copy", copy_question), ("original", original_question)):
            findings.append(
                _non_liquet(
                    new_id=new_id,
                    check_id=check_id,
                    subject=subject,
                    target=target,
                    question=question,
                    reason=reason,
                )
            )
        return findings
    if isinstance(copy.outcome, Unreadable):
        reason = Unreadable(
            reason_code=copy.outcome.reason_code,
            why=f"the copy could not be read whole: {copy.outcome.why}",
            evidence=copy.outcome.evidence,
            actor=Actor.AUTHOR,
        )
        findings.append(
            _non_liquet(
                new_id=new_id,
                check_id=check_id,
                subject=subject,
                target="copy",
                question=copy_question,
                reason=reason,
            )
        )
    else:
        findings.append(
            _pair_side(copy, "copy", original.subject, redirects, subject, copy_question, new_id)
        )
    findings.append(
        _pair_side(
            original, "original", original.subject, redirects, subject, original_question, new_id
        )
    )
    return findings


def _pair_side(
    page: FetchedPage,
    role: str,
    against: str,
    redirects: Sequence[Receipt],
    subject: str,
    question: str,
    new_id: NewId,
) -> Finding:
    """Build one side of the pair check.

    :param page: The page whose canonical is judged, read whole.
    :param role: ``copy`` or ``original``.
    :param against: The original's URL.
    :param redirects: Receipts for redirect equivalence.
    :param subject: The pair's subject (the copy's URL).
    :param question: The question, if the answer is ambiguous.
    :param new_id: The run's finding id source.
    :return: The finding.
    """
    check_id = "epi.pair.canonical"
    evidence = _canonical_evidence(page, role)
    compared = _compare_canonical(page, role, against, redirects)
    if compared is None:
        reason = Unreadable(
            reason_code=ReasonCode.AMBIGUOUS,
            why=f"the {role} declares canonical URLs that name different URLs",
            evidence=tuple(evidence),
            actor=Actor.AUTHOR,
        )
        return _non_liquet(
            new_id=new_id,
            check_id=check_id,
            subject=subject,
            target=role,
            question=question,
            reason=reason,
        )
    summary, defect, canonical = compared
    if canonical is None:
        if role == "copy":
            summary = (
                f"The copy declares no canonical URL, so it does not name the original, {against}."
            )
            defect = True
        else:
            summary = (
                "The original declares no canonical URL, so nothing on it contradicts the pairing."
            )
    return _finding(
        new_id=new_id,
        check_id=check_id,
        subject=subject,
        target=role,
        actor=Actor.AUTHOR,
        summary=summary,
        evidence=evidence,
        defect=defect,
    )


__all__ = [
    "FetchedPage",
    "canonical_resolves",
    "canonical_urls",
    "epi_actor",
    "og_image_resolves",
    "og_image_url",
    "pair_canonical",
    "unanswered",
]
