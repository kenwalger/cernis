"""Fetch outcomes as findings: what Cernis could not see, and why (DESIGN.md section 3).

No check runs against a page Cernis did not see whole. Instead, every
question the peritext checks would have answered becomes a
``NOT_DETERMINABLE`` finding with the reason code for what happened and the
receipts as evidence of the attempt. One finding per check (and per
``og:*`` property), with the same key the check's own finding would have, so
history can match a later run that did read the page (Phase 5).

How a fetch maps to a reason code:

=================================================  =========================
What happened                                      Reason code
=================================================  =========================
robots.txt disallows the URL or a redirect target  ``DISALLOWED_BY_ROBOTS``
the host resolves to a non-public address          ``ADDRESS_REFUSED``
still ``429`` after every retry                    ``RATE_LIMITED``
``401`` or ``403``                                 ``ACCESS_DENIED``
timeout, connection, TLS, or too many redirects    ``FETCH_FAILED``
the body was longer than the size limit            ``FETCH_FAILED``
any other status that is not ``2xx`` (or a ``304``
with its cached body): ``404``, ``410``, ``5xx``,
a redirect that could not be followed              ``FETCH_FAILED``
=================================================  =========================
"""

from collections.abc import Callable
from dataclasses import dataclass

from cernis.checks.peritext import OG_CORE
from cernis.checks.registry import check
from cernis.fetch import FetchResult
from cernis.model import Actor, ErrorKind, Evidence, Finding, ReasonCode, Receipt, Status
from cernis.parse.extractors import SiteType

NewId = Callable[[], str]
"""Returns the next finding id in the run."""

QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("peri.canonical.present", "", "Whether the page declares a canonical link"),
    (
        "peri.canonical.single",
        "",
        "How many canonical URLs the page declares, and whether they agree",
    ),
    ("peri.canonical.absolute", "", "Whether the page's canonical URL is absolute"),
    ("peri.meta.description", "", "Whether the page has a meta description, and how long it is"),
    *(("peri.og.core", prop, f"Whether the page declares {prop}") for prop in OG_CORE),
    ("peri.og.url_matches_canonical", "", "Whether og:url agrees with the canonical URL"),
    ("peri.lang", "", "Whether the page declares its language"),
    ("peri.jsonld.parses", "", "Whether the page's JSON-LD blocks parse"),
    ("peri.title", "", "What the page's title is, and how long it is"),
)
"""Each peritext question, as ``(check id, target, question)``, in DESIGN.md order."""

_ERROR_WHY = {
    ErrorKind.TIMEOUT: "the request timed out",
    ErrorKind.CONNECTION: "the connection failed or the response could not be read",
    ErrorKind.TLS: "the TLS handshake failed",
    ErrorKind.TOO_MANY_REDIRECTS: "it redirected more times than Cernis follows",
}


@dataclass(frozen=True, kw_only=True)
class Readable:
    """A page Cernis saw whole.

    :param receipt: The receipt of the attempt that got it.
    :param body: Its whole body.
    """

    receipt: Receipt
    body: bytes


@dataclass(frozen=True, kw_only=True)
class Unreadable:
    """A page Cernis did not see whole, and why.

    :param reason_code: The reason code.
    :param why: Why, in plain English, as a clause (``the request timed out``).
    :param evidence: The attempt's evidence.
    :param actor: Who can change it.
    """

    reason_code: ReasonCode
    why: str
    evidence: tuple[Evidence, ...]
    actor: Actor


def _robots_actor(site: SiteType | None) -> Actor:
    """Say who controls a site's robots.txt (DESIGN.md section 3, Actor).

    :param site: The site type.
    :return: ``PLATFORM`` on DEV, ``AUTHOR`` on WordPress, else ``UNKNOWN``.
    """
    if site is SiteType.DEV:
        return Actor.PLATFORM
    if site is SiteType.WORDPRESS:
        return Actor.AUTHOR
    return Actor.UNKNOWN


def classify(result: FetchResult, site: SiteType | None) -> Readable | Unreadable:
    """Decide whether a fetch gave Cernis a page to check, and if not, why not.

    :param result: The fetch.
    :param site: The page's site type, for the actor.
    :return: The page, or the reason there is none.
    :raises ValueError: If the fetch has neither a receipt nor a robots
        decision, which the fetcher never produces.
    """
    final = result.final
    if result.disallowed_url is not None:
        decision = next(d for d in result.robots if d.url == result.disallowed_url)
        evidence = [
            Evidence(
                receipt_id=decision.receipt_id,
                location=f"robots.txt for {decision.url} ({decision.basis})",
                observed=decision.rule or f"no rule; robots.txt is {decision.basis.lower()}",
            )
        ]
        if final is not None:
            evidence.append(
                Evidence(
                    receipt_id=final.id, location="HTTP status", observed=str(final.status_code)
                )
            )
        return Unreadable(
            reason_code=ReasonCode.DISALLOWED_BY_ROBOTS,
            why=f"robots.txt disallows {result.disallowed_url} for Cernis",
            evidence=tuple(evidence),
            actor=_robots_actor(site),
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
            actor=Actor.UNKNOWN,
        )
    if final.error_kind is not ErrorKind.NONE:
        evidence = [
            Evidence(receipt_id=final.id, location="error_kind", observed=final.error_kind.value)
        ]
        if final.status_code is not None:
            evidence.append(
                Evidence(
                    receipt_id=final.id, location="HTTP status", observed=str(final.status_code)
                )
            )
        return Unreadable(
            reason_code=ReasonCode.FETCH_FAILED,
            why=_ERROR_WHY[final.error_kind],
            evidence=tuple(evidence),
            actor=Actor.UNKNOWN,
        )
    status = final.status_code
    if result.rate_limited:
        return Unreadable(
            reason_code=ReasonCode.RATE_LIMITED,
            why=f"the server answered 429 on all {len(result.receipts)} attempts",
            evidence=tuple(
                Evidence(
                    receipt_id=r.id,
                    location="HTTP status and Retry-After",
                    observed=f"{r.status_code}; Retry-After: {r.header('retry-after') or 'none'}",
                )
                for r in result.receipts
            ),
            actor=Actor.UNKNOWN,
        )
    status_evidence = (Evidence(receipt_id=final.id, location="HTTP status", observed=str(status)),)
    if status in (401, 403):
        return Unreadable(
            reason_code=ReasonCode.ACCESS_DENIED,
            why=f"the server answered {status}",
            evidence=status_evidence,
            actor=Actor.UNKNOWN,
        )
    if final.body_truncated_at is not None:
        return Unreadable(
            reason_code=ReasonCode.FETCH_FAILED,
            why=(
                f"the body was longer than Cernis's {final.body_truncated_at}-byte limit, "
                "so it was not read whole"
            ),
            evidence=(
                Evidence(
                    receipt_id=final.id,
                    location="body_truncated_at",
                    observed=str(final.body_truncated_at),
                ),
            ),
            actor=Actor.UNKNOWN,
        )
    whole = final.body_sha256 is not None and result.body is not None
    if status is not None and (200 <= status <= 299 or status == 304) and whole:
        assert result.body is not None
        return Readable(receipt=final, body=result.body)
    if status == 304:
        why = "the server answered 304 and Cernis had no cached copy"
    else:
        why = f"the server answered {status}"
    return Unreadable(
        reason_code=ReasonCode.FETCH_FAILED,
        why=why,
        evidence=status_evidence,
        actor=Actor.UNKNOWN,
    )


def not_determinable_findings(
    unreadable: Unreadable, *, subject_url: str, new_id: NewId
) -> list[Finding]:
    """Turn an unread page into one NOT_DETERMINABLE finding per peritext question.

    :param unreadable: Why the page was not read.
    :param subject_url: The audited URL.
    :param new_id: The run's finding id source.
    :return: The findings, in DESIGN.md order.
    """
    return [
        Finding(
            id=new_id(),
            check_id=check_id,
            check_version=check(check_id).version,
            status=Status.NOT_DETERMINABLE,
            actor=unreadable.actor,
            subject_url=subject_url,
            summary=f"{question} is not determinable: {unreadable.why}.",
            target=target,
            evidence=unreadable.evidence,
            reason_code=unreadable.reason_code,
            question=question,
        )
        for check_id, target, question in QUESTIONS
    ]
