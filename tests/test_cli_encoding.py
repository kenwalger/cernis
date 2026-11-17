"""Every command writes UTF-8, whatever the console's code page (Session 7).

On Windows, a redirected standard output takes the locale's code page
(cp1252 on most machines), so the ``·`` in a report arrived garbled. Each
subprocess test forces such an encoding with ``PYTHONIOENCODING`` and reads
the raw bytes, so it fails the same way on any platform.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from store_support import PAGE
from test_cli_store import audit_twice

from cernis import cli
from cernis.cli import main

MIDDLE_DOT = "·"
"""The separator in ``cernis runs`` and ``cernis history`` lines."""


def _run_redirected(arguments: list[str], encoding: str) -> subprocess.CompletedProcess[bytes]:
    """Run ``python -m cernis`` with standard output piped, in a given encoding.

    :param arguments: The command's arguments.
    :param encoding: What ``PYTHONIOENCODING`` asks the streams to use.
    :return: The finished process, its output as raw bytes.
    """
    environment = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8",)}
    environment["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, "-m", "cernis", *arguments],
        capture_output=True,
        env=environment,
        check=False,
    )


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
@pytest.mark.parametrize("command", ["runs", "history"])
def test_redirected_output_is_utf8_whatever_the_code_page(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    encoding: str,
) -> None:
    """``·`` arrives as its UTF-8 bytes, and the command does not fail on it."""
    audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")
    arguments = (
        [command, "--store", store] if command == "runs" else [command, PAGE, "--store", store]
    )

    result = _run_redirected(arguments, encoding)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert MIDDLE_DOT.encode("utf-8") in result.stdout
    result.stdout.decode("utf-8")


def test_store_verify_and_diff_write_utf8_when_redirected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other store commands write through the same reconfigured stream."""
    audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")

    for arguments in (["store", "verify", "--store", store], ["diff", PAGE, "--store", store]):
        result = _run_redirected(arguments, "ascii")
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        result.stdout.decode("utf-8")


@pytest.mark.parametrize("output_format", ["md", "json"])
@pytest.mark.parametrize("command", ["runs", "history", "diff"])
def test_runs_history_and_diff_write_to_a_file_with_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    output_format: str,
) -> None:
    """``--output`` writes what standard output would have shown, in UTF-8, and prints nothing."""
    audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")
    arguments = [command, "--store", store, "--format", output_format]
    if command != "runs":
        arguments[1:1] = [PAGE]
    target = tmp_path / f"out.{output_format}"

    assert main(arguments) == 0
    shown = capsys.readouterr().out
    assert main([*arguments, "--output", str(target)]) == 0

    assert capsys.readouterr().out == ""
    assert target.read_text(encoding="utf-8") == shown
    if output_format == "json":
        json.loads(target.read_text(encoding="utf-8"))


def test_an_output_file_that_cannot_be_written_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same rule as the auditing commands: the reason on standard error, exit 2."""
    audit_twice(monkeypatch, tmp_path, capsys)
    missing = tmp_path / "no-such-directory" / "out.md"

    code = main(["runs", "--store", str(tmp_path / "store"), "--output", str(missing)])

    assert code == 2
    assert "cannot write" in capsys.readouterr().err


def test_the_reconfigured_streams_keep_their_error_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reconfigure(encoding=...) alone resets errors to strict; stderr must keep its own."""
    stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="backslashreplace")
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "stdout", stdout)

    cli._use_utf8()

    assert (stderr.encoding, stderr.errors) == ("utf-8", "backslashreplace")
    assert (stdout.encoding, stdout.errors) == ("utf-8", "strict")
    print("cannot write \udcff", file=stderr)
