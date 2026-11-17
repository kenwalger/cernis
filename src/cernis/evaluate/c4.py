"""Claim C-4, evaluated mechanically over one stored run (DESIGN.md section 8).

C-4 says the three statuses are used honestly. Its four rules, fixed on
2026-11-17 before the run they were first applied to:

1. ``based_on``: every ``RECOMMENDATION`` has a non-empty ``based_on``, and
   every id in it names an ``OBSERVED`` finding in the same run.
2. ``no_promise``: every recommendation's text (its summary, the action, and
   its rationale) passes the no-promise test, with the same patterns the test
   suite uses (:func:`cernis.promises.find_outcome_language`, imported, never
   copied).
3. ``not_determinable``: every ``NOT_DETERMINABLE`` has a reason code and a
   question, and either evidence of an attempt or ``would_require``.
4. ``status_fields``: no finding carries a field that belongs to another
   status (``defect`` to ``OBSERVED``; ``rationale`` and ``based_on`` to
   ``RECOMMENDATION``; ``reason_code``, ``question``, and ``would_require`` to
   ``NOT_DETERMINABLE``), and every status is one of the three.

The rules read the stored records as the ledger holds them, never rebuilt
:class:`~cernis.model.Finding` objects: the model refuses to build a finding
that breaks these rules, so evaluating rebuilt findings could not find a
violation that reached the store. Model validation should make every
violation impossible; one found here is a validation bug as well as a
falsification.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cernis import __version__
from cernis.promises import find_outcome_language
from cernis.report.markdown import code, escape
from cernis.store.base import StoredEntry

C4_FORMAT = "cernis-evaluate-c4"
"""The JSON format name of ``cernis evaluate c4``."""

C4_FORMAT_VERSION = 1
"""The version of that JSON format."""

RULES: tuple[tuple[str, str], ...] = (
    (
        "based_on",
        "Every RECOMMENDATION has a non-empty based_on, and every id in it names an "
        "OBSERVED finding in the same run.",
    ),
    (
        "no_promise",
        "Every recommendation's summary and rationale pass the no-promise test.",
    ),
    (
        "not_determinable",
        "Every NOT_DETERMINABLE has a reason code and a question, and evidence of an "
        "attempt or would_require.",
    ),
    (
        "status_fields",
        "No finding carries a field that belongs to another status, and every status is "
        "OBSERVED, RECOMMENDATION, or NOT_DETERMINABLE.",
    ),
)
"""C-4's rules, by name, in order, with what each requires."""

_STATUSES = ("OBSERVED", "RECOMMENDATION", "NOT_DETERMINABLE")
_FIELD_OWNERS: tuple[tuple[str, str], ...] = (
    ("defect", "OBSERVED"),
    ("rationale", "RECOMMENDATION"),
    ("based_on", "RECOMMENDATION"),
    ("reason_code", "NOT_DETERMINABLE"),
    ("question", "NOT_DETERMINABLE"),
    ("would_require", "NOT_DETERMINABLE"),
)


class C4Error(Exception):
    """The run cannot be evaluated: it is not a complete run in the store."""


@dataclass(frozen=True, kw_only=True)
class Violation:
    """One finding that breaks one rule.

    :param rule: The rule's name.
    :param finding_id: The finding's id in the run.
    :param key: The finding's key.
    :param check_id: The finding's check.
    :param detail: What is wrong, in one sentence.
    """

    rule: str
    finding_id: str
    key: str
    check_id: str
    detail: str


@dataclass(frozen=True, kw_only=True)
class RuleResult:
    """One rule over every finding it applies to.

    :param rule: The rule's name.
    :param description: What the rule requires.
    :param checked: How many findings it applied to.
    :param violations: Every violation, in run order.
    """

    rule: str
    description: str
    checked: int
    violations: tuple[Violation, ...]


@dataclass(frozen=True, kw_only=True)
class C4Result:
    """C-4's rules over one run.

    :param run_id: The run.
    :param counts: Its findings per stored status value.
    :param rules: Each rule's result, in :data:`RULES` order.
    """

    run_id: str
    counts: Mapping[str, int]
    rules: tuple[RuleResult, ...]

    @property
    def held(self) -> bool:
        """Whether every rule held.

        :return: True when no rule has a violation.
        """
        return not any(rule.violations for rule in self.rules)


def _text(record: Mapping[str, object], name: str) -> str:
    """Read a text field of a stored record.

    :param record: The record.
    :param name: The field.
    :return: The value, or an empty string when it is absent or not text.
    """
    value = record.get(name)
    return value if isinstance(value, str) else ""


def _present(record: Mapping[str, object], name: str) -> bool:
    """Say whether a stored record carries a field with a value.

    :param record: The record.
    :param name: The field.
    :return: False for an absent field, ``None``, ``False``, an empty string,
        or an empty list, which is how a stored record writes a field it does
        not use; True for anything else, ``0`` included.
    """
    value = record.get(name)
    return not (value is None or value is False or value == "" or value == [])


def _attempted(record: Mapping[str, object]) -> bool:
    """Say whether a record's evidence shows an attempt.

    :param record: The record.
    :return: True when at least one evidence entry names the receipt of an
        attempt and where it looked; an empty entry shows nothing.
    """
    evidence = record.get("evidence")
    if not isinstance(evidence, list):
        return False
    return any(
        isinstance(item, dict) and _text(item, "receipt_id").strip() and _text(item, "location")
        for item in evidence
    )


def _violation(rule: str, record: Mapping[str, object], detail: str) -> Violation:
    """Build a violation of one rule by one finding.

    :param rule: The rule.
    :param record: The finding's stored record.
    :param detail: What is wrong.
    :return: The violation.
    """
    return Violation(
        rule=rule,
        finding_id=_text(record, "id"),
        key=_text(record, "key"),
        check_id=_text(record, "check_id"),
        detail=detail,
    )


def _based_on(records: Sequence[Mapping[str, object]]) -> RuleResult:
    """Rule 1: every recommendation rests on observed findings of its own run.

    :param records: The run's finding records.
    :return: The rule's result.
    """
    statuses: dict[str, str] = {}
    shared: set[str] = set()
    for r in records:
        finding_id = _text(r, "id")
        if finding_id in statuses:
            shared.add(finding_id)
        statuses[finding_id] = _text(r, "status")
    checked = 0
    found: list[Violation] = []
    for record in records:
        if _text(record, "status") != "RECOMMENDATION":
            continue
        checked += 1
        ids = record.get("based_on")
        if ids is not None and not isinstance(ids, list):
            found.append(_violation("based_on", record, "based_on is not a list."))
            continue
        if not ids:
            found.append(_violation("based_on", record, "based_on is empty or missing."))
            continue
        for item in ids:
            if not isinstance(item, str):
                found.append(
                    _violation(
                        "based_on",
                        record,
                        f"based_on names {item!r}, which is not a finding id (not text).",
                    )
                )
            elif not item.strip():
                found.append(_violation("based_on", record, "based_on names an empty id."))
            elif item not in statuses:
                found.append(
                    _violation("based_on", record, f"based_on names {item}, not in this run.")
                )
            elif item in shared:
                found.append(
                    _violation(
                        "based_on",
                        record,
                        f"based_on names {item}, which more than one finding in this run has.",
                    )
                )
            elif statuses[item] != "OBSERVED":
                found.append(
                    _violation(
                        "based_on",
                        record,
                        f"based_on names {item}, which is {statuses[item] or 'without a status'}"
                        ", not OBSERVED.",
                    )
                )
    return RuleResult(
        rule="based_on", description=RULES[0][1], checked=checked, violations=tuple(found)
    )


def _no_promise(records: Sequence[Mapping[str, object]]) -> RuleResult:
    """Rule 2: no recommendation text predicts an outcome.

    :param records: The run's finding records.
    :return: The rule's result.
    """
    checked = 0
    found: list[Violation] = []
    for record in records:
        if _text(record, "status") != "RECOMMENDATION":
            continue
        checked += 1
        for name in ("summary", "rationale"):
            value = record.get(name)
            if value is not None and not isinstance(value, str):
                found.append(
                    _violation(
                        "no_promise", record, f"its {name} is not text, so it cannot be checked."
                    )
                )
                continue
            phrases = find_outcome_language(_text(record, name))
            if phrases:
                quoted = ", ".join(f'"{phrase}"' for phrase in phrases)
                found.append(_violation("no_promise", record, f"its {name} contains {quoted}."))
    return RuleResult(
        rule="no_promise", description=RULES[1][1], checked=checked, violations=tuple(found)
    )


def _not_determinable(records: Sequence[Mapping[str, object]]) -> RuleResult:
    """Rule 3: every unanswered question says why, what, and what was tried or needed.

    :param records: The run's finding records.
    :return: The rule's result.
    """
    checked = 0
    found: list[Violation] = []
    for record in records:
        if _text(record, "status") != "NOT_DETERMINABLE":
            continue
        checked += 1
        for name in ("reason_code", "question"):
            if not _text(record, name).strip():
                found.append(_violation("not_determinable", record, f"{name} is missing."))
        if not _attempted(record) and not _text(record, "would_require").strip():
            found.append(
                _violation(
                    "not_determinable",
                    record,
                    "it has neither evidence of an attempt nor would_require.",
                )
            )
    return RuleResult(
        rule="not_determinable",
        description=RULES[2][1],
        checked=checked,
        violations=tuple(found),
    )


def _status_fields(records: Sequence[Mapping[str, object]]) -> RuleResult:
    """Rule 4: every field belongs to the finding's own status.

    :param records: The run's finding records.
    :return: The rule's result.
    """
    found: list[Violation] = []
    for record in records:
        status = _text(record, "status")
        if status not in _STATUSES:
            found.append(
                _violation("status_fields", record, f"its status {status!r} is not one of three.")
            )
            continue
        for name, owner in _FIELD_OWNERS:
            if owner != status and _present(record, name):
                found.append(
                    _violation(
                        "status_fields",
                        record,
                        f"a {status} finding carries {name}, which belongs to {owner}.",
                    )
                )
    return RuleResult(
        rule="status_fields",
        description=RULES[3][1],
        checked=len(records),
        violations=tuple(found),
    )


def evaluate_findings(run_id: str, records: Sequence[Mapping[str, object]]) -> C4Result:
    """Evaluate C-4's four rules over one run's finding records.

    :param run_id: The run.
    :param records: Its findings as stored, in run order.
    :return: The result.
    """
    counts: dict[str, int] = {}
    for record in records:
        status = _text(record, "status") or "(none)"
        counts[status] = counts.get(status, 0) + 1
    return C4Result(
        run_id=run_id,
        counts=counts,
        rules=(
            _based_on(records),
            _no_promise(records),
            _not_determinable(records),
            _status_fields(records),
        ),
    )


def evaluate_c4(entries: Sequence[StoredEntry], run_id: str) -> C4Result:
    """Evaluate C-4 over one complete run in the store.

    :param entries: Every entry, read back verified, in sequence order.
    :param run_id: The run.
    :return: The result.
    :raises C4Error: When the store holds no complete run with that id
        (no run record, so a reader ignores its entries).
    """
    if not any(e.kind == "run" and e.run_id == run_id for e in entries):
        raise C4Error(f"the store holds no complete run {run_id}")
    records = [e.record for e in entries if e.kind == "finding" and e.run_id == run_id]
    return evaluate_findings(run_id, records)


def _violation_as_dict(violation: Violation) -> dict[str, str]:
    """Represent a violation as JSON-ready data.

    :param violation: The violation.
    :return: Its fields.
    """
    return {
        "rule": violation.rule,
        "finding_id": violation.finding_id,
        "key": violation.key,
        "check_id": violation.check_id,
        "detail": violation.detail,
    }


def format_c4_json(result: C4Result) -> str:
    """Render ``cernis evaluate c4 --format json``.

    :param result: The result.
    :return: The JSON, with a trailing newline.
    """
    payload = {
        "format": C4_FORMAT,
        "format_version": C4_FORMAT_VERSION,
        "cernis_version": __version__,
        "run": result.run_id,
        "held": result.held,
        "counts": dict(sorted(result.counts.items())),
        "rules": [
            {
                "rule": rule.rule,
                "description": rule.description,
                "checked": rule.checked,
                "violations": [_violation_as_dict(v) for v in rule.violations],
            }
            for rule in result.rules
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def format_c4_markdown(result: C4Result) -> str:
    """Render ``cernis evaluate c4``.

    :param result: The result.
    :return: The Markdown, with a trailing newline.
    """
    counts = ", ".join(f"{status} {n}" for status, n in sorted(result.counts.items()))
    lines = [
        "# Claim C-4: the three statuses used honestly",
        "",
        f"Run: {code(result.run_id)}",
        f"Findings: {counts or 'none'}",
        "",
        "| Rule | Checked | Violations |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {rule.rule} | {rule.checked} | {len(rule.violations)} |" for rule in result.rules]
    lines.append("")
    if result.held:
        lines.append("Every rule held: no violations.")
    else:
        lines += ["## Violations", ""]
        for rule in result.rules:
            for v in rule.violations:
                lines.append(
                    f"- {rule.rule}: finding {code(v.finding_id)} ({escape(v.check_id)}), "
                    f"key {code(v.key)}: {escape(v.detail)}"
                )
    lines += ["", "## The rules", ""]
    lines += [f"{n}. {name}: {text}" for n, (name, text) in enumerate(RULES, start=1)]
    return "\n".join(lines) + "\n"
