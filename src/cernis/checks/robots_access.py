"""``epi.robots.access``: what a site's robots.txt says for general and AI crawlers.

One finding per name, the name being the ``target``: ``*`` for general
crawlers, then each token in the AI crawler list (:mod:`cernis.crawlers`).
Never a defect: whether to let AI crawlers in is the author's or the
platform's choice (DESIGN.md section 4).

The robots.txt is the one Cernis already fetched for the page (once per
origin per run), read by Cernis's own RFC 9309 matcher, so the answer for
each crawler rests on the same receipt as Cernis's own access. A crawler
named in a group gets that group's rules; one not named falls back to the
``*`` group, and the finding says which applied.

The check version is ``<registry version>+c<crawler list version>+m<matcher
version>``, so a change to the crawler list or to the matcher is a
``CHECKER`` change in history.

Actors: ``PLATFORM`` on DEV (dev.to's robots.txt), ``AUTHOR`` on WordPress
and owned sites, ``UNKNOWN`` otherwise.
"""

from cernis.checks.epitext import NewId, epi_actor
from cernis.checks.outcomes import Unreadable
from cernis.checks.registry import check
from cernis.crawlers import Crawler, crawler_list
from cernis.fetch import RobotsBasis, RobotsPolicy
from cernis.fetch.rfc9309 import MATCHER_VERSION
from cernis.model import ErrorKind, Evidence, Finding, ReasonCode, Status
from cernis.parse.extractors import SiteType

CHECK_ID = "epi.robots.access"


def check_version() -> str:
    """Return the version every ``epi.robots.access`` finding records.

    :return: Such as ``1+c1+m1``: the check, the crawler list, and the matcher.
    """
    return f"{check(CHECK_ID).version}+c{crawler_list().version}+m{MATCHER_VERSION}"


def _who(crawler: Crawler | None) -> str:
    """Name a crawler for a summary.

    :param crawler: The crawler, or ``None`` for general crawlers.
    :return: Such as ``GPTBot (OpenAI)``, or ``general crawlers (*)``.
    """
    return "general crawlers (*)" if crawler is None else f"{crawler.token} ({crawler.operator})"


def robots_access(
    *,
    subject: str,
    url: str,
    site: SiteType | None,
    policy: RobotsPolicy,
    new_id: NewId,
) -> list[Finding]:
    """Report what robots.txt says about one page, for ``*`` and each AI crawler.

    :param subject: The audited URL.
    :param url: The URL the page answered at, in the fetcher's normalized
        form; its path and query are what the rules are matched against.
    :param site: The page's site type, for the actor.
    :param policy: The robots.txt policy for that URL's origin.
    :param new_id: The run's finding id source.
    :return: The findings: ``*`` first, then the crawler list's order.
    """
    actor = epi_actor(site, CHECK_ID)
    version = check_version()
    receipt = policy.receipt
    findings: list[Finding] = []
    for crawler in (None, *crawler_list().crawlers):
        name = "*" if crawler is None else crawler.token
        who = _who(crawler)
        if policy.basis is RobotsBasis.UNREACHABLE:
            if receipt.error_kind is not ErrorKind.NONE:
                code, why = ReasonCode.FETCH_FAILED, f"the fetch failed ({receipt.error_kind})"
            elif receipt.status_code == 429:
                code, why = ReasonCode.RATE_LIMITED, "it answered 429"
            else:
                code, why = ReasonCode.FETCH_FAILED, f"it answered {receipt.status_code}"
            question = f"What robots.txt says about this page for {who}"
            findings.append(
                Finding(
                    id=new_id(),
                    check_id=CHECK_ID,
                    check_version=version,
                    status=Status.NOT_DETERMINABLE,
                    actor=actor,
                    subject_url=subject,
                    summary=(
                        f"{question} is not determinable: {policy.robots_url} could not be "
                        f"read ({why})."
                    ),
                    target=name,
                    evidence=(
                        Evidence(
                            receipt_id=receipt.id,
                            location=policy.robots_url,
                            observed=str(receipt.status_code or receipt.error_kind),
                        ),
                    ),
                    reason_code=code,
                    question=question,
                )
            )
            continue
        if policy.basis is RobotsBasis.UNAVAILABLE:
            summary = (
                f"robots.txt answered {receipt.status_code}, so under RFC 9309 it allows "
                f"{who} to fetch this page."
            )
            evidence = Evidence(
                receipt_id=receipt.id, location=policy.robots_url, observed=str(receipt.status_code)
            )
        else:
            rules = policy.rules
            assert rules is not None
            decision = policy.decide(url, name)
            if rules.names(name):
                group, group_text = name, f"a group names {name}"
            elif name != "*" and rules.names("*"):
                group, group_text = "*", f"no group names {name}, so the * group applies"
            else:
                group = name
                group_text = (
                    "there is no * group"
                    if name == "*"
                    else f"no group names {name} and there is no * group"
                )
            verdict = "allows" if decision.allowed else "disallows"
            rule_text = (
                f"the rule {decision.rule!r} decides"
                if decision.rule is not None
                else "no rule matches"
            )
            summary = f"robots.txt {verdict} {who} to fetch this page: {group_text}; {rule_text}."
            location = f"{policy.robots_url}, group for {group}"
            evidence = (
                Evidence(receipt_id=receipt.id, location=location, observed=decision.rule)
                if decision.rule is not None
                else Evidence(
                    receipt_id=receipt.id,
                    location=location,
                    searched_for=f"a rule matching {url}",
                )
            )
        findings.append(
            Finding(
                id=new_id(),
                check_id=CHECK_ID,
                check_version=version,
                status=Status.OBSERVED,
                actor=actor,
                subject_url=subject,
                summary=summary,
                target=name,
                evidence=(evidence,),
            )
        )
    return findings


def not_read(
    *, subject: str, site: SiteType | None, reason: Unreadable, new_id: NewId
) -> list[Finding]:
    """Say, for each name, that robots.txt was never read for an unread page.

    For a page whose host the address screen refused before robots.txt was
    fetched: the question is open, never silently dropped.

    :param subject: The audited URL.
    :param site: The page's site type, for the actor.
    :param reason: Why the page (and so its robots.txt) was not read.
    :param new_id: The run's finding id source.
    :return: One NOT_DETERMINABLE finding per name, with the page's reason code.
    """
    actor = epi_actor(site, CHECK_ID)
    version = check_version()
    findings: list[Finding] = []
    for crawler in (None, *crawler_list().crawlers):
        question = f"What robots.txt says about this page for {_who(crawler)}"
        findings.append(
            Finding(
                id=new_id(),
                check_id=CHECK_ID,
                check_version=version,
                status=Status.NOT_DETERMINABLE,
                actor=actor,
                subject_url=subject,
                summary=(
                    f"{question} is not determinable: robots.txt was not fetched ({reason.why})."
                ),
                target="*" if crawler is None else crawler.token,
                evidence=reason.evidence,
                reason_code=reason.reason_code,
                question=question,
            )
        )
    return findings
