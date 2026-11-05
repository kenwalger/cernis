"""The receipt store's protocol, and the entries every store writes (ADR-002).

The rest of Cernis talks to a :class:`ReceiptStore` only. The protocol is what
Cernis needs, not what a backend offers: record a completed run, read every
entry back verified, and verify the store against an anchor.

A run is written as one entry per receipt, snapshot, and finding, then one
entry for the run record, which comes last and marks the run complete
(DESIGN.md section 5, "The receipt ledger"). Each entry's content is
canonical JSON, and its idempotency key names the event (the run and the
record), never the content, so a retry records nothing twice and a later run
of identical content is recorded again.
"""

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from cernis.history.fields import classifier_version
from cernis.model import Run
from cernis.report.json_report import (
    finding_as_dict,
    receipt_as_dict,
    section_counts,
    snapshot_as_dict,
)

ENTRY_SCHEMA_VERSION = 1
"""The entry schema's version.

Removing or renaming a field, or changing a value's meaning, bumps it.
"""

KINDS = ("receipt", "snapshot", "finding", "run")
"""The kinds of entry, in the order a run writes them."""

ANCHOR_STATUSES = ("verified", "missing", "unreadable", "behind", "empty")
"""What the check before a run found about the store's anchor, as its run record keeps it:
the anchor was found and the chain verified up to it; there was no anchor file
beside a non-empty ledger; there was one, but it could not be read; entries
followed the anchored tip that no anchor covered; or the store was empty,
with nothing to anchor."""

log = logging.getLogger(__name__)


class StoreError(Exception):
    """A run could not be recorded, or the store could not be read."""


class StoreLockedError(StoreError):
    """Another writer holds the store."""


class StoreAnchorError(StoreError):
    """A run is in the ledger, but its tip anchor could not be written.

    :param tip: The ledger's tip after the run.
    :param message: What went wrong.
    """

    def __init__(self, tip: "StoreTip", message: str) -> None:
        super().__init__(message)
        self.tip = tip


class StoreIntegrityError(StoreError):
    """The store failed verification, so none of what was read is used.

    :param sequence: The entry at which verification failed.
    :param reason: The reason code, such as ``BROKEN_LINK``.
    :param detail: What was being done, for the message.
    """

    def __init__(self, sequence: int | None, reason: str, detail: str) -> None:
        where = f" at sequence {sequence}" if sequence is not None else ""
        super().__init__(f"{detail}: the ledger failed verification: {reason}{where}")
        self.sequence = sequence
        self.reason = reason


@dataclass(frozen=True, kw_only=True)
class StoreTip:
    """The last entry of a store: its sequence number and entry hash.

    :param sequence: The entry's sequence number, from 1.
    :param entry_hash: The entry's hash, in lowercase hex.
    """

    sequence: int
    entry_hash: str

    def __str__(self) -> str:
        """Show the tip as Cernis prints it.

        :return: ``<sequence> <entry hash>``.
        """
        return f"{self.sequence} {self.entry_hash}"


class VerificationStatus(StrEnum):
    """What verifying a store found."""

    VERIFIED = "VERIFIED"
    """Every entry verified, and the anchor, if any, was found."""
    FAILED = "FAILED"
    """An entry failed verification, or the anchor was not found."""
    NOT_DETERMINABLE = "NOT_DETERMINABLE"
    """The chain verified, but there was no anchor to check its tail against."""


@dataclass(frozen=True, kw_only=True)
class Verification:
    """The result of verifying a store.

    :param status: What verification found.
    :param entries_checked: How many entries were examined.
    :param tip: The store's last entry, as stored; trustworthy only when verified.
    :param anchor: The tip it was checked against, or ``None`` if there was none.
    :param failure_sequence: The entry at which it failed, or ``None``.
    :param failure_reason: The reason code, such as ``TIP_MISMATCH``, or ``None``.
    :param note: One sentence saying what was found, for people.
    """

    status: VerificationStatus
    entries_checked: int
    tip: StoreTip | None
    anchor: StoreTip | None
    failure_sequence: int | None = None
    failure_reason: str | None = None
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class StoredEntry:
    """One entry read back from a store, verified.

    :param sequence: Its sequence number.
    :param kind: ``receipt``, ``snapshot``, ``finding``, or ``run``.
    :param run_id: The run it belongs to.
    :param record: The record, as the JSON report writes it.
    :param schema_version: The entry schema version it was written in.
    :param idempotency_key: The key it was written with.
    """

    sequence: int
    kind: str
    run_id: str
    record: Mapping[str, object]
    schema_version: int
    idempotency_key: str


@dataclass(frozen=True, kw_only=True)
class PreparedEntry:
    """An entry ready to be written: its key, content, and the content's hash.

    :param kind: ``receipt``, ``snapshot``, ``finding``, or ``run``.
    :param idempotency_key: ``cernis/<run id>/<kind>/<local id>``.
    :param content: The canonical JSON the entry stores.
    """

    kind: str
    idempotency_key: str
    content: str

    @property
    def payload_hash(self) -> str:
        """The SHA-256 of the content, in lowercase hex."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class Recorded:
    """What recording a run did.

    :param tip: The store's tip after the run.
    :param appended: How many entries were written.
    :param already: How many were already in the store (a retry).
    :param checked_before: What verifying the store found before writing.
    """

    tip: StoreTip
    appended: int
    already: int
    checked_before: Verification


@dataclass(frozen=True, kw_only=True)
class LedgerStatus:
    """Whether a run was recorded, for its report.

    :param recorded: Whether every entry of the run is in the store.
    :param tip: The store's tip after the run, when recorded.
    :param reason: Why it was not recorded, when it was not.
    :param checked_before: What verifying the store found before writing, if it ran.
    """

    recorded: bool
    tip: StoreTip | None = None
    reason: str | None = None
    checked_before: VerificationStatus | None = None


class RunWriter(Protocol):
    """Records runs, while it holds a store's single writer."""

    def record(self, run: Run) -> Recorded:
        """Record a completed run.

        :param run: The run; a :class:`~cernis.model.Run` is valid by construction.
        :return: What was recorded.
        """
        ...


class ReceiptStore(Protocol):
    """Where Cernis keeps every completed run (ADR-002)."""

    def writer(self) -> AbstractContextManager[RunWriter]:
        """Take the store's single writer.

        :return: A context that holds the writer until it exits.
        """
        ...

    def entries(self) -> list[StoredEntry]:
        """Read every entry back, verified.

        :return: The entries, in sequence order.
        """
        ...

    def verify(self, expected: StoreTip | None = None) -> Verification:
        """Verify the store.

        :param expected: A tip to check against instead of the store's own anchor.
        :return: What verification found.
        """
        ...


def canonical_json(value: object) -> str:
    """Serialize a value the one way Cernis stores it.

    :param value: JSON-ready data.
    :return: Sorted keys, no insignificant whitespace, non-ASCII kept as is.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def idempotency_key(run_id: str, kind: str, local_id: str) -> str:
    """Name one event: one record of one run.

    :param run_id: The run's id.
    :param kind: The kind of entry.
    :param local_id: The record's id within the run (``run`` for the run record).
    :return: ``cernis/<run id>/<kind>/<local id>``.
    """
    return f"cernis/{run_id}/{kind}/{local_id}"


def _entry(run_id: str, kind: str, local_id: str, record: Mapping[str, object]) -> PreparedEntry:
    """Prepare one entry.

    :param run_id: The run's id.
    :param kind: The kind of entry.
    :param local_id: The record's id within the run.
    :param record: The record.
    :return: The entry.
    """
    content = canonical_json(
        {"cernis_entry": ENTRY_SCHEMA_VERSION, "kind": kind, "run_id": run_id, "record": record}
    )
    return PreparedEntry(
        kind=kind, idempotency_key=idempotency_key(run_id, kind, local_id), content=content
    )


def run_entries(run: Run, *, anchor_status: str) -> list[PreparedEntry]:
    """Prepare every entry of a run, the run record last.

    :param run: The run.
    :param anchor_status: What the check before writing found about the
        store's anchor (:data:`ANCHOR_STATUSES`). It goes in the run record,
        so a run that started with no anchor stays on record in the chain.
    :return: One entry per receipt, snapshot, and finding, then the run record.
    :raises ValueError: If ``anchor_status`` is not one of :data:`ANCHOR_STATUSES`.
    """
    if anchor_status not in ANCHOR_STATUSES:
        raise ValueError(f"anchor_status must be one of {ANCHOR_STATUSES}, got {anchor_status!r}")
    entries = [_entry(run.id, "receipt", r.id, receipt_as_dict(r)) for r in run.receipts]
    entries += [
        _entry(run.id, "snapshot", s.receipt_id, snapshot_as_dict(s)) for s in run.snapshots
    ]
    entries += [_entry(run.id, "finding", f.id, finding_as_dict(f)) for f in run.findings]
    record: dict[str, object] = {
        "id": run.id,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
        "cernis_version": run.cernis_version,
        "subjects": list(run.subjects),
        "pairs": [{"original": pair.original, "copy": pair.copy} for pair in run.pairs],
        "sources": [
            {"kind": source.kind, "query": source.query, "listed": list(source.listed)}
            for source in run.sources
        ],
        "counts": section_counts(run),
        "anchor_status": anchor_status,
        "classifier_version": classifier_version(),
        "entries": {
            "receipt": len(run.receipts),
            "snapshot": len(run.snapshots),
            "finding": len(run.findings),
        },
    }
    entries.append(_entry(run.id, "run", "run", record))
    return entries


def plan_appends(
    run: Run, prepared: Sequence[PreparedEntry], recorded: Mapping[str, str]
) -> list[PreparedEntry]:
    """Decide which of a run's entries to write, given those already recorded.

    A run record already recorded means the run is complete. It is never
    compared with the new one: its ``anchor_status`` is the first write's, and
    a retry, made after that write anchored the store, would see a different
    one. Every other entry must then be recorded already, with the same
    content: nothing is ever added under a completed run's id.

    :param run: The run, for messages.
    :param prepared: The run's entries.
    :param recorded: The payload hash of every entry of this run already in the
        store, by idempotency key.
    :return: The entries still to write, in order.
    :raises StoreError: If an entry's key is recorded with different content,
        or the run is complete and this one has an entry it did not: another
        run reused this run's id, so nothing of this one is written.
    """
    complete = any(entry.kind == "run" and entry.idempotency_key in recorded for entry in prepared)
    todo: list[PreparedEntry] = []
    for entry in prepared:
        known = recorded.get(entry.idempotency_key)
        if entry.kind == "run" and known is not None:
            log.debug("run already recorded: %s", entry.idempotency_key)
        elif known is None and not complete:
            todo.append(entry)
        elif known != entry.payload_hash:
            raise StoreError(
                f"run id {run.id} is already in the store with different content "
                f"({entry.idempotency_key}): another run used the same id, so this one "
                "was not recorded"
            )
        else:
            log.debug("already recorded: %s", entry.idempotency_key)
    return todo


def parse_entry(sequence: int, content: str, key: str | None) -> StoredEntry | None:
    """Read a stored entry's content back.

    :param sequence: The entry's sequence number.
    :param content: Its stored content.
    :param key: Its idempotency key.
    :return: The entry, or ``None`` if it was not written by Cernis.
    :raises StoreError: If it is a Cernis entry Cernis cannot read.
    """
    if key is None or not key.startswith("cernis/"):
        return None
    try:
        value = json.loads(content)
    except ValueError as exc:
        raise StoreError(f"entry {sequence} ({key}) is not JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("cernis_entry") != ENTRY_SCHEMA_VERSION:
        raise StoreError(f"entry {sequence} ({key}) is not in entry schema {ENTRY_SCHEMA_VERSION}")
    kind, run_id, record = value.get("kind"), value.get("run_id"), value.get("record")
    if kind not in KINDS or not isinstance(run_id, str) or not isinstance(record, dict):
        raise StoreError(f"entry {sequence} ({key}) is malformed")
    return StoredEntry(
        sequence=sequence,
        kind=kind,
        run_id=run_id,
        record=record,
        schema_version=ENTRY_SCHEMA_VERSION,
        idempotency_key=key,
    )
