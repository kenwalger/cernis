"""Reading stored runs back: ``cernis runs`` and ``cernis history`` (DESIGN.md section 5).

Only complete runs are read: a run's entries count once its run record,
written last, is in the store. Nothing here compares runs; that is the
history diff, a later session's work.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from cernis import __version__
from cernis.report.markdown import code, escape
from cernis.store.base import StoredEntry
from cernis.urls import normalize_url

RUNS_FORMAT = "cernis-runs"
"""The JSON format name of ``cernis runs``."""

HISTORY_FORMAT = "cernis-history"
"""The JSON format name of ``cernis history``."""

LISTING_VERSION = 1
"""The version of both JSON listings. Adding a field does not change it."""

FINDING_FIELDS = (
    "check_id",
    "check_version",
    "target",
    "status",
    "defect",
    "actor",
    "summary",
    "reason_code",
)
"""The finding fields ``cernis history`` shows."""


@dataclass(frozen=True, kw_only=True)
class StoredRun:
    """A complete run read back from the store.

    :param id: The run id.
    :param started_at: When it started, ISO 8601 in UTC.
    :param finished_at: When it finished, ISO 8601 in UTC.
    :param cernis_version: The Cernis version that ran it.
    :param subjects: The URLs it audited.
    :param counts: Its findings per status, as the report counts them.
    :param anchor_status: What the check before the run found about the
        store's anchor: ``verified``, ``missing``, ``unreadable``, or ``empty``.
    :param findings: Its findings, by finding key.
    """

    id: str
    started_at: str
    finished_at: str
    cernis_version: str
    subjects: tuple[str, ...]
    counts: Mapping[str, int]
    anchor_status: str = ""
    findings: Mapping[str, Mapping[str, object]] = field(default_factory=dict)


ANCHOR_GAPS = ("missing", "unreadable", "behind")
"""The anchor statuses that mean the ledger before a run could not be checked."""


def anchor_gap(run: StoredRun) -> str:
    """Say in words that a run started without a usable anchor.

    :param run: A run whose ``anchor_status`` is one of :data:`ANCHOR_GAPS`.
    :return: One sentence, for ``cernis runs`` and ``cernis store verify``.
    """
    if run.anchor_status == "behind":
        why = "entries followed the anchored tip that no anchor covered"
    else:
        why = f"the anchor was {run.anchor_status}"
    return (
        f"run {run.id} started with the anchor {run.anchor_status}: {why}, so the ledger "
        "before it had no anchor to check against (not determinable)."
    )


def _text(record: Mapping[str, object], name: str) -> str:
    """Read a text field of a stored record.

    :param record: The record.
    :param name: The field.
    :return: The value, or an empty string.
    """
    value = record.get(name)
    return value if isinstance(value, str) else ""


def stored_runs(entries: Sequence[StoredEntry]) -> list[StoredRun]:
    """Gather the complete runs in a store, in the order they were recorded.

    :param entries: Every entry, verified, in sequence order.
    :return: One run per run record, with its findings by key.
    """
    findings: dict[str, dict[str, Mapping[str, object]]] = {}
    for entry in entries:
        if entry.kind == "finding":
            findings.setdefault(entry.run_id, {})[_text(entry.record, "key")] = entry.record
    runs: list[StoredRun] = []
    for entry in entries:
        if entry.kind != "run":
            continue
        record = entry.record
        subjects = record.get("subjects")
        counts = record.get("counts")
        runs.append(
            StoredRun(
                id=entry.run_id,
                started_at=_text(record, "started_at"),
                finished_at=_text(record, "finished_at"),
                cernis_version=_text(record, "cernis_version"),
                subjects=tuple(s for s in subjects if isinstance(s, str))
                if isinstance(subjects, list)
                else (),
                counts={k: v for k, v in counts.items() if isinstance(v, int)}
                if isinstance(counts, dict)
                else {},
                anchor_status=_text(record, "anchor_status"),
                findings=findings.get(entry.run_id, {}),
            )
        )
    return runs


def run_history(entries: Sequence[StoredEntry], url: str) -> list[StoredRun]:
    """Find every stored run that audited a URL, with its findings about it.

    :param entries: Every entry, verified, in sequence order.
    :param url: The URL, compared after Cernis's one URL normalization.
    :return: The runs, oldest first, each holding only the findings about ``url``.
    """
    wanted = normalize_url(url)
    history: list[StoredRun] = []
    for run in stored_runs(entries):
        if all(normalize_url(subject) != wanted for subject in run.subjects):
            continue
        about = {
            key: finding
            for key, finding in run.findings.items()
            if normalize_url(_text(finding, "subject_url")) == wanted
        }
        history.append(
            StoredRun(
                id=run.id,
                started_at=run.started_at,
                finished_at=run.finished_at,
                cernis_version=run.cernis_version,
                subjects=run.subjects,
                counts=run.counts,
                anchor_status=run.anchor_status,
                findings=about,
            )
        )
    return history


def _run_summary(run: StoredRun) -> dict[str, object]:
    """Represent a stored run's metadata as JSON-ready data.

    :param run: The run.
    :return: Its id, times, version, subjects, and counts.
    """
    return {
        "id": run.id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "cernis_version": run.cernis_version,
        "subjects": list(run.subjects),
        "counts": dict(run.counts),
        "anchor_status": run.anchor_status,
    }


def _counts_text(counts: Mapping[str, int]) -> str:
    """Show a run's counts in words.

    :param counts: Findings per status.
    :return: For example ``observed 30, recommendations 1, not determinable 4``.
    """
    return (
        f"observed {counts.get('observed', 0)}, "
        f"recommendations {counts.get('recommendations', 0)}, "
        f"not determinable {counts.get('not_determinable', 0)}"
    )


def format_runs_json(runs: Sequence[StoredRun], store: str) -> str:
    """Render ``cernis runs`` as JSON.

    :param runs: The stored runs.
    :param store: The store directory, for the record.
    :return: The JSON, with a trailing newline.
    """
    payload = {
        "format": RUNS_FORMAT,
        "format_version": LISTING_VERSION,
        "cernis_version": __version__,
        "store": store,
        "runs": [_run_summary(run) for run in runs],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def format_runs_markdown(runs: Sequence[StoredRun], store: str) -> str:
    """Render ``cernis runs`` as Markdown.

    :param runs: The stored runs.
    :param store: The store directory.
    :return: The listing, with a trailing newline.
    """
    lines = ["# Stored runs", "", f"Store: {escape(store)}", ""]
    if not runs:
        lines.append("No run is stored yet.")
    for run in runs:
        lines.append(
            f"- {code(run.id)}: started {run.started_at}, finished {run.finished_at} · "
            f"Cernis {escape(run.cernis_version)} · {_counts_text(run.counts)}"
        )
        lines += [f"  - {escape(subject)}" for subject in run.subjects]
        if run.anchor_status in ANCHOR_GAPS:
            lines.append(f"  - {anchor_gap(run)}")
    return "\n".join(lines) + "\n"


def format_history_json(url: str, history: Sequence[StoredRun], store: str) -> str:
    """Render ``cernis history`` as JSON.

    :param url: The URL asked about.
    :param history: The runs that audited it.
    :param store: The store directory.
    :return: The JSON, with a trailing newline.
    """
    payload = {
        "format": HISTORY_FORMAT,
        "format_version": LISTING_VERSION,
        "cernis_version": __version__,
        "store": store,
        "url": url,
        "runs": [
            {
                **_run_summary(run),
                "findings": {
                    key: {name: finding.get(name) for name in FINDING_FIELDS}
                    for key, finding in run.findings.items()
                },
            }
            for run in history
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def format_history_markdown(url: str, history: Sequence[StoredRun], store: str) -> str:
    """Render ``cernis history`` as Markdown.

    :param url: The URL asked about.
    :param history: The runs that audited it.
    :param store: The store directory.
    :return: The listing, with a trailing newline.
    """
    lines = [f"# History: {escape(url)}", "", f"Store: {escape(store)}", ""]
    if not history:
        lines.append("No stored run audited this URL.")
    for run in history:
        lines += [
            f"## Run {code(run.id)}",
            "",
            f"Started {run.started_at} · Cernis {escape(run.cernis_version)} · "
            f"{len(run.findings)} findings",
            "",
            "| Key | Check | Target | Status | Defect | Summary |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for key, finding in run.findings.items():
            cells = [
                code(key),
                code(_text(finding, "check_id")),
                escape(_text(finding, "target")),
                _text(finding, "status"),
                "yes" if finding.get("defect") is True else "",
                escape(_text(finding, "summary")),
            ]
            lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
