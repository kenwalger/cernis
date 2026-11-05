"""An in-memory receipt store, for tests (ADR-002).

It keeps the ledger store's rules for what is written (one writer at a
time, entries keyed by the event, a run refused whole when its id is
reused), so tests of the code above the protocol run without a file. It has
no anchor file and nothing outside the process can change it, so it never
reports a missing anchor or a failed verification of its own; those paths
are tested on the ledger store.
"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from cernis.model import Run
from cernis.store.base import (
    PreparedEntry,
    Recorded,
    StoredEntry,
    StoreLockedError,
    StoreTip,
    Verification,
    VerificationStatus,
    parse_entry,
    plan_appends,
    run_entries,
)

_GENESIS = hashlib.sha256(b"cernis-memory-store").hexdigest()


class MemoryStore:
    """A receipt store held in a list."""

    def __init__(self) -> None:
        self._entries: list[tuple[PreparedEntry, str]] = []
        self._writing = False

    @contextmanager
    def writer(self) -> Iterator["_MemoryWriter"]:
        """Take the store's single writer.

        :yield: The writer, until the context exits.
        :raises StoreLockedError: If another writer holds the store.
        """
        if self._writing:
            raise StoreLockedError("another writer holds the in-memory store")
        self._writing = True
        try:
            yield _MemoryWriter(self)
        finally:
            self._writing = False

    def entries(self) -> list[StoredEntry]:
        """Read every entry back.

        :return: The entries, in sequence order.
        """
        found = (
            parse_entry(number, entry.content, entry.idempotency_key)
            for number, (entry, _) in enumerate(self._entries, start=1)
        )
        return [entry for entry in found if entry is not None]

    def tip(self) -> StoreTip | None:
        """Return the last entry's tip.

        :return: The tip, or ``None`` when empty.
        """
        if not self._entries:
            return None
        return StoreTip(sequence=len(self._entries), entry_hash=self._entries[-1][1])

    def verify(self, expected: StoreTip | None = None) -> Verification:
        """Verify the store, which nothing outside this process can change.

        :param expected: A tip that must be in the store.
        :return: Verified, unless ``expected`` is not in the store.
        """
        tip = self.tip()
        if expected is not None and (
            expected.sequence < 1
            or expected.sequence > len(self._entries)
            or self._entries[expected.sequence - 1][1] != expected.entry_hash
        ):
            return Verification(
                status=VerificationStatus.FAILED,
                entries_checked=len(self._entries),
                tip=tip,
                anchor=expected,
                failure_sequence=expected.sequence,
                failure_reason="TIP_MISMATCH",
                note="the expected tip is not in the store",
            )
        return Verification(
            status=VerificationStatus.VERIFIED,
            entries_checked=len(self._entries),
            tip=tip,
            anchor=expected,
            note="the in-memory store verified",
        )

    def _append(self, entry: PreparedEntry) -> None:
        """Append one entry, chaining its hash to the last.

        :param entry: The entry.
        """
        parent = self._entries[-1][1] if self._entries else _GENESIS
        digest = hashlib.sha256(f"{parent}\x00{entry.content}".encode()).hexdigest()
        self._entries.append((entry, digest))


class _MemoryWriter:
    """Records runs into a :class:`MemoryStore`.

    :param store: The store.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def record(self, run: Run) -> Recorded:
        """Record a completed run.

        A :class:`~cernis.store.base.StoreError` from
        :func:`~cernis.store.base.plan_appends` (another run already used this
        run's id) reaches the caller, and nothing is appended.

        :param run: The run.
        :return: What was recorded.
        """
        before = self._store.verify()
        prepared = run_entries(run, anchor_status="verified" if before.entries_checked else "empty")
        prefix = f"cernis/{run.id}/"
        recorded = {
            entry.idempotency_key: entry.payload_hash
            for entry, _ in self._store._entries
            if entry.idempotency_key.startswith(prefix)
        }
        todo = plan_appends(run, prepared, recorded)
        for entry in todo:
            self._store._append(entry)
        tip = self._store.tip()
        assert tip is not None  # a run always has at least its run record
        return Recorded(
            tip=tip, appended=len(todo), already=len(prepared) - len(todo), checked_before=before
        )
