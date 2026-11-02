"""The Markdown report, for people (DESIGN.md section 7).

The header names the run, the Cernis version, and the version of each check
used, then each subject and how it was read. Three sections follow, each
with a plain count and nothing else (principle 2): **Observed**,
**Recommendations**, and **Not determinable (non liquet)**. With more than
one subject, each section is split by subject.

- An observed finding shows ``DEFECT`` only when it is one, then the actor,
  the check id, and the target, then its summary and its evidence.
- A recommendation shows its action, ``Why:`` its rationale, and ``Based on:``
  each finding it rests on as that finding's check id and summary, never a
  bare id.
- Not-determinable findings that share a subject, a reason, and the same
  evidence (one page Cernis could not read) are shown together, listing
  each question.

Evidence values are shown in code spans, whitespace collapsed and cut at
:data:`MAX_VALUE` characters; the JSON report has them whole. Text taken
from a page is escaped so it cannot become Markdown or HTML.
"""

import re
from itertools import groupby

from cernis.model import Evidence, Finding, Run, Snapshot, Status
from cernis.report.json_report import checks_in, section_counts

MAX_VALUE = 160
"""The most characters of an evidence value the Markdown report shows."""

_ESCAPE = re.compile(r"([\\`*<>\[\]])")


def escape(text: str) -> str:
    """Escape text so Markdown shows it as written.

    :param text: Text that may come from a page.
    :return: The text with Markdown and HTML punctuation backslash-escaped.
    """
    return _ESCAPE.sub(r"\\\1", text)


def code(text: str) -> str:
    """Put text in a code span that its own backticks cannot close.

    :param text: The text.
    :return: The code span.
    """
    if not text:
        return "` `"
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padded = f" {text} " if text.startswith("`") or text.endswith("`") else text
    return f"{fence}{padded}{fence}"


def _value(text: str) -> str:
    """Shorten an evidence value for reading.

    :param text: The value.
    :return: The value with whitespace collapsed, cut at :data:`MAX_VALUE`
        characters with a note of the full length.
    """
    flat = " ".join(text.split())
    if len(flat) <= MAX_VALUE:
        return code(flat)
    return f"{code(flat[:MAX_VALUE])}... ({len(flat)} characters)"


def _evidence_line(item: Evidence) -> str:
    """Render one piece of evidence.

    :param item: The evidence.
    :return: One line.
    """
    if item.observed is None:
        found = f"searched for {escape(item.searched_for or '')}, found none"
    else:
        found = _value(item.observed)
    return f"  Evidence: {code(item.location)}: {found} (receipt {item.receipt_id})"


def _observed(finding: Finding) -> list[str]:
    """Render an observed finding.

    :param finding: The finding.
    :return: Its lines.
    """
    label = " · ".join(
        part
        for part in (
            "DEFECT" if finding.defect else "",
            finding.actor.value,
            finding.check_id,
            escape(finding.target),
        )
        if part
    )
    return [f"- {label}", f"  {escape(finding.summary)}", *map(_evidence_line, finding.evidence)]


def _recommendation(finding: Finding, by_id: dict[str, Finding]) -> list[str]:
    """Render a recommendation.

    :param finding: The recommendation.
    :param by_id: Every finding in the run, by id.
    :return: Its lines.
    """
    based = "; ".join(
        f"{by_id[ref].check_id} ({escape(by_id[ref].summary)})" for ref in finding.based_on
    )
    return [
        f"- {escape(finding.summary)}",
        f"  Why: {escape(finding.rationale or '')}",
        f"  Based on: {based}",
    ]


def _lower_first(text: str) -> str:
    """Lowercase a sentence's first letter, to list it inside another sentence.

    :param text: The sentence, such as a question.
    :return: The text with its first character lowercased.
    """
    return text[:1].lower() + text[1:]


def _not_determinable(group: list[Finding]) -> list[str]:
    """Render not-determinable findings that share a subject, reason, and evidence.

    :param group: The findings.
    :return: Their lines.
    """
    first = group[0]
    reason = first.reason_code.value if first.reason_code else ""
    if len(group) == 1:
        lines = [
            f"- {escape(first.question or '')}.",
            f"  Reason: {reason}. {escape(first.summary)}",
        ]
    else:
        why = first.summary.split(" is not determinable: ", 1)[-1]
        questions = "; ".join(escape(_lower_first(f.question or "")) for f in group)
        lines = [
            f"- The page could not be read: {escape(why)}",
            f"  Reason: {reason}. Not determinable: {questions}.",
        ]
    return lines + [_evidence_line(item) for item in first.evidence]


def _snapshot_of(run: Run, subject: str) -> Snapshot | None:
    """Find the snapshot of a subject's page.

    :param run: The run.
    :param subject: The subject URL.
    :return: The snapshot whose receipt requested the subject, or ``None`` if
        the page was not read whole.
    """
    requested = {receipt.id: receipt.requested_url for receipt in run.receipts}
    for snap in run.snapshots:
        if requested.get(snap.receipt_id) == subject:
            return snap
    return None


def _how_read(run: Run, subject: str) -> str:
    """Say how a subject's page was read.

    :param run: The run.
    :param subject: The subject URL.
    :return: The extractor and its selection, or why the page was not read.
    """
    snap = _snapshot_of(run, subject)
    if snap is not None:
        return (
            f"read whole (receipt {snap.receipt_id}); extractor {snap.extractor_id} "
            f"{snap.extractor_version}, {snap.extractor_selection.value}"
        )
    codes = sorted(
        {
            f.reason_code.value
            for f in run.findings
            if f.subject_url == subject
            and f.reason_code is not None
            and f.status is Status.NOT_DETERMINABLE
            and not f.check_id.startswith("epi.")
        }
    )
    return f"not read ({', '.join(codes)})" if codes else "not read"


def _subject_lines(run: Run) -> list[str]:
    """Describe each pair and each subject, and how each page was read.

    :param run: The run.
    :return: The lines.
    """
    lines: list[str] = []
    for number, pair in enumerate(run.pairs, start=1):
        lines.append(f"- Pair {number}: original {escape(pair.original)}; copy {escape(pair.copy)}")
    for subject in run.subjects:
        lines.append(f"- {escape(subject)}: {_how_read(run, subject)}")
    return lines


def _page_title(run: Run, subject: str) -> str | None:
    """Return a subject page's title, if it was read.

    :param run: The run.
    :param subject: The subject URL.
    :return: The title, whitespace collapsed, or ``None``.
    """
    for finding in run.findings:
        if (
            finding.check_id == "peri.title"
            and finding.status is Status.OBSERVED
            and finding.subject_url == subject
        ):
            observed = finding.evidence[0].observed
            if observed and observed.strip():
                return " ".join(observed.split())
    return None


def _title(run: Run) -> str:
    """Choose the report's heading.

    :param run: The run.
    :return: ``Cernis audit: <title>`` for one page, or one pair (the
        original's title), with a title; else ``Cernis audit``.
    """
    if len(run.subjects) == 1:
        found = _page_title(run, run.subjects[0])
    elif len(run.pairs) == 1 and len(run.subjects) == 2:
        found = _page_title(run, run.pairs[0].original) or _page_title(run, run.pairs[0].copy)
    else:
        found = None
    return f"Cernis audit: {escape(found)}" if found else "Cernis audit"


_PAIR_CHECK = "epi.pair.canonical"


def _groups(run: Run) -> list[tuple[str | None, list[tuple[str | None, str, bool]]]]:
    """Arrange the subjects for the report: each pair as one subject, then the rest.

    :param run: The run.
    :return: ``(heading, parts)`` per group, each part ``(heading, subject,
        pair findings)``: the subject whose findings it shows, and whether it
        shows that subject's pair-check findings rather than its page
        findings. A page in several pairs is shown with the first.
    """
    groups: list[tuple[str | None, list[tuple[str | None, str, bool]]]] = []
    shown: set[str] = set()
    for pair in run.pairs:
        parts: list[tuple[str | None, str, bool]] = []
        for role, url in (("Original", pair.original), ("Copy", pair.copy)):
            if url not in shown:
                parts.append((f"{role}: {escape(url)}", url, False))
                shown.add(url)
        parts.append(("The pair", pair.copy, True))
        heading = f"Pair: {escape(pair.copy)} (copy of {escape(pair.original)})"
        groups.append((heading, parts))
    for subject in run.subjects:
        if subject not in shown:
            groups.append((escape(subject), [(None, subject, False)]))
    return groups


def report_markdown(run: Run) -> str:
    """Render a run as the Markdown report.

    :param run: The run.
    :return: The report, with a trailing newline.
    """
    counts = section_counts(run)
    by_id = {finding.id: finding for finding in run.findings}
    checks = " · ".join(f"{cid} {version}" for cid, version in checks_in(run))
    lines = [f"# {_title(run)}", ""]
    if len(run.pairs) == 1:
        lines += [
            f"Copy: {escape(run.pairs[0].copy)}",
            f"Original: {escape(run.pairs[0].original)}",
        ]
    lines += [
        f"Run: {run.id} · Cernis {run.cernis_version}",
        f"Started: {run.started_at.isoformat()} · Finished: {run.finished_at.isoformat()}",
        f"Checks: {checks or 'none'}",
        "",
        "Subjects:",
        "",
        *_subject_lines(run),
    ]
    sections = (
        ("Observed", Status.OBSERVED, counts["observed"]),
        ("Recommendations", Status.RECOMMENDATION, counts["recommendations"]),
        ("Not determinable (non liquet)", Status.NOT_DETERMINABLE, counts["not_determinable"]),
    )
    groups = _groups(run)
    several = len(groups) > 1 or bool(run.pairs)
    for heading, status, count in sections:
        lines += ["", f"## {heading} ({count})"]
        if count == 0:
            lines += ["", "None."]
            continue
        for group_heading, parts in groups:
            rendered_parts: list[list[str]] = []
            for part_heading, subject, pair_part in parts:
                chosen = [
                    f
                    for f in run.findings
                    if f.status is status
                    and f.subject_url == subject
                    and (f.check_id == _PAIR_CHECK) is pair_part
                ]
                if not chosen:
                    continue
                body: list[str] = []
                if part_heading is not None:
                    body += ["", f"#### {part_heading}"]
                body += _render(chosen, status, by_id)
                rendered_parts.append(body)
            if not rendered_parts:
                continue
            if several and group_heading is not None:
                lines += ["", f"### {group_heading}"]
            for body in rendered_parts:
                lines += body
    return "\n".join(lines) + "\n"


def _render(chosen: list[Finding], status: Status, by_id: dict[str, Finding]) -> list[str]:
    """Render one part's findings in one section.

    :param chosen: The findings, all with ``status``.
    :param status: The section's status.
    :param by_id: Every finding in the run, by id.
    :return: The lines.
    """
    lines: list[str] = []
    if status is Status.NOT_DETERMINABLE:
        groups = [
            list(group) for _, group in groupby(chosen, key=lambda f: (f.reason_code, f.evidence))
        ]
        for group in groups:
            lines += ["", *_not_determinable(group)]
        return lines
    for finding in chosen:
        rendered = (
            _observed(finding) if status is Status.OBSERVED else _recommendation(finding, by_id)
        )
        lines += ["", *rendered]
    return lines
