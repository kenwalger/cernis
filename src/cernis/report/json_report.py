"""The JSON report: the whole run, machine-readable, in a versioned format.

The report is one JSON object:

- ``format`` (``"cernis-report"``) and ``format_version`` (:data:`FORMAT_VERSION`);
- ``run``: ``id``, ``started_at``, ``finished_at`` (ISO 8601, UTC), and
  ``cernis_version``;
- ``checks``: the ``id`` and ``version`` of every check with a finding in the
  run, in registry order;
- ``subjects``: the audited URLs;
- ``counts``: the number of findings in each report section
  (``observed``, ``recommendations``, ``not_determinable``), and nothing
  else (principle 2: no scores or summary numbers);
- ``findings``: every finding, with every field, its derived ``key``, and
  its evidence;
- ``receipts`` and ``snapshots``: every receipt and snapshot, with every field.

Field names are the model's. A change that removes or renames a field, or
changes a value's meaning, bumps :data:`FORMAT_VERSION`; adding a field does
not.
"""

import json

from cernis.checks.registry import CHECKS
from cernis.model import Evidence, Finding, Receipt, Run, Snapshot, Status

FORMAT = "cernis-report"
"""The report format's name."""

FORMAT_VERSION = 1
"""The report format's version."""


def receipt_as_dict(receipt: Receipt) -> dict[str, object]:
    """Represent a receipt as JSON-ready data.

    :param receipt: The receipt.
    :return: Its fields, with the time in ISO 8601 and headers as an object.
    """
    return {
        "id": receipt.id,
        "requested_url": receipt.requested_url,
        "final_url": receipt.final_url,
        "redirect_chain": list(receipt.redirect_chain),
        "status_code": receipt.status_code,
        "error_kind": receipt.error_kind.value,
        "fetched_at": receipt.fetched_at.isoformat(),
        "body_sha256": receipt.body_sha256,
        "body_truncated_at": receipt.body_truncated_at,
        "headers": dict(receipt.headers),
        "cernis_version": receipt.cernis_version,
        "user_agent": receipt.user_agent,
    }


def snapshot_as_dict(snapshot: Snapshot) -> dict[str, object]:
    """Represent a snapshot as JSON-ready data.

    :param snapshot: The snapshot.
    :return: Its fields.
    """
    return {
        "receipt_id": snapshot.receipt_id,
        "extractor_id": snapshot.extractor_id,
        "extractor_version": snapshot.extractor_version,
        "extractor_selection": snapshot.extractor_selection.value,
        "content_sha256": snapshot.content_sha256,
        "head_sha256": snapshot.head_sha256,
        "frame_sha256": snapshot.frame_sha256,
    }


def _evidence_as_dict(evidence: Evidence) -> dict[str, object]:
    """Represent one piece of evidence as JSON-ready data.

    :param evidence: The evidence.
    :return: Its fields.
    """
    return {
        "receipt_id": evidence.receipt_id,
        "location": evidence.location,
        "observed": evidence.observed,
        "searched_for": evidence.searched_for,
    }


def finding_as_dict(finding: Finding) -> dict[str, object]:
    """Represent a finding as JSON-ready data.

    :param finding: The finding.
    :return: Every field, including the derived key.
    """
    return {
        "id": finding.id,
        "key": finding.key,
        "check_id": finding.check_id,
        "check_version": finding.check_version,
        "status": finding.status.value,
        "actor": finding.actor.value,
        "defect": finding.defect,
        "subject_url": finding.subject_url,
        "target": finding.target,
        "summary": finding.summary,
        "evidence": [_evidence_as_dict(item) for item in finding.evidence],
        "rationale": finding.rationale,
        "based_on": list(finding.based_on),
        "reason_code": finding.reason_code.value if finding.reason_code else None,
        "question": finding.question,
        "would_require": finding.would_require,
    }


def section_counts(run: Run) -> dict[str, int]:
    """Count the findings in each report section.

    :param run: The run.
    :return: ``observed``, ``recommendations``, and ``not_determinable``.
    """
    statuses = [finding.status for finding in run.findings]
    return {
        "observed": statuses.count(Status.OBSERVED),
        "recommendations": statuses.count(Status.RECOMMENDATION),
        "not_determinable": statuses.count(Status.NOT_DETERMINABLE),
    }


def checks_in(run: Run) -> list[tuple[str, str]]:
    """List the checks with a finding in the run, with their versions, in registry order.

    :param run: The run.
    :return: ``(check id, version)`` pairs.
    """
    used = {(finding.check_id, finding.check_version) for finding in run.findings}
    return [
        (spec.id, version) for spec in CHECKS for (cid, version) in sorted(used) if cid == spec.id
    ]


def report_json(run: Run) -> str:
    """Render a run as the JSON report.

    :param run: The run.
    :return: The report, indented, with a trailing newline.
    """
    payload = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "run": {
            "id": run.id,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "cernis_version": run.cernis_version,
        },
        "checks": [{"id": cid, "version": version} for cid, version in checks_in(run)],
        "subjects": list(run.subjects),
        "counts": section_counts(run),
        "findings": [finding_as_dict(finding) for finding in run.findings],
        "receipts": [receipt_as_dict(receipt) for receipt in run.receipts],
        "snapshots": [snapshot_as_dict(snapshot) for snapshot in run.snapshots],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
