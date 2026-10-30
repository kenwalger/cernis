"""Tests for run assembly: fetch outcomes as findings, snapshots, and a run that validates."""

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fetch_support import FakeResolver, Site, make_fetcher, redirect, respond
from parse_support import fixture

import cernis.audit as audit_module
from cernis.audit import Target, audit, run_id_for
from cernis.checks.outcomes import QUESTIONS
from cernis.model import (
    ErrorKind,
    Evidence,
    ExtractorSelection,
    Finding,
    ReasonCode,
    RunError,
    Status,
)
from cernis.parse import SitePrefix, SiteType

PAGE = "https://blog.example.com/two-canonicals/"
HTML = {"content-type": "text/html; charset=utf-8"}


class Clock:
    """A wall clock that moves a second each time it is read."""

    def __init__(self) -> None:
        self.time = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        """Read the clock.

        :return: The time, then advance it.
        """
        current = self.time
        self.time += timedelta(seconds=1)
        return current


def run_on(
    site: Site,
    tmp_path: Path,
    *targets: Target,
    resolver: FakeResolver | None = None,
    **config: int,
) -> object:
    """Audit targets against a scripted web.

    :param site: The scripted web.
    :param tmp_path: The cache directory.
    :param *targets: What to audit.
    :param resolver: The fake resolver.
    :param **config: Fetch settings.
    :return: The run.
    """
    fetcher = make_fetcher(site, tmp_path, resolver=resolver, min_interval=0, **config)  # type: ignore[arg-type]
    return audit(list(targets), fetcher, now=Clock())


def test_a_page_read_whole_is_checked_snapshotted_and_validated(tmp_path: Path) -> None:
    """Receipts, a snapshot, observed findings, and recommendations in one valid run."""
    site = Site()
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))

    run = audit(
        [Target(url=PAGE, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path),
        now=Clock(),
    )

    assert run.id == "20261030T120000Z"
    assert run.finished_at > run.started_at
    assert run.subjects == (PAGE,)
    assert [r.requested_url for r in run.receipts] == ["https://blog.example.com/robots.txt", PAGE]
    (snapshot,) = run.snapshots
    assert (snapshot.receipt_id, snapshot.extractor_id, snapshot.extractor_selection) == (
        "r-002",
        "wordpress.entry",
        ExtractorSelection.DECLARED,
    )
    statuses = [f.status for f in run.findings]
    assert statuses.count(Status.OBSERVED) == 13
    assert statuses.count(Status.RECOMMENDATION) == 1
    assert [f.id for f in run.findings] == [f"f-{n:03d}" for n in range(1, 15)]
    (advice,) = [f for f in run.findings if f.status is Status.RECOMMENDATION]
    (based,) = advice.based_on
    assert next(f for f in run.findings if f.id == based).check_id == "peri.canonical.single"


def test_run_ids_name_the_start_in_utc() -> None:
    """DESIGN.md section 7: Run: 20261117T180000Z."""
    assert run_id_for(datetime(2026, 11, 17, 18, 0, tzinfo=UTC)) == "20261117T180000Z"


def _not_determinable(run: object) -> list[Finding]:
    """Check an unread page's findings and return them.

    :param run: The run.
    :return: Its findings, all NOT_DETERMINABLE, one per question.
    """
    findings = list(run.findings)  # type: ignore[attr-defined]
    assert [f.status for f in findings] == [Status.NOT_DETERMINABLE] * len(QUESTIONS)
    assert [(f.check_id, f.target, f.question) for f in findings] == list(QUESTIONS)
    assert run.snapshots == ()  # type: ignore[attr-defined]
    assert len({f.reason_code for f in findings}) == 1
    assert len({f.evidence for f in findings}) == 1
    return findings


@pytest.mark.parametrize(
    ("reply", "code", "observed"),
    [
        (respond(404), ReasonCode.FETCH_FAILED, "404"),
        (respond(410), ReasonCode.FETCH_FAILED, "410"),
        (respond(500), ReasonCode.FETCH_FAILED, "500"),
        (respond(401), ReasonCode.ACCESS_DENIED, "401"),
        (respond(403), ReasonCode.ACCESS_DENIED, "403"),
        (respond(302), ReasonCode.FETCH_FAILED, "302"),
        (respond(304), ReasonCode.FETCH_FAILED, "304"),
        (httpx.ConnectTimeout("slow"), ReasonCode.FETCH_FAILED, "TIMEOUT"),
        (httpx.ConnectError("refused"), ReasonCode.FETCH_FAILED, "CONNECTION"),
    ],
)
def test_a_page_not_read_gives_one_non_liquet_per_question_and_no_checks(
    tmp_path: Path, reply: object, code: ReasonCode, observed: str
) -> None:
    """Every question the checks would answer is NOT_DETERMINABLE, citing the attempt."""
    site = Site()
    site.add(PAGE, reply)  # type: ignore[arg-type]

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE)))

    assert findings[0].reason_code is code
    assert findings[0].evidence[0].observed == observed
    assert findings[0].evidence[0].receipt_id == "r-002"


def test_a_lasting_429_is_rate_limited_with_every_attempt_as_evidence(tmp_path: Path) -> None:
    """Each attempt's status and Retry-After is on record."""
    site = Site()
    site.add(PAGE, respond(429, headers={"retry-after": "1"}))

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE)))

    assert findings[0].reason_code is ReasonCode.RATE_LIMITED
    assert [e.observed for e in findings[0].evidence] == ["429; Retry-After: 1"] * 3
    assert [e.receipt_id for e in findings[0].evidence] == ["r-002", "r-003", "r-004"]


def test_a_page_disallowed_by_robots_cites_the_robots_receipt(tmp_path: Path) -> None:
    """Nothing was requested, so the evidence is the robots.txt decision."""
    site = Site()
    site.add("https://blog.example.com/robots.txt", respond(200, b"User-agent: *\nDisallow: /\n"))

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE, site=SiteType.WORDPRESS)))

    assert findings[0].reason_code is ReasonCode.DISALLOWED_BY_ROBOTS
    (evidence,) = findings[0].evidence
    assert (evidence.receipt_id, evidence.observed) == ("r-001", "Disallow: /")
    assert findings[0].actor.value == "AUTHOR"


def test_a_redirect_to_a_disallowed_url_cites_both_receipts(tmp_path: Path) -> None:
    """The redirect was received; its target was not requested."""
    site = Site()
    site.add(PAGE, redirect("https://other.example/x"))
    site.add("https://other.example/robots.txt", respond(200, b"User-agent: *\nDisallow: /\n"))

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE)))

    # other.example's robots.txt (r-002) is fetched mid-redirect, before the
    # attempt's own receipt (r-003, the 301) is written.
    assert [e.receipt_id for e in findings[0].evidence] == ["r-002", "r-003"]


def test_a_refused_address_is_address_refused(tmp_path: Path) -> None:
    """The reason names the address and its range."""
    site = Site()
    resolver = FakeResolver({"blog.example.com": ["10.0.0.7"]})

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE), resolver=resolver))

    assert findings[0].reason_code is ReasonCode.ADDRESS_REFUSED
    assert "10.0.0.7 is private" in (findings[0].evidence[0].observed or "")
    assert site.requests == []


def test_too_many_redirects_is_fetch_failed(tmp_path: Path) -> None:
    """A redirect loop is a failed fetch."""
    site = Site()
    site.add(PAGE, redirect(PAGE + "x"))
    site.add(PAGE + "x", redirect(PAGE))

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE), max_redirects=2))

    assert findings[0].reason_code is ReasonCode.FETCH_FAILED
    assert findings[0].evidence[0].observed == ErrorKind.TOO_MANY_REDIRECTS.value


def test_a_truncated_page_is_not_checked(tmp_path: Path) -> None:
    """ADR-003: a page cut off at the size limit is never checked or snapshotted."""
    site = Site()
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))

    findings = _not_determinable(run_on(site, tmp_path, Target(url=PAGE), max_body_bytes=100))

    assert findings[0].reason_code is ReasonCode.FETCH_FAILED
    assert findings[0].evidence[0].location == "body_truncated_at"
    assert findings[0].summary == (
        "Whether the page declares a canonical link is not determinable: the body was longer "
        "than Cernis's 100-byte limit, so it was not read whole."
    )


def test_a_url_given_twice_is_audited_once(tmp_path: Path) -> None:
    """Equivalent URLs are one subject, so keys stay unique."""
    site = Site()
    site.add(PAGE, respond(404))

    run = run_on(
        site, tmp_path, Target(url=PAGE), Target(url="https://BLOG.example.com/two-canonicals")
    )

    assert run.subjects == (PAGE,)  # type: ignore[attr-defined]


def test_several_pages_share_one_run_and_one_robots_receipt(tmp_path: Path) -> None:
    """robots.txt is fetched once per origin per run, and the run holds it once."""
    site = Site()
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))
    site.add("https://blog.example.com/missing/", respond(404))

    run = run_on(site, tmp_path, Target(url=PAGE), Target(url="https://blog.example.com/missing/"))

    urls = [r.requested_url for r in run.receipts]  # type: ignore[attr-defined]
    assert urls.count("https://blog.example.com/robots.txt") == 1
    assert len(run.subjects) == 2  # type: ignore[attr-defined]


def test_a_run_that_fails_validation_raises_and_is_never_emitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finding citing a receipt the run does not hold is a bug: the audit raises."""
    site = Site()
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))
    real = audit_module.peritext_findings

    def broken(*args: object, **kwargs: object) -> list[Finding]:
        findings = real(*args, **kwargs)  # type: ignore[arg-type]
        bad = Evidence(receipt_id="r-999", location="nowhere", observed="x")
        return [
            dataclasses.replace(findings[0], evidence=(bad,)),
            *findings[1:],
        ]

    monkeypatch.setattr(audit_module, "peritext_findings", broken)

    with pytest.raises(RunError, match="r-999"):
        run_on(site, tmp_path, Target(url=PAGE))


def test_no_urls_is_an_error(tmp_path: Path) -> None:
    """An audit needs something to audit."""
    with pytest.raises(ValueError, match="at least one URL"):
        audit([], make_fetcher(Site(), tmp_path), now=Clock())


# Prefix rules (Session 4d)

BLOG_RULE = SitePrefix(prefix="https://blog.example.com/", site=SiteType.WORDPRESS)


def test_a_prefix_rule_chooses_the_extractor_and_is_recorded(tmp_path: Path) -> None:
    """An undeclared URL under a prefix gets the prefix's site type, marked 'prefix'."""
    site = Site()
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))

    run = audit([Target(url=PAGE)], make_fetcher(site, tmp_path), now=Clock(), prefixes=[BLOG_RULE])

    (snapshot,) = run.snapshots
    assert (snapshot.extractor_id, snapshot.extractor_selection) == (
        "wordpress.entry",
        ExtractorSelection.PREFIX,
    )
    assert {f.actor.value for f in run.findings} == {"AUTHOR"}


def test_a_declaration_beats_a_prefix_rule(tmp_path: Path) -> None:
    """A URL's own site type wins over any prefix."""
    site = Site()
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))

    run = audit(
        [Target(url=PAGE, site=SiteType.DEV)],
        make_fetcher(site, tmp_path),
        now=Clock(),
        prefixes=[BLOG_RULE],
    )

    (snapshot,) = run.snapshots
    assert (snapshot.extractor_id, snapshot.extractor_selection) == (
        "dev.article",
        ExtractorSelection.DECLARED,
    )


def test_a_prefix_rule_is_matched_against_the_url_that_answered(tmp_path: Path) -> None:
    """A redirect into the prefix counts; the page is what was read."""
    site = Site()
    site.add("https://short.example/p", redirect(PAGE))
    site.add(PAGE, respond(200, fixture("two-canonicals"), HTML))

    run = audit(
        [Target(url="https://short.example/p")],
        make_fetcher(site, tmp_path),
        now=Clock(),
        prefixes=[BLOG_RULE],
    )

    assert run.snapshots[0].extractor_selection is ExtractorSelection.PREFIX
