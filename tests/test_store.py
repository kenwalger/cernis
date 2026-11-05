"""Tests for the ReceiptStore protocol (ADR-002), against both implementations."""

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
from store_support import PAGE, START, make_run

from cernis.history.fields import classifier_version
from cernis.model import Run
from cernis.report.json_report import section_counts
from cernis.store import (
    ENTRY_SCHEMA_VERSION,
    LedgerStore,
    MemoryStore,
    PreparedEntry,
    ReceiptStore,
    StoreError,
    StoreLockedError,
    StoreTip,
    run_entries,
    run_history,
    stored_runs,
)
from cernis.store.base import plan_appends

StoreFactory = Callable[[Path], ReceiptStore]
"""Makes a fresh store in a directory."""

STORES: dict[str, StoreFactory] = {
    "memory": lambda path: MemoryStore(),
    "ledger": lambda path: LedgerStore(path / "store"),
}


@pytest.fixture(params=sorted(STORES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ReceiptStore:
    """Give each test a fresh store of each kind.

    :param request: The fixture request, naming the kind.
    :param tmp_path: The test's directory.
    :return: The store.
    """
    factory: StoreFactory = STORES[request.param]
    return factory(tmp_path)


def record(store: ReceiptStore, run: Run) -> None:
    """Record one run with the store's writer.

    :param store: The store.
    :param run: The run.
    """
    with store.writer() as writer:
        writer.record(run)


def kinds(store: ReceiptStore) -> Counter[str]:
    """Count the store's entries by kind.

    :param store: The store.
    :return: The counts.
    """
    return Counter(entry.kind for entry in store.entries())


def test_a_run_is_recorded_as_its_receipts_snapshots_findings_and_run_record(
    store: ReceiptStore, tmp_path: Path
) -> None:
    """One entry per record, the run record last, each in the entry schema."""
    run = make_run(tmp_path)

    record(store, run)

    entries = store.entries()
    assert kinds(store) == {
        "receipt": len(run.receipts),
        "snapshot": len(run.snapshots),
        "finding": len(run.findings),
        "run": 1,
    }
    assert entries[-1].kind == "run"
    assert {entry.run_id for entry in entries} == {run.id}
    assert all(entry.schema_version == ENTRY_SCHEMA_VERSION for entry in entries)


def test_page_bodies_are_never_stored(store: ReceiptStore, tmp_path: Path) -> None:
    """Receipts carry the body's hash, never the body."""
    record(store, make_run(tmp_path))

    for entry in store.entries():
        assert "Unchanged text" not in str(entry.record)


def test_a_stored_run_reads_back_with_its_counts(store: ReceiptStore, tmp_path: Path) -> None:
    """Cernis runs: id, times, subjects, version, and findings per status."""
    run = make_run(tmp_path)
    record(store, run)

    (stored,) = stored_runs(store.entries())

    assert (stored.id, stored.started_at, stored.finished_at) == (
        run.id,
        run.started_at.isoformat(),
        run.finished_at.isoformat(),
    )
    assert stored.subjects == run.subjects
    assert stored.cernis_version == run.cernis_version
    assert stored.counts == section_counts(run)


def test_two_runs_that_observe_identical_content_are_two_observations(
    store: ReceiptStore, tmp_path: Path
) -> None:
    """The same facts on a later run are recorded again, as a new observation."""
    first = make_run(tmp_path, START)
    second = make_run(tmp_path, START.replace(hour=13))
    assert [r.body_sha256 for r in first.receipts] == [r.body_sha256 for r in second.receipts]

    record(store, first)
    record(store, second)

    assert kinds(store)["receipt"] == len(first.receipts) + len(second.receipts)
    assert [stored.id for stored in stored_runs(store.entries())] == [first.id, second.id]


def test_retrying_a_run_records_each_entry_once(store: ReceiptStore, tmp_path: Path) -> None:
    """Writing the same run again (a retry after a crash) adds nothing."""
    run = make_run(tmp_path)
    record(store, run)
    before = len(store.entries())

    with store.writer() as writer:
        again = writer.record(run)

    assert len(store.entries()) == before
    assert (again.appended, again.already) == (0, before)


def test_a_reused_run_id_with_different_content_is_refused_whole(
    store: ReceiptStore, tmp_path: Path
) -> None:
    """Two runs that started in the same second share a run id; the second is refused."""
    record(store, make_run(tmp_path, START, b"<html><body>one</body></html>"))
    before = store.entries()

    with store.writer() as writer, pytest.raises(StoreError, match="run id"):
        writer.record(make_run(tmp_path, START, b"<html><body>two</body></html>"))

    assert store.entries() == before


def test_a_retry_after_the_anchor_was_written_is_still_one_run(
    store: ReceiptStore, tmp_path: Path
) -> None:
    """The run record's anchor status is the first write's; a retry does not conflict with it."""
    run = make_run(tmp_path)
    record(store, run)
    record(store, make_run(tmp_path, START.replace(hour=13)))

    with store.writer() as writer:
        again = writer.record(run)

    assert again.appended == 0
    assert [stored.id for stored in stored_runs(store.entries())].count(run.id) == 1


def test_a_second_writer_is_refused(store: ReceiptStore, tmp_path: Path) -> None:
    """One writer at a time: the second gets a clear error, never a shared store."""
    second = store if isinstance(store, MemoryStore) else LedgerStore(tmp_path / "store")

    with store.writer(), pytest.raises(StoreLockedError, match="another"), second.writer():
        pass


def test_the_writer_is_released_after_use(store: ReceiptStore, tmp_path: Path) -> None:
    """Once the first writer is done, the next one may write."""
    with store.writer():
        pass

    record(store, make_run(tmp_path))

    assert kinds(store)["run"] == 1


def test_history_lists_each_run_with_its_findings_for_the_url(
    store: ReceiptStore, tmp_path: Path
) -> None:
    """Cernis history: every run that audited the URL, its findings by key."""
    first = make_run(tmp_path, START)
    second = make_run(tmp_path, START.replace(hour=13))
    record(store, first)
    record(store, second)

    history = run_history(store.entries(), "https://BLOG.example.com/a-post")

    assert [stored.id for stored in history] == [first.id, second.id]
    assert set(history[0].findings) == {f.key for f in first.findings if f.subject_url == PAGE}
    assert set(history[0].findings) == set(history[1].findings)


def test_history_of_a_url_never_audited_is_empty(store: ReceiptStore, tmp_path: Path) -> None:
    """No run audited it, so there is nothing to list."""
    record(store, make_run(tmp_path))

    assert run_history(store.entries(), "https://elsewhere.example/") == []


def test_entries_are_canonical_json_keyed_by_the_event(tmp_path: Path) -> None:
    """Sorted keys, no spaces, a schema version; keys name the run and the record."""
    run = make_run(tmp_path)

    prepared = run_entries(run, anchor_status="empty")

    keys = [entry.idempotency_key for entry in prepared]
    assert keys[0] == f"cernis/{run.id}/receipt/{run.receipts[0].id}"
    assert keys[-1] == f"cernis/{run.id}/run/run"
    assert len(set(keys)) == len(keys)
    for entry in prepared:
        parsed = json.loads(entry.content)
        assert entry.content == json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert parsed["cernis_entry"] == ENTRY_SCHEMA_VERSION
        assert entry.payload_hash == hashlib.sha256(entry.content.encode("utf-8")).hexdigest()
    assert prepared[0].content.startswith('{"cernis_entry":1,"kind":"receipt","record":{')


def test_a_completed_run_id_reused_with_new_entries_is_refused() -> None:
    """Audit O-f1: entries the completed run did not have are never added under its id."""
    prepared = [
        PreparedEntry(kind="receipt", idempotency_key="cernis/r/receipt/r-001", content="a"),
        PreparedEntry(kind="receipt", idempotency_key="cernis/r/receipt/r-002", content="b"),
        PreparedEntry(kind="run", idempotency_key="cernis/r/run/run", content="run-2"),
    ]
    recorded = {
        "cernis/r/receipt/r-001": prepared[0].payload_hash,
        "cernis/r/run/run": PreparedEntry(
            kind="run", idempotency_key="cernis/r/run/run", content="run-1"
        ).payload_hash,
    }

    with pytest.raises(StoreError, match="run id"):
        plan_appends(make_run_stub("r"), prepared, recorded)


def test_a_completed_run_retried_unchanged_adds_nothing() -> None:
    """A retry of a completed run matches every entry, whatever its run record says now."""
    prepared = [
        PreparedEntry(kind="receipt", idempotency_key="cernis/r/receipt/r-001", content="a"),
        PreparedEntry(kind="run", idempotency_key="cernis/r/run/run", content="run-now"),
    ]
    recorded = {
        "cernis/r/receipt/r-001": prepared[0].payload_hash,
        "cernis/r/run/run": "an earlier run record's hash",
    }

    assert plan_appends(make_run_stub("r"), prepared, recorded) == []


def test_the_memory_store_refuses_an_expected_tip_before_the_first_entry() -> None:
    """Audit G-f5: sequence 0 or less is never a tip, so it can never match."""
    store = MemoryStore()

    for sequence in (0, -1):
        verification = store.verify(StoreTip(sequence=sequence, entry_hash="x"))
        assert verification.failure_reason == "TIP_MISMATCH"


def make_run_stub(run_id: str) -> Run:
    """Return a run whose only use is its id, for plan_appends' messages.

    :param run_id: The id.
    :return: An object with that id.
    """

    class Stub:
        """Stands in for a run."""

        id = run_id

    return Stub()  # type: ignore[return-value]


def test_the_run_record_names_the_classifier_version(tmp_path: Path) -> None:
    """A classifier change between two runs is then a CHECKER change in their diff."""
    record = json.loads(run_entries(make_run(tmp_path), anchor_status="empty")[-1].content)

    assert record["record"]["classifier_version"] == classifier_version()
