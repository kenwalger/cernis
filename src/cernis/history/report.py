"""The ``cernis diff`` output, in Markdown and JSON (DESIGN.md sections 5 and 7).

The JSON is one object:

- ``format`` (``"cernis-diff"``) and ``format_version`` (:data:`DIFF_VERSION`);
- ``cernis_version`` that made the diff, and ``classifier_version``;
- ``url``, as asked for;
- ``runs``: ``from`` and ``to``, each with ``id``, ``started_at``,
  ``cernis_version``, ``classifier_version`` (``null`` for a run recorded
  before Session 6c), and ``anchor_status``;
- ``changed``: whether anything changed;
- ``page_change``: ``null``, or ``class``, ``reasons``, ``hashes`` (the
  snapshot hashes that changed), and ``fields`` (each changed head field's
  ``name``, ``control``, ``source``, ``before``, and ``after`` values);
- ``finding_changes``: each with ``key``, ``check_id``, ``target``, ``kind``
  (``appeared``, ``disappeared``, ``changed``), ``changed`` (the fields that
  differ), ``cause`` (``CHECKER``, ``PAGE``, ``RESOURCE``, ``UNKNOWN``),
  ``detail``, ``page_class``, ``resource_url``, and ``before`` and ``after``
  (``status``, ``defect``, ``reason_code``, and ``evidence`` without receipt
  ids; ``null`` for a side the key is missing from).

Adding a field does not change :data:`DIFF_VERSION`; removing or renaming one,
or changing a value's meaning, does.
"""

import json
from collections.abc import Mapping

from cernis import __version__
from cernis.history.classify import Cause, FindingChange, Record, RunDiff, RunView
from cernis.report.markdown import code, escape

DIFF_FORMAT = "cernis-diff"
"""The JSON format name of ``cernis diff``."""

DIFF_VERSION = 1
"""The version of the ``cernis diff`` JSON format."""

CAUSE_ORDER = (Cause.CHECKER, Cause.PAGE, Cause.RESOURCE, Cause.UNKNOWN)
"""The order the Markdown output groups finding changes in."""

MAX_SHOWN = 80
"""The most characters of a value the Markdown output shows."""


def _run_json(view: RunView) -> dict[str, object]:
    """Represent one side of the diff.

    :param view: The run.
    :return: Its id, start, versions, and anchor status.
    """
    return {
        "id": view.run_id,
        "started_at": view.text("started_at"),
        "cernis_version": view.text("cernis_version"),
        "classifier_version": view.record.get("classifier_version"),
        "anchor_status": view.text("anchor_status") or None,
    }


def _finding_json(finding: Record | None) -> dict[str, object] | None:
    """Represent a finding as compared: its state and evidence values.

    :param finding: The finding, or ``None``.
    :return: The compared fields, or ``None``.
    """
    if finding is None:
        return None
    evidence = finding.get("evidence")
    return {
        "status": finding.get("status"),
        "defect": finding.get("defect"),
        "reason_code": finding.get("reason_code"),
        "check_version": finding.get("check_version"),
        "evidence": [
            {
                "location": item.get("location"),
                "observed": item.get("observed"),
                "searched_for": item.get("searched_for"),
            }
            for item in (evidence if isinstance(evidence, list) else [])
            if isinstance(item, dict)
        ],
    }


def format_diff_json(diff: RunDiff) -> str:
    """Render a diff as JSON.

    :param diff: The diff.
    :return: The JSON, with a trailing newline.
    """
    page = diff.page_change
    payload = {
        "format": DIFF_FORMAT,
        "format_version": DIFF_VERSION,
        "cernis_version": __version__,
        "classifier_version": diff.classifier_version,
        "url": diff.url,
        "runs": {"from": _run_json(diff.before), "to": _run_json(diff.after)},
        "changed": not diff.empty,
        "page_change": None
        if page is None
        else {
            "class": page.change_class.value,
            "reasons": list(page.reasons),
            "hashes": list(page.hashes),
            "fields": [
                {
                    "name": field.name,
                    "control": field.control.value,
                    "source": field.source,
                    "before": list(field.before),
                    "after": list(field.after),
                }
                for field in page.fields
            ],
        },
        "finding_changes": [
            {
                "key": change.key,
                "check_id": change.check_id,
                "target": change.target,
                "kind": change.kind,
                "changed": list(change.changed),
                "cause": change.cause.value,
                "detail": change.detail,
                "page_class": None if change.page_class is None else change.page_class.value,
                "resource_url": change.resource_url,
                "before": _finding_json(change.before),
                "after": _finding_json(change.after),
            }
            for change in diff.finding_changes
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _short(text: str) -> str:
    """Shorten a value for the Markdown output.

    :param text: The value.
    :return: At most :data:`MAX_SHOWN` characters, with an ellipsis if cut.
    """
    return text if len(text) <= MAX_SHOWN else text[: MAX_SHOWN - 3] + "..."


def _state(finding: Record | None) -> str:
    """Describe a finding's state in a few words.

    :param finding: The finding, or ``None``.
    :return: For example ``OBSERVED, defect (404)``, or ``absent``.
    """
    if finding is None:
        return "absent"
    parts = [str(finding.get("status"))]
    if finding.get("defect") is True:
        parts.append("defect")
    if finding.get("reason_code"):
        parts.append(str(finding.get("reason_code")))
    evidence = finding.get("evidence")
    values = [
        str(item.get("observed"))
        for item in (evidence if isinstance(evidence, list) else [])
        if isinstance(item, dict) and item.get("observed") is not None
    ]
    text = ", ".join(parts)
    if values:
        text += f" ({escape(_short(', '.join(values)))})"
    return text


def _sentence(change: FindingChange, diff: RunDiff) -> str:
    """Say one finding change in a plain sentence.

    :param change: The change.
    :param diff: The diff it belongs to.
    :return: The sentence.
    """
    subject = escape(diff.url)
    if change.target:
        subject += f", target {escape(_short(change.target))}"
    what = f"{_state(change.before)} in run {code(diff.before.run_id)}, "
    what += f"{_state(change.after)} in run {code(diff.after.run_id)}"
    if change.kind == "changed":
        what += f" (changed: {', '.join(change.changed)})"
    cause = f"Cause: {change.cause}, {escape(change.detail)}."
    return f"- {code(change.check_id)} for {subject}: {what}. {cause}"


def _values(values: tuple[str, ...]) -> str:
    """Show a head field's values.

    :param values: The values.
    :return: Them, shortened, or ``absent``.
    """
    return escape(_short(" | ".join(values))) if values else "absent"


def format_diff_markdown(diff: RunDiff) -> str:
    """Render a diff as Markdown.

    :param diff: The diff.
    :return: The diff, with a trailing newline.
    """
    lines = [
        f"# Diff: {escape(diff.url)}",
        "",
        f"Classifier: {diff.classifier_version}",
        "",
        "| | Run | Started | Cernis | Anchor status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for side, view in (("From", diff.before), ("To", diff.after)):
        lines.append(
            f"| {side} | {code(view.run_id)} | {escape(view.text('started_at'))} | "
            f"{escape(view.text('cernis_version'))} | "
            f"{escape(view.text('anchor_status') or 'not recorded')} |"
        )
    lines.append("")
    if diff.empty:
        lines.append("No changes between these runs.")
        return "\n".join(lines) + "\n"
    page = diff.page_change
    if page is None:
        lines += ["## Page change: none", "", "The page's snapshot did not change.", ""]
    else:
        lines += [f"## Page change: {page.change_class}", ""]
        lines += [f"- {escape(reason)}" for reason in page.reasons]
        if page.hashes:
            lines.append(f"- Hashes changed: {', '.join(page.hashes)}")
        for field in page.fields:
            lines.append(
                f"- Head field {escape(field.name)} ({field.control}): {_values(field.before)} "
                f"in run {code(diff.before.run_id)}, {_values(field.after)} "
                f"in run {code(diff.after.run_id)}"
            )
        lines.append("")
    lines += [f"## Finding changes ({len(diff.finding_changes)})", ""]
    if not diff.finding_changes:
        lines += ["No finding changed.", ""]
    by_cause: Mapping[Cause, list[FindingChange]] = {
        cause: [c for c in diff.finding_changes if c.cause is cause] for cause in CAUSE_ORDER
    }
    for cause in CAUSE_ORDER:
        changes = by_cause[cause]
        if not changes:
            continue
        lines += [f"### Cause: {cause} ({len(changes)})", ""]
        lines += [_sentence(change, diff) for change in changes]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
