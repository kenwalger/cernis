"""Tests for the ledger store: the mapping, the tip anchor, tamper evidence, and C-5b.

The tamper tests change the ledger's SQLite file directly, with a separate
connection, after dropping the custody trigger, as the SDK's own tests do.
Only tests may do that: Cernis itself never opens the file (claim C-5b).
"""

import ast
import dataclasses
import hashlib
import inspect
import json
import sqlite3
from enum import StrEnum
from pathlib import Path

import pytest
import sovereign_ledger
from sovereign_ledger import SignatureStatus, SovereignLedger
from store_support import START, make_run

from cernis.store import (
    LedgerStore,
    StoreAnchorError,
    StoreError,
    StoreIntegrityError,
    StoreTip,
    VerificationStatus,
    stored_runs,
)

SRC = Path(__file__).parent.parent / "src" / "cernis"
STUB = Path(__file__).parent.parent / "typings" / "sovereign_ledger" / "__init__.pyi"


def recorded_store(tmp_path: Path, runs: int = 1) -> LedgerStore:
    """Make a ledger store holding ``runs`` runs, an hour apart.

    :param tmp_path: The test's directory.
    :param runs: How many runs to record.
    :return: The store.
    """
    store = LedgerStore(tmp_path / "store")
    for hour in range(runs):
        with store.writer() as writer:
            writer.record(make_run(tmp_path, START.replace(hour=12 + hour)))
    return store


def tamper(store: LedgerStore, *statements: str) -> None:
    """Change the ledger file out of band.

    :param store: The store.
    :param *statements: SQL to run, in one transaction.
    """
    connection = sqlite3.connect(store.ledger_path)
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def count_rows(store: LedgerStore) -> int:
    """Count the ledger's rows, tampered or not.

    :param store: The store.
    :return: The number of rows.
    """
    connection = sqlite3.connect(store.ledger_path)
    try:
        (count,) = connection.execute("SELECT COUNT(*) FROM forensic_ledger").fetchone()
    finally:
        connection.close()
    return int(count)


# The mapping


def test_each_entry_is_unsigned_and_mapped_as_designed(tmp_path: Path) -> None:
    """DESIGN.md section 5: the content's hash, the run's finish, event keys, no signature."""
    run = make_run(tmp_path)
    store = LedgerStore(tmp_path / "store")
    with store.writer() as writer:
        writer.record(run)

    with SovereignLedger(str(store.ledger_path)) as ledger:
        entries = list(ledger.iter_entries())

    assert entries
    for entry in entries:
        assert (entry.signature_status, entry.signature) == (SignatureStatus.UNSIGNED, None)
        assert entry.signer_key_id is None
        assert entry.payload_hash == hashlib.sha256(entry.sieved_content.encode()).hexdigest()
        assert entry.timestamp == run.finished_at.isoformat()
        kind = json.loads(entry.sieved_content)["kind"]
        assert entry.idempotency_key is not None
        assert entry.idempotency_key.startswith(f"cernis/{run.id}/{kind}/")


# The tip anchor


def test_the_tip_is_anchored_beside_the_ledger_after_each_run(tmp_path: Path) -> None:
    """The anchor holds the tip's sequence, entry hash, and when it was written, in UTC."""
    store = LedgerStore(tmp_path / "store")
    with store.writer() as writer:
        recorded = writer.record(make_run(tmp_path))

    anchor = json.loads(store.anchor_path.read_text(encoding="utf-8"))
    assert store.anchor_path.name == "ledger.db.tip.json"
    assert (anchor["sequence"], anchor["entry_hash"]) == (
        recorded.tip.sequence,
        recorded.tip.entry_hash,
    )
    assert anchor["recorded_at"].endswith("+00:00")
    assert sorted(path.name for path in store.directory.glob("*.tmp")) == []


def test_verification_passes_against_the_anchor(tmp_path: Path) -> None:
    """An untouched ledger verifies, and the report names the tip it found."""
    store = recorded_store(tmp_path, runs=2)

    verification = store.verify()

    assert verification.status is VerificationStatus.VERIFIED
    assert verification.anchor == verification.tip


def test_a_truncated_tail_fails_verification_with_tip_mismatch(tmp_path: Path) -> None:
    """Removing the last entries leaves a consistent chain; only the anchor catches it."""
    store = recorded_store(tmp_path, runs=2)
    anchor = store.verify().anchor
    assert anchor is not None

    tamper(
        store,
        "DROP TRIGGER prevent_delete_forensic_ledger",
        "DELETE FROM forensic_ledger WHERE id > (SELECT MAX(id) - 3 FROM forensic_ledger)",
    )

    verification = store.verify()
    assert verification.status is VerificationStatus.FAILED
    assert (verification.failure_reason, verification.failure_sequence) == (
        "TIP_MISMATCH",
        anchor.sequence,
    )


def test_a_deleted_entry_is_detected(tmp_path: Path) -> None:
    """Removing an entry from the middle breaks the chain where it was."""
    store = recorded_store(tmp_path)

    tamper(
        store,
        "DROP TRIGGER prevent_delete_forensic_ledger",
        "DELETE FROM forensic_ledger WHERE id = 2",
    )

    verification = store.verify()
    assert verification.status is VerificationStatus.FAILED
    assert verification.failure_reason in ("SEQUENCE_GAP", "BROKEN_LINK")
    assert verification.failure_sequence == 3


def test_an_edited_entry_fails_reads_and_verification_with_the_sdk_reason(
    tmp_path: Path,
) -> None:
    """A changed record is caught by the sweep, and a read of it raises, naming the reason."""
    store = recorded_store(tmp_path)

    tamper(
        store,
        "DROP TRIGGER prevent_update_forensic_ledger",
        "UPDATE forensic_ledger SET sieved_content = sieved_content || ' ' WHERE id = 2",
    )

    verification = store.verify()
    assert verification.status is VerificationStatus.FAILED
    assert (verification.failure_reason, verification.failure_sequence) == ("BROKEN_LINK", 3)
    with pytest.raises(StoreIntegrityError) as raised:
        store.entries()
    assert (raised.value.reason, raised.value.sequence) == ("BROKEN_LINK", 3)
    assert "BROKEN_LINK" in str(raised.value)


def test_a_missing_anchor_is_not_determinable(tmp_path: Path) -> None:
    """With no anchor beside a non-empty ledger, there is nothing to check the tail against."""
    store = recorded_store(tmp_path)
    store.anchor_path.unlink()

    verification = store.verify()

    assert verification.status is VerificationStatus.NOT_DETERMINABLE
    assert "anchor" in verification.note


def test_a_run_that_starts_with_no_anchor_records_the_gap_in_the_ledger(
    tmp_path: Path,
) -> None:
    """The missing anchor is permanent evidence in the chain, not only in one report."""
    store = recorded_store(tmp_path)
    store.anchor_path.unlink()

    with store.writer() as writer:
        writer.record(make_run(tmp_path, START.replace(hour=14)))

    assert store.verify().status is VerificationStatus.VERIFIED
    statuses = [run.anchor_status for run in stored_runs(store.entries())]
    assert statuses == ["empty", "missing"]


def test_a_run_on_an_anchored_store_records_the_anchor_verified(tmp_path: Path) -> None:
    """Each run record says what the check before it found."""
    store = recorded_store(tmp_path, runs=2)

    assert [run.anchor_status for run in stored_runs(store.entries())] == ["empty", "verified"]


def test_an_unreadable_anchor_is_recorded_as_such(tmp_path: Path) -> None:
    """An anchor file that cannot be read is not missing, and is not an anchor."""
    store = recorded_store(tmp_path)
    store.anchor_path.write_text("not json", encoding="utf-8")

    with store.writer() as writer:
        writer.record(make_run(tmp_path, START.replace(hour=14)))

    assert stored_runs(store.entries())[-1].anchor_status == "unreadable"


def test_an_empty_store_with_no_anchor_verifies(tmp_path: Path) -> None:
    """Nothing recorded, nothing to check: verified, with no entries."""
    verification = LedgerStore(tmp_path / "store").verify()

    assert (verification.status, verification.entries_checked) == (VerificationStatus.VERIFIED, 0)


def test_an_anchor_with_no_ledger_fails(tmp_path: Path) -> None:
    """The anchor says entries were recorded; a missing ledger is not an empty one."""
    store = recorded_store(tmp_path)
    for path in store.directory.glob("ledger.db*"):
        if path != store.anchor_path:
            path.unlink()

    assert store.verify().status is VerificationStatus.FAILED


def test_an_expected_tip_overrides_the_anchor(tmp_path: Path) -> None:
    """Cernis store verify --expected-tip: an anchor kept elsewhere is checked instead."""
    store = recorded_store(tmp_path)
    tip = store.verify().tip
    assert tip is not None

    later = StoreTip(sequence=tip.sequence + 5, entry_hash=tip.entry_hash)

    assert store.verify(later).failure_reason == "TIP_MISMATCH"
    assert store.verify(tip).status is VerificationStatus.VERIFIED


def test_a_ledger_that_fails_verification_takes_no_new_entries(tmp_path: Path) -> None:
    """A broken ledger is reported, never appended to or repaired."""
    store = recorded_store(tmp_path)
    tamper(
        store,
        "DROP TRIGGER prevent_update_forensic_ledger",
        "UPDATE forensic_ledger SET sieved_content = 'x' WHERE id = 1",
    )
    rows = count_rows(store)

    with store.writer() as writer, pytest.raises(StoreIntegrityError, match="BROKEN_LINK"):
        writer.record(make_run(tmp_path, START.replace(hour=14)))

    assert count_rows(store) == rows


# Failure behavior


def test_a_failed_write_is_raised_and_a_retry_completes_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that stops partway is an error, its run is invisible, and a retry finishes it."""
    run = make_run(tmp_path)
    store = LedgerStore(tmp_path / "store")
    original = SovereignLedger.append_entry
    calls = {"n": 0}

    def failing(self: SovereignLedger, *args: object, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 3:
            raise sqlite3.OperationalError("disk I/O error")
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SovereignLedger, "append_entry", failing)
    with store.writer() as writer, pytest.raises(StoreError, match="disk I/O error"):
        writer.record(run)
    assert stored_runs(store.entries()) == []

    monkeypatch.setattr(SovereignLedger, "append_entry", original)
    with store.writer() as writer:
        retried = writer.record(run)

    assert retried.already == 2
    assert [stored.id for stored in stored_runs(store.entries())] == [run.id]
    keys = [entry.idempotency_key for entry in store.entries()]
    assert len(keys) == len(set(keys))


# Claim C-5b: the public API only


def test_the_type_stub_matches_the_installed_package() -> None:
    """Every name in the stub is public in sovereign_ledger, with the same fields and members."""
    stub = ast.parse(STUB.read_text(encoding="utf-8"))
    names = [node.name for node in stub.body if isinstance(node, ast.ClassDef)]

    assert set(names) <= set(sovereign_ledger.__all__)
    for node in stub.body:
        if not isinstance(node, ast.ClassDef):
            continue
        real = getattr(sovereign_ledger, node.name)
        if dataclasses.is_dataclass(real):
            fields = [item.target.id for item in node.body if isinstance(item, ast.AnnAssign)]  # type: ignore[union-attr]
            assert fields == [field.name for field in dataclasses.fields(real)], node.name
        elif isinstance(real, type) and issubclass(real, StrEnum):
            members = {
                item.targets[0].id: ast.literal_eval(item.value)  # type: ignore[attr-defined]
                for item in node.body
                if isinstance(item, ast.Assign)
            }
            assert members == {member.name: member.value for member in real}, node.name
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                stub_params = [arg.arg for arg in (*item.args.args, *item.args.kwonlyargs)]
                real_params = list(inspect.signature(getattr(real, item.name)).parameters)
                assert stub_params == real_params, f"{node.name}.{item.name}"


def _python_files() -> list[Path]:
    """List Cernis's source files.

    :return: Every ``.py`` file under ``src/cernis``.
    """
    return sorted(SRC.rglob("*.py"))


def test_cernis_never_imports_a_private_name_from_the_ledger() -> None:
    """C-5b's first falsifier: no underscore name, and no module but the package itself."""
    offenses: list[str] = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            where = f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "sovereign_ledger"
            ):
                if node.module != "sovereign_ledger":
                    offenses.append(f"{where}: imports from {node.module}")
                offenses += [
                    f"{where}: imports {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("_") or alias.name not in sovereign_ledger.__all__
                ]
            elif isinstance(node, ast.Import):
                offenses += [
                    f"{where}: imports {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("sovereign_ledger.")
                ]
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "sovereign_ledger"
                and node.attr.startswith("_")
            ):
                offenses.append(f"{where}: uses sovereign_ledger.{node.attr}")

    assert offenses == []


def test_cernis_never_opens_a_sqlite_file_itself() -> None:
    """C-5b's second falsifier: Cernis reaches the ledger only through the SDK."""
    offenses: list[str] = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            where = f"{path.relative_to(SRC)}:{getattr(node, 'lineno', 0)}"
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "connect"
                and isinstance(node.value, ast.Name)
                and node.value.id == "sqlite3"
            ):
                offenses.append(f"{where}: sqlite3.connect")
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                offenses += [
                    f"{where}: from sqlite3 import {alias.name}"
                    for alias in node.names
                    if alias.name == "connect"
                ]

    assert offenses == []


# From audit aud_GN220m1Nam


def test_entries_after_the_anchored_tip_are_not_determinable(tmp_path: Path) -> None:
    """Audit G-f2: Cernis re-anchors after every run, so unanchored entries are not passed."""
    store = recorded_store(tmp_path)
    with SovereignLedger(str(store.ledger_path)) as ledger:
        content = "written by something else"
        ledger.append_entry(
            {
                "payload_hash": hashlib.sha256(content.encode()).hexdigest(),
                "timestamp": "2026-11-04T15:00:00+00:00",
            },
            content,
        )

    verification = store.verify()

    assert verification.status is VerificationStatus.NOT_DETERMINABLE
    assert "after the anchored tip" in verification.note
    with store.writer() as writer:
        writer.record(make_run(tmp_path, START.replace(hour=15)))
    assert stored_runs(store.entries())[-1].anchor_status == "behind"


def test_an_older_expected_tip_with_later_runs_verifies(tmp_path: Path) -> None:
    """A tip kept elsewhere from an earlier run: the later runs after it are expected."""
    store = LedgerStore(tmp_path / "store")
    with store.writer() as writer:
        first = writer.record(make_run(tmp_path, START))
    with store.writer() as writer:
        writer.record(make_run(tmp_path, START.replace(hour=13)))

    assert store.verify(first.tip).status is VerificationStatus.VERIFIED


@pytest.mark.parametrize(
    "anchor",
    [
        {"sequence": True, "entry_hash": "a" * 64},
        {"sequence": 1.9, "entry_hash": "a" * 64},
        {"sequence": -3, "entry_hash": "a" * 64},
        {"sequence": 5, "entry_hash": None},
        {"sequence": 5, "entry_hash": "A" * 64},
        {"sequence": 5, "entry_hash": "abc"},
        {"format": "something-else", "format_version": 1, "sequence": 5, "entry_hash": "a" * 64},
    ],
)
def test_a_malformed_anchor_is_unreadable_never_a_tip(
    tmp_path: Path, anchor: dict[str, object]
) -> None:
    """Audit S-f11: only a whole, well-formed anchor is checked against."""
    store = recorded_store(tmp_path)
    good = json.loads(store.anchor_path.read_text(encoding="utf-8"))
    store.anchor_path.write_text(json.dumps({**good, **anchor}), encoding="utf-8")

    tip, note = store.read_anchor()

    assert tip is None
    assert "cannot be read" in note


def test_a_failed_anchor_write_is_recorded_but_unanchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit S-f3: the run is in the ledger, so it is not reported as unrecorded."""
    store = LedgerStore(tmp_path / "store")

    def refuse(self: LedgerStore, tip: StoreTip) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(LedgerStore, "write_anchor", refuse)
    with store.writer() as writer, pytest.raises(StoreAnchorError) as raised:
        writer.record(make_run(tmp_path))

    assert raised.value.tip == store.verify().tip
    assert len(stored_runs(store.entries())) == 1


def test_a_backend_failure_while_recording_is_a_store_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit O-f3 and S-f5: a database error from any ledger call becomes a StoreError."""
    store = recorded_store(tmp_path)

    def broken(self: SovereignLedger, *args: object, **kwargs: object) -> object:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(SovereignLedger, "verify_ledger", broken)

    with store.writer() as writer, pytest.raises(StoreError, match="malformed"):
        writer.record(make_run(tmp_path, START.replace(hour=14)))
    with pytest.raises(StoreError, match="malformed"):
        store.verify()


def test_a_store_directory_that_cannot_be_made_is_a_store_error(tmp_path: Path) -> None:
    """Audit S-f5: an unusable store path is a clear error, not a traceback."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")

    with pytest.raises(StoreError, match="cannot"), LedgerStore(blocker / "store").writer():
        pass
