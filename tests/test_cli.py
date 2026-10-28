"""Tests for the ``cernis`` command-line interface."""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from cernis import __version__
from cernis.checks.registry import CHECKS
from cernis.cli import REPOSITORY_URL, main

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_flag_prints_name_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    """``cernis --version`` prints ``cernis <version>`` and exits 0."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"cernis {__version__}"


def test_package_version_matches_pyproject() -> None:
    """The version in ``__init__`` and ``pyproject.toml`` agree."""
    with PYPROJECT.open("rb") as handle:
        assert tomllib.load(handle)["project"]["version"] == __version__


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


def test_checks_prints_table(capsys: pytest.CaptureFixture[str]) -> None:
    """``cernis checks`` prints a header and one row per registered check."""
    assert main(["checks"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["ID", "FAMILY", "VERSION", "IMPLEMENTED"]
    rows = [line.split() for line in lines[1:]]
    assert rows == [[check.id, check.family.value, check.version, "no"] for check in CHECKS]


def test_checks_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    """``cernis checks --format json`` prints the registry as JSON."""
    assert main(["checks", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["cernis_version"] == __version__
    assert payload["checks"] == [
        {
            "id": check.id,
            "family": check.family.value,
            "version": check.version,
            "implemented": check.implemented,
            "description": check.description,
        }
        for check in CHECKS
    ]


def test_checks_rejects_unknown_format(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown ``--format`` value is a usage error (exit 2)."""
    with pytest.raises(SystemExit) as excinfo:
        main(["checks", "--format", "xml"])

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
