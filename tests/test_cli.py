"""Tests for the ``cernis`` command-line interface."""

import subprocess
import sys

import pytest

from cernis import __version__
from cernis.cli import REPOSITORY_URL, main


def test_version_flag_prints_name_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    """``cernis --version`` prints ``cernis <version>`` and exits 0."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"cernis {__version__}"


def test_no_arguments_prints_status_paragraph(capsys: pytest.CaptureFixture[str]) -> None:
    """``cernis`` with no arguments describes the project and returns 0."""
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "early development" in out
    assert "discoverability" in out
    assert REPOSITORY_URL in out


def test_module_entry_point_exits_zero() -> None:
    """``python -m cernis`` runs the CLI and exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "cernis"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert REPOSITORY_URL in result.stdout
