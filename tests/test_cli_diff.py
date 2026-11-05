"""Tests for ``cernis diff``: defaults, errors, and both formats (DESIGN.md sections 5 and 7)."""

import json
import sqlite3
from pathlib import Path

import pytest
from store_support import HTML, PAGE
from test_cli_store import _fixed, audit_args, serve

from cernis import cli
from cernis.cli import main
from cernis.store import LedgerStore


def record_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bodies: list[bytes],
) -> list[str]:
    """Record one run per body, an hour apart, and return their ids.

    :param monkeypatch: Used to replace the fetcher and the run clock.
    :param tmp_path: The test's directory.
    :param capsys: Captures the output, which is discarded.
    :param bodies: The page's body in each run.
    :return: The run ids, in order.
    """
    ids = []
    for hour, body in enumerate(bodies, start=12):
        serve(monkeypatch, body)
        monkeypatch.setattr(cli, "_run_clock", _fixed(hour))
        assert main(audit_args(tmp_path, "--format", "json")) == 0
        ids.append(json.loads(capsys.readouterr().out)["run"]["id"])
    return ids


def diff(tmp_path: Path, *extra: str) -> int:
    """Run ``cernis diff`` on the test page with this test's store.

    :param tmp_path: The test's directory.
    :param *extra: More arguments.
    :return: The exit code.
    """
    return main(["diff", PAGE, "--store", str(tmp_path / "store"), *extra])


def test_two_runs_of_an_unchanged_page_say_so_plainly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No changes is a result: said in words, exit 0."""
    ids = record_runs(monkeypatch, tmp_path, capsys, [HTML, HTML])

    code = diff(tmp_path)

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith(f"# Diff: {PAGE}")
    assert "No changes between these runs." in out
    assert f"`{ids[0]}`" in out
    assert f"`{ids[1]}`" in out
    assert "Classifier: 1+h1" in out


def test_the_default_is_the_two_most_recent_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Three runs: the last two are compared."""
    ids = record_runs(monkeypatch, tmp_path, capsys, [HTML, HTML, HTML])

    assert diff(tmp_path, "--format", "json") == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "cernis-diff"
    assert (payload["runs"]["from"]["id"], payload["runs"]["to"]["id"]) == (ids[1], ids[2])
    assert payload["changed"] is False
    assert payload["page_change"] is None
    assert payload["finding_changes"] == []


def test_a_changed_page_is_classified_with_its_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The page change's class and evidence, then the finding changes, grouped by cause.

    The page is owned, so it has no article body: any change to it is
    UNCLASSIFIED, but the evidence still names the field that moved.
    """
    changed = HTML.replace(b"<title>A post</title>", b"<title>Another post</title>")
    ids = record_runs(monkeypatch, tmp_path, capsys, [HTML, changed])

    assert diff(tmp_path) == 0
    markdown = capsys.readouterr().out
    assert diff(tmp_path, "--from", ids[0], "--to", ids[1], "--format", "json") == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["changed"] is True
    assert payload["page_change"]["class"] == "UNCLASSIFIED"
    assert any("content_sha256" in r for r in payload["page_change"]["reasons"])
    assert [f["name"] for f in payload["page_change"]["fields"]] == ["title"]
    assert payload["page_change"]["fields"][0]["control"] == "AUTHOR"
    assert {c["cause"] for c in payload["finding_changes"]} == {"PAGE"}
    assert "## Page change: UNCLASSIFIED" in markdown
    assert "Head field title (AUTHOR)" in markdown
    assert "Cause: PAGE" in markdown
    assert "`peri.title` for" in markdown


def test_fewer_than_two_runs_says_so_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One run is nothing to compare."""
    record_runs(monkeypatch, tmp_path, capsys, [HTML])

    code = diff(tmp_path)

    captured = capsys.readouterr()
    assert code == 1
    assert "fewer than two" in captured.err
    assert captured.out == ""


def test_a_run_that_did_not_audit_the_url_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, naming the runs that did."""
    ids = record_runs(monkeypatch, tmp_path, capsys, [HTML, HTML])

    code = diff(tmp_path, "--from", "20260101T000000Z-000000")

    err = capsys.readouterr().err
    assert code == 2
    assert ids[0] in err
    assert ids[1] in err


def test_a_ledger_that_fails_verification_gives_no_diff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the failure, with its reason code and sequence."""
    record_runs(monkeypatch, tmp_path, capsys, [HTML, HTML])
    connection = sqlite3.connect(LedgerStore(tmp_path / "store").ledger_path)
    try:
        connection.execute("DROP TRIGGER prevent_update_forensic_ledger")
        connection.execute(
            "UPDATE forensic_ledger SET sieved_content = sieved_content || ' ' WHERE id = 2"
        )
        connection.commit()
    finally:
        connection.close()

    code = diff(tmp_path)

    captured = capsys.readouterr()
    assert code == 1
    assert "BROKEN_LINK" in captured.err
    assert captured.out == ""
