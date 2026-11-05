"""Tests for the store on the command line: recording, runs, history, and verify."""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fetch_support import FIXED_NOW, FakeResolver, Site, respond
from store_support import HTML, PAGE

from cernis import cli
from cernis import store as store_module
from cernis.cli import main
from cernis.fetch import FetchConfig, Fetcher
from cernis.model import RunError
from cernis.store import LedgerStore, StoreError


def serve(monkeypatch: pytest.MonkeyPatch, body: bytes = HTML) -> Site:
    """Make the CLI fetch a scripted web holding the test page.

    :param monkeypatch: Used to replace the CLI's fetcher.
    :param body: The page's body.
    :return: The scripted web.
    """
    site = Site()
    site.add(PAGE, respond(200, body, {"content-type": "text/html; charset=utf-8"}))

    def build(config: FetchConfig) -> Fetcher:
        return Fetcher(
            config,
            transport=httpx.MockTransport(site.handler),
            sleep=lambda seconds: None,
            now=lambda: FIXED_NOW,
            resolver=FakeResolver(),
        )

    monkeypatch.setattr(cli, "Fetcher", build)
    return site


def audit_args(tmp_path: Path, *extra: str) -> list[str]:
    """Build ``cernis audit`` arguments for the test page, with this test's store.

    :param tmp_path: The test's directory.
    :param *extra: More arguments.
    :return: The arguments.
    """
    return [
        "audit",
        PAGE,
        "--site-type",
        "owned",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--store",
        str(tmp_path / "store"),
        *extra,
    ]


def audit_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    """Record two runs, a second apart, and return their run ids.

    :param monkeypatch: Used to replace the fetcher and the run clock.
    :param tmp_path: The test's directory.
    :param capsys: Captures the output, which is discarded.
    :return: The run ids, in order.
    """
    serve(monkeypatch)
    ids: list[str] = []
    for hour in (12, 13):
        monkeypatch.setattr(cli, "_run_clock", _fixed(hour))
        assert main(audit_args(tmp_path, "--format", "json")) == 0
        ids.append(json.loads(capsys.readouterr().out)["run"]["id"])
    return ids


def _fixed(hour: int) -> object:
    """Return a run clock fixed at an hour of the test day, a second later each reading.

    :param hour: The hour.
    :return: The clock.
    """
    from store_support import START, clock

    return clock(START.replace(hour=hour))


# Recording a run


def test_a_run_is_recorded_and_its_tip_printed_and_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After a run: the tip on standard error, and in the report header, as in the anchor."""
    serve(monkeypatch)

    code = main(audit_args(tmp_path))

    captured = capsys.readouterr()
    assert code == 0
    anchor = json.loads(LedgerStore(tmp_path / "store").anchor_path.read_text(encoding="utf-8"))
    tip = f"tip {anchor['sequence']} {anchor['entry_hash']}"
    assert tip in captured.err
    assert f"Ledger: recorded, {tip}" in captured.out


def test_the_json_report_records_the_ledger_tip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON report's run metadata carries the ledger status and tip."""
    serve(monkeypatch)

    assert main(audit_args(tmp_path, "--format", "json")) == 0

    ledger = json.loads(capsys.readouterr().out)["run"]["ledger"]
    anchor = json.loads(LedgerStore(tmp_path / "store").anchor_path.read_text(encoding="utf-8"))
    assert ledger == {
        "status": "recorded",
        "tip": {"sequence": anchor["sequence"], "entry_hash": anchor["entry_hash"]},
        "reason": None,
        "checked_before": "VERIFIED",
    }


def test_the_store_defaults_to_a_git_ignored_directory(isolated_store: Path) -> None:
    """The default store is .cernis/store/, and .gitignore keeps .cernis/ out of the repository.

    :param isolated_store: The default store this test uses (see conftest.py).
    """
    gitignore = (Path(__file__).parent.parent / ".gitignore").read_text(encoding="utf-8")

    assert cli.build_parser().parse_args(["audit", PAGE]).store == isolated_store
    assert Path(".cernis/store") == store_module.DEFAULT_STORE_DIR
    assert ".cernis/" in gitignore.splitlines()


def test_two_runs_started_in_the_same_frozen_second_are_both_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run id's random suffix keeps them apart, so neither is refused."""
    serve(monkeypatch)
    ids: list[str] = []
    for _ in range(2):
        monkeypatch.setattr(cli, "_run_clock", _fixed(12))
        assert main(audit_args(tmp_path, "--format", "json")) == 0
        ids.append(json.loads(capsys.readouterr().out)["run"]["id"])

    assert ids[0] != ids[1]
    assert ids[0][:16] == ids[1][:16]
    assert main(["runs", "--store", str(tmp_path / "store"), "--format", "json"]) == 0
    assert [run["id"] for run in json.loads(capsys.readouterr().out)["runs"]] == ids


def test_runs_shows_each_runs_anchor_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that started with no anchor says so in cernis runs, from the ledger itself."""
    serve(monkeypatch)
    monkeypatch.setattr(cli, "_run_clock", _fixed(12))
    assert main(audit_args(tmp_path)) == 0
    LedgerStore(tmp_path / "store").anchor_path.unlink()
    monkeypatch.setattr(cli, "_run_clock", _fixed(13))
    assert main(audit_args(tmp_path)) == 0
    capsys.readouterr()

    assert main(["runs", "--store", str(tmp_path / "store"), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(["runs", "--store", str(tmp_path / "store")]) == 0
    markdown = capsys.readouterr().out

    assert [run["anchor_status"] for run in payload["runs"]] == ["empty", "missing"]
    assert "no anchor to check against" in markdown


def test_a_store_held_by_another_writer_stops_the_audit_before_fetching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second writer gets a clear error at once, and nothing is fetched."""
    site = serve(monkeypatch)

    with LedgerStore(tmp_path / "store").writer():
        code = main(audit_args(tmp_path))

    assert code == 2
    assert "another" in capsys.readouterr().err
    assert site.requests == []


def test_a_failed_write_is_reported_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report still goes out, saying the run was not recorded and why; never silence."""
    serve(monkeypatch)

    def refuse(self: object, run: object) -> object:
        raise StoreError("the disk is full")

    monkeypatch.setattr(cli, "_record", refuse)

    code = main(audit_args(tmp_path))

    captured = capsys.readouterr()
    assert code == 1
    assert "Ledger: not recorded: the disk is full" in captured.out
    assert "the disk is full" in captured.err


def test_a_failed_run_is_never_appended(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A run that cannot be assembled never reaches the store."""
    serve(monkeypatch)

    def broken(*args: object, **kwargs: object) -> object:
        raise RunError("Run '20261104T120000Z': finding id 'f-001' repeated")

    monkeypatch.setattr(cli, "audit", broken)

    with pytest.raises(RunError):
        main(audit_args(tmp_path))

    assert LedgerStore(tmp_path / "store").entries() == []


# cernis runs and cernis history


def test_runs_lists_the_stored_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Id, times, subjects, version, and findings per status, in Markdown and JSON."""
    ids = audit_twice(monkeypatch, tmp_path, capsys)

    assert main(["runs", "--store", str(tmp_path / "store")]) == 0
    markdown = capsys.readouterr().out
    assert main(["runs", "--store", str(tmp_path / "store"), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert markdown.startswith("# Stored runs")
    for run_id in ids:
        assert f"`{run_id}`" in markdown
    assert [run["id"] for run in payload["runs"]] == ids
    first = payload["runs"][0]
    assert first["subjects"] == [PAGE]
    assert set(first["counts"]) == {"observed", "recommendations", "not_determinable", "site"}
    assert first["cernis_version"]


def test_history_lists_each_runs_findings_for_the_url_by_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every run that audited the URL, each with its findings for it, keyed by finding key."""
    ids = audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")

    assert main(["history", PAGE, "--store", store, "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(["history", PAGE, "--store", store]) == 0
    markdown = capsys.readouterr().out

    assert [run["id"] for run in payload["runs"]] == ids
    first, second = (run["findings"] for run in payload["runs"])
    assert set(first) == set(second)
    assert all(len(key) == 64 for key in first)
    assert {"check_id", "status", "summary"} <= set(next(iter(first.values())))
    assert markdown.startswith(f"# History: {PAGE}")
    assert next(iter(first)) in markdown


def test_history_of_a_url_never_audited_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty history is an answer, not an error."""
    audit_twice(monkeypatch, tmp_path, capsys)

    code = main(["history", "https://elsewhere.example/", "--store", str(tmp_path / "store")])

    assert code == 0
    assert "No stored run audited" in capsys.readouterr().out


def _tamper(tmp_path: Path) -> None:
    """Edit the second ledger entry out of band.

    :param tmp_path: The test's directory.
    """
    connection = sqlite3.connect(LedgerStore(tmp_path / "store").ledger_path)
    try:
        connection.execute("DROP TRIGGER prevent_update_forensic_ledger")
        connection.execute(
            "UPDATE forensic_ledger SET sieved_content = sieved_content || ' ' WHERE id = 2"
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize("command", [["runs"], ["history", PAGE]])
def test_reading_a_tampered_store_reports_the_reason_and_uses_no_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    """A read that fails verification names the reason and sequence, and prints no runs."""
    audit_twice(monkeypatch, tmp_path, capsys)
    _tamper(tmp_path)

    code = main([*command, "--store", str(tmp_path / "store")])

    captured = capsys.readouterr()
    assert code == 1
    assert "BROKEN_LINK" in captured.err
    assert "sequence 3" in captured.err
    assert captured.out == ""


def test_reading_a_store_with_no_anchor_says_not_determinable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The chain still verifies on read; the missing anchor is named, never taken as passing."""
    ids = audit_twice(monkeypatch, tmp_path, capsys)
    LedgerStore(tmp_path / "store").anchor_path.unlink()

    code = main(["runs", "--store", str(tmp_path / "store"), "--format", "json"])

    captured = capsys.readouterr()
    assert code == 0
    assert "not determinable" in captured.err
    assert [run["id"] for run in json.loads(captured.out)["runs"]] == ids


# cernis store verify


def test_store_verify_passes_on_an_untouched_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole chain, checked against the anchor: verified, exit 0."""
    audit_twice(monkeypatch, tmp_path, capsys)

    code = main(["store", "verify", "--store", str(tmp_path / "store")])

    assert code == 0
    assert "Result: VERIFIED" in capsys.readouterr().out


def test_store_verify_reports_tampering_with_its_reason_and_sequence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An edited entry: FAILED, the SDK's reason code, the sequence, exit 1."""
    audit_twice(monkeypatch, tmp_path, capsys)
    _tamper(tmp_path)

    code = main(["store", "verify", "--store", str(tmp_path / "store")])

    assert code == 1
    assert "Result: FAILED: BROKEN_LINK at sequence 3" in capsys.readouterr().out


def test_store_verify_with_no_anchor_is_not_determinable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No anchor beside a non-empty ledger: not determinable, exit 3, never passing."""
    audit_twice(monkeypatch, tmp_path, capsys)
    LedgerStore(tmp_path / "store").anchor_path.unlink()

    code = main(["store", "verify", "--store", str(tmp_path / "store")])

    assert code == 3
    assert "Result: NOT DETERMINABLE" in capsys.readouterr().out


def test_store_verify_checks_an_expected_tip_given_on_the_command_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--expected-tip SEQUENCE:HASH, an anchor kept elsewhere, replaces the anchor file."""
    audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")
    anchor = json.loads(LedgerStore(tmp_path / "store").anchor_path.read_text(encoding="utf-8"))
    tip = f"{anchor['sequence']}:{anchor['entry_hash']}"
    beyond = f"{anchor['sequence'] + 1}:{anchor['entry_hash']}"

    assert main(["store", "verify", "--store", store, "--expected-tip", tip]) == 0
    capsys.readouterr()
    assert main(["store", "verify", "--store", store, "--expected-tip", beyond]) == 1
    assert "TIP_MISMATCH" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["12", "x:abc", "3:", ":abc"])
def test_a_malformed_expected_tip_is_refused(value: str) -> None:
    """The tip is SEQUENCE:HASH."""
    with pytest.raises(SystemExit) as raised:
        main(["store", "verify", "--expected-tip", value])

    assert raised.value.code == 2


# From audit aud_GN220m1Nam


def test_a_run_whose_anchor_cannot_be_written_says_recorded_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Audit S-f3: in the ledger, but unanchored; the report says both, and the exit is 1."""
    serve(monkeypatch)

    def refuse(self: LedgerStore, tip: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr(LedgerStore, "write_anchor", refuse)

    code = main(audit_args(tmp_path))

    captured = capsys.readouterr()
    assert code == 1
    assert "Ledger: recorded, tip " in captured.out
    assert "the anchor could not be written" in captured.out
    assert "read-only file system" in captured.err


def test_a_backend_failure_still_emits_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Audit O-f3: a database error after the audit is reported, never a lost report."""
    serve(monkeypatch)
    from sovereign_ledger import SovereignLedger

    def broken(self: object, *args: object, **kwargs: object) -> object:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(SovereignLedger, "verify_ledger", broken)

    code = main(audit_args(tmp_path))

    captured = capsys.readouterr()
    assert code == 1
    assert "Ledger: not recorded: " in captured.out
    assert "malformed" in captured.err


def test_store_verify_lists_runs_that_started_with_no_anchor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Audit O-f2 and S-f1: the gap in the chain is named by verify too, not only by runs."""
    serve(monkeypatch)
    monkeypatch.setattr(cli, "_run_clock", _fixed(12))
    assert main(audit_args(tmp_path)) == 0
    capsys.readouterr()
    LedgerStore(tmp_path / "store").anchor_path.unlink()
    monkeypatch.setattr(cli, "_run_clock", _fixed(13))
    assert main(audit_args(tmp_path, "--format", "json")) == 0
    second = json.loads(capsys.readouterr().out)["run"]["id"]

    code = main(["store", "verify", "--store", str(tmp_path / "store")])

    out = capsys.readouterr().out
    assert code == 0
    assert "Result: VERIFIED" in out
    assert f"Anchor gap: run {second} started with the anchor missing" in out


def test_an_uppercase_expected_tip_is_read_as_lowercase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Audit S-f11: a hash pasted in capitals is the same hash."""
    audit_twice(monkeypatch, tmp_path, capsys)
    anchor = json.loads(LedgerStore(tmp_path / "store").anchor_path.read_text(encoding="utf-8"))
    tip = f"{anchor['sequence']}:{anchor['entry_hash'].upper()}"

    code = main(["store", "verify", "--store", str(tmp_path / "store"), "--expected-tip", tip])

    assert code == 0


@pytest.mark.parametrize("value", [f"3:{'g' * 64}", "3:abc", f"0:{'a' * 64}"])
def test_an_expected_tip_must_be_a_sequence_and_a_sha256(value: str) -> None:
    """Audit S-f11: a sequence of at least 1 and 64 hex digits."""
    with pytest.raises(SystemExit) as raised:
        main(["store", "verify", "--expected-tip", value])

    assert raised.value.code == 2


def test_store_with_no_subcommand_is_a_usage_error() -> None:
    """Audit S-f11: cernis store alone names its subcommands and exits 2."""
    with pytest.raises(SystemExit) as raised:
        main(["store"])

    assert raised.value.code == 2
