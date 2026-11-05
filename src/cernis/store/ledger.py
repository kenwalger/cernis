"""The receipt store on sovereign-sdk-ledger 2.x (ADR-002, DESIGN.md section 5).

Cernis uses only the ledger's public API (claim C-5b): it imports names from
``sovereign_ledger`` itself, never an underscore name or a submodule, and
never opens the ledger's SQLite file. The store directory holds:

- ``ledger.db``, the ledger;
- ``ledger.db.tip.json``, the tip anchor: the last tip Cernis wrote, so a
  ledger cut short is caught (``TIP_MISMATCH``);
- ``ledger.db.lock``, held by the one writer while a command records a run.

Entries are unsigned: no signature is passed, so the ledger records each as
``UNSIGNED`` (DESIGN.md section 5, decision 2). The anchor guards against a
ledger cut short or changed out of band, not against someone who can
rewrite both files; a tip kept elsewhere (``cernis store verify
--expected-tip``) covers that.

Every ledger error is turned into a :class:`~cernis.store.base.StoreError`,
so a failure to record or read is always reported, never a traceback.
"""

import json
import logging
import os
import re
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from sovereign_ledger import (
    IdempotencyKeyConflictError,
    LedgerIntegrityError,
    LedgerTip,
    SovereignLedger,
    SovereignStorageError,
)

from cernis.model import Run
from cernis.store.base import (
    Recorded,
    StoreAnchorError,
    StoredEntry,
    StoreError,
    StoreIntegrityError,
    StoreLockedError,
    StoreTip,
    Verification,
    VerificationStatus,
    parse_entry,
    plan_appends,
    run_entries,
)

DEFAULT_STORE_DIR = Path(".cernis/store")
"""The store directory used when none is given, relative to the working directory."""

ANCHOR_FORMAT = "cernis-ledger-anchor"
"""The tip anchor file's format name."""

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

_LEDGER_ERRORS = (sqlite3.Error, SovereignStorageError, UnicodeError)
"""What a ledger call can raise for a failure of the store, not of Cernis."""

log = logging.getLogger(__name__)

if sys.platform == "win32":
    import msvcrt

    def _lock(file: BinaryIO) -> None:
        """Take an exclusive lock on the file's first byte, without waiting.

        :param file: The lock file.
        """
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(file: BinaryIO) -> None:
        """Release the lock.

        :param file: The lock file.
        """
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(file: BinaryIO) -> None:
        """Take an exclusive lock on the file, without waiting.

        :param file: The lock file.
        """
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(file: BinaryIO) -> None:
        """Release the lock.

        :param file: The lock file.
        """
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _anchor_problem(value: object) -> str | None:
    """Say what is wrong with an anchor file's content, if anything.

    :param value: The parsed JSON.
    :return: The problem, or ``None`` for a whole, well-formed anchor.
    """
    if not isinstance(value, dict):
        return "not a JSON object"
    if value.get("format") != ANCHOR_FORMAT or value.get("format_version") != 1:
        return f"not a {ANCHOR_FORMAT} version 1 file"
    sequence = value.get("sequence")
    if type(sequence) is not int or sequence < 1:
        return f"the sequence {sequence!r} is not a whole number of at least 1"
    entry_hash = value.get("entry_hash")
    if not isinstance(entry_hash, str) or not _SHA256_HEX.fullmatch(entry_hash):
        return f"the entry hash {entry_hash!r} is not 64 lowercase hex digits"
    return None


def _tip(tip: LedgerTip | None) -> StoreTip | None:
    """Convert the ledger's tip to Cernis's.

    :param tip: The ledger's tip, or ``None``.
    :return: The same tip, or ``None``.
    """
    return None if tip is None else StoreTip(sequence=tip.sequence, entry_hash=tip.entry_hash)


class LedgerStore:
    """A receipt store in a directory, on sovereign-sdk-ledger.

    :param directory: The store directory; created on the first write.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.ledger_path = directory / "ledger.db"
        self.anchor_path = directory / "ledger.db.tip.json"
        self.lock_path = directory / "ledger.db.lock"

    @contextmanager
    def _ledger(self) -> Iterator[SovereignLedger]:
        """Open the ledger.

        :yield: The open ledger, closed when the context exits.
        :raises StoreError: If the ledger cannot be opened.
        """
        try:
            ledger = SovereignLedger(str(self.ledger_path))
        except (SovereignStorageError, sqlite3.Error, OSError) as exc:
            raise StoreError(f"cannot open the ledger {self.ledger_path}: {exc}") from exc
        with ledger:
            yield ledger

    @contextmanager
    def writer(self) -> Iterator["_LedgerWriter"]:
        """Take the store's single writer, before anything is fetched.

        :yield: The writer, until the context exits.
        :raises StoreLockedError: If another process (or another writer in
            this one) is writing to the store.
        :raises StoreError: If the store directory cannot be made or used.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            lock = self.lock_path.open("a+b")
        except OSError as exc:
            raise StoreError(f"cannot use the store directory {self.directory}: {exc}") from exc
        try:
            _lock(lock)
        except OSError as exc:
            lock.close()
            raise StoreLockedError(
                f"another cernis command is writing to the store at {self.directory}; "
                "run this one when it has finished"
            ) from exc
        try:
            with self._ledger() as ledger:
                yield _LedgerWriter(self, ledger)
        finally:
            _unlock(lock)
            lock.close()

    def entries(self) -> list[StoredEntry]:
        """Read every entry back, each link verified from the start of the chain.

        The anchor is not checked here; :meth:`verify` checks it, and the
        reading commands call it first.

        :return: Cernis's entries, in sequence order; empty if there is no ledger.
        :raises StoreIntegrityError: If the chain fails verification. Nothing
            read is returned.
        :raises StoreError: If the ledger cannot be read.
        """
        if not self.ledger_path.exists():
            return []
        with self._ledger() as ledger:
            try:
                read = [
                    (entry.sequence, entry.sieved_content, entry.idempotency_key)
                    for entry in ledger.iter_entries()
                ]
            except LedgerIntegrityError as exc:
                raise StoreIntegrityError(
                    exc.sequence, exc.reason.name, f"reading {self.ledger_path}"
                ) from exc
            except _LEDGER_ERRORS as exc:
                raise StoreError(f"cannot read the ledger {self.ledger_path}: {exc}") from exc
        parsed = (parse_entry(sequence, content, key) for sequence, content, key in read)
        return [entry for entry in parsed if entry is not None]

    def read_anchor(self) -> tuple[StoreTip | None, str]:
        """Read the tip anchor beside the ledger.

        :return: The anchored tip, or ``None``, and a note saying why there is none.
        """
        if not self.anchor_path.exists():
            return None, f"there is no anchor file at {self.anchor_path}"
        try:
            value = json.loads(self.anchor_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, f"the anchor file {self.anchor_path} cannot be read ({exc})"
        problem = _anchor_problem(value)
        if problem is not None:
            return None, f"the anchor file {self.anchor_path} cannot be read ({problem})"
        return (
            StoreTip(sequence=value["sequence"], entry_hash=value["entry_hash"]),
            f"anchor {self.anchor_path}",
        )

    def write_anchor(self, tip: StoreTip) -> None:
        """Write the tip anchor atomically: a temporary file, then a rename.

        An :class:`OSError` from writing it reaches the caller.

        :param tip: The tip to anchor.
        """
        content = json.dumps(
            {
                "format": ANCHOR_FORMAT,
                "format_version": 1,
                "sequence": tip.sequence,
                "entry_hash": tip.entry_hash,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        temporary = self.anchor_path.with_name(self.anchor_path.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            file.write(content + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.anchor_path)

    def verify(self, expected: StoreTip | None = None) -> Verification:
        """Verify the whole chain against an anchor.

        :param expected: A tip to check against; ``None`` uses the anchor file.
        :return: Verified; failed, with the ledger's reason code and sequence;
            or not determinable, when a non-empty ledger has no anchor, or
            entries follow the anchor file's tip.
        :raises StoreError: If the ledger cannot be opened or read.
        """
        anchor: StoreTip | None
        if expected is not None:
            anchor, source = expected, "the expected tip given"
        else:
            anchor, source = self.read_anchor()
        try:
            return self._verify(anchor, source, from_file=expected is None)
        except _LEDGER_ERRORS as exc:
            raise StoreError(f"cannot verify the ledger {self.ledger_path}: {exc}") from exc

    def _verify(self, anchor: StoreTip | None, source: str, *, from_file: bool) -> Verification:
        """Verify the whole chain against an anchor, if there is one.

        :param anchor: The tip to check against, or ``None``.
        :param source: Where the anchor came from, for the note.
        :param from_file: Whether it is the anchor file, which Cernis rewrites
            after every run, so entries after it are not covered by it.
        :return: What verification found.
        """
        if not self.ledger_path.exists():
            if anchor is not None:
                return Verification(
                    status=VerificationStatus.FAILED,
                    entries_checked=0,
                    tip=None,
                    anchor=anchor,
                    failure_sequence=anchor.sequence,
                    failure_reason="LEDGER_MISSING",
                    note=f"{source} names entry {anchor.sequence}, but there is no ledger",
                )
            return Verification(
                status=VerificationStatus.VERIFIED,
                entries_checked=0,
                tip=None,
                anchor=None,
                note="the store is empty",
            )
        expected_tip = (
            None
            if anchor is None
            else LedgerTip(sequence=anchor.sequence, entry_hash=anchor.entry_hash)
        )
        with self._ledger() as ledger:
            report = ledger.verify_ledger(expected_tip=expected_tip)
        tip = _tip(report.tip)
        if not report.verified:
            reason = report.failure_reason.name if report.failure_reason else "FAILED"
            return Verification(
                status=VerificationStatus.FAILED,
                entries_checked=report.entries_checked,
                tip=tip,
                anchor=anchor,
                failure_sequence=report.failure_sequence,
                failure_reason=reason,
                note=f"verification failed: {reason} at sequence {report.failure_sequence}",
            )
        if from_file and anchor is not None and tip is not None and tip.sequence > anchor.sequence:
            beyond = tip.sequence - anchor.sequence
            return Verification(
                status=VerificationStatus.NOT_DETERMINABLE,
                entries_checked=report.entries_checked,
                tip=tip,
                anchor=anchor,
                note=(
                    f"the chain verified, but {beyond} entries after the anchored tip "
                    f"({anchor.sequence}) are not covered by {source}"
                ),
            )
        if anchor is None and report.entries_checked > 0:
            return Verification(
                status=VerificationStatus.NOT_DETERMINABLE,
                entries_checked=report.entries_checked,
                tip=tip,
                anchor=None,
                note=f"the chain verified, but {source}, so its tail cannot be checked",
            )
        return Verification(
            status=VerificationStatus.VERIFIED,
            entries_checked=report.entries_checked,
            tip=tip,
            anchor=anchor,
            note=f"the chain verified against {source}" if anchor else "the store is empty",
        )


class _LedgerWriter:
    """Records runs into a :class:`LedgerStore`, while holding its lock.

    :param store: The store.
    :param ledger: The open ledger.
    """

    def __init__(self, store: LedgerStore, ledger: SovereignLedger) -> None:
        self._store = store
        self._ledger = ledger

    def _recorded(self, run: Run) -> dict[str, str]:
        """Read the payload hash of every entry of this run already in the ledger.

        :param run: The run.
        :return: Payload hashes by idempotency key.
        :raises StoreIntegrityError: If the chain fails verification.
        :raises StoreError: If the ledger cannot be read.
        """
        prefix = f"cernis/{run.id}/"
        try:
            return {
                entry.idempotency_key: entry.payload_hash
                for entry in self._ledger.iter_entries()
                if entry.idempotency_key is not None and entry.idempotency_key.startswith(prefix)
            }
        except LedgerIntegrityError as exc:
            raise StoreIntegrityError(
                exc.sequence, exc.reason.name, f"run {run.id} was not recorded"
            ) from exc
        except _LEDGER_ERRORS as exc:
            raise StoreError(f"run {run.id} was not recorded: {exc}") from exc

    def _anchor_status(self, before: Verification) -> str:
        """Say what the check before this run found about the anchor.

        :param before: The verification made before writing; not failed.
        :return: ``verified``, ``missing``, ``unreadable``, ``behind``, or ``empty``.
        """
        if before.status is VerificationStatus.NOT_DETERMINABLE:
            if before.anchor is not None:
                return "behind"
            return "unreadable" if self._store.anchor_path.exists() else "missing"
        return "verified" if before.entries_checked else "empty"

    def record(self, run: Run) -> Recorded:
        """Append a completed run, then anchor the new tip.

        :param run: The run.
        :return: What was recorded.
        :raises StoreIntegrityError: If the ledger fails verification first;
            it takes no new entries then.
        :raises StoreAnchorError: If the run is in the ledger but its anchor
            could not be written.
        :raises StoreError: If another run used this run's id, or a write
            fails. Entries written before a failure stay in the ledger with no
            run record, so readers ignore them; recording the same run again
            (the same :class:`~cernis.model.Run`) completes it. A new command
            makes a new run, with a new id.
        """
        before = self._store.verify()
        if before.status is VerificationStatus.FAILED:
            raise StoreIntegrityError(
                before.failure_sequence,
                before.failure_reason or "FAILED",
                f"run {run.id} was not recorded",
            )
        prepared = run_entries(run, anchor_status=self._anchor_status(before))
        try:
            todo = plan_appends(run, prepared, self._recorded(run))
        except UnicodeError as exc:
            raise StoreError(f"run {run.id} was not recorded: {exc}") from exc
        timestamp = run.finished_at.isoformat()
        appended = 0
        for entry in todo:
            receipt = {"payload_hash": entry.payload_hash, "timestamp": timestamp}
            try:
                self._ledger.append_entry(
                    receipt, entry.content, idempotency_key=entry.idempotency_key
                )
            except IdempotencyKeyConflictError:
                log.debug("already recorded: %s", entry.idempotency_key)
                continue
            except (*_LEDGER_ERRORS, ValueError, TypeError) as exc:
                raise StoreError(f"run {run.id} was not recorded: {exc}") from exc
            appended += 1
        try:
            last = _tip(self._ledger.get_tip())
        except _LEDGER_ERRORS as exc:
            raise StoreError(
                f"run {run.id} was appended, but the tip cannot be read: {exc}"
            ) from exc
        assert last is not None  # the run record was just appended or found
        try:
            self._store.write_anchor(last)
        except OSError as exc:
            raise StoreAnchorError(
                last,
                f"run {run.id} is in the ledger at tip {last}, but its anchor "
                f"{self._store.anchor_path} could not be written: {exc}",
            ) from exc
        return Recorded(
            tip=last,
            appended=appended,
            already=len(prepared) - appended,
            checked_before=before,
        )
