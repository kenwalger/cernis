"""Tests for the ``cernis`` command-line interface."""

import hashlib
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from fetch_support import FIXED_NOW, Site, respond

from cernis import REPOSITORY_URL, __version__, cli
from cernis.checks.registry import CHECKS
from cernis.cli import main
from cernis.fetch import USER_AGENT, FetchConfig, Fetcher
from cernis.fetch.cache import DEFAULT_CACHE_DIR


def test_version_flag_prints_name_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    """``cernis --version`` prints ``cernis <version>`` and exits 0."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"cernis {__version__}"


def test_package_version_is_the_installed_distribution_version() -> None:
    """``__version__`` is the version of the installed ``cernis`` distribution."""
    assert __version__ == version("cernis")


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


# cernis fetch


def _scripted_fetcher(monkeypatch: pytest.MonkeyPatch, site: Site) -> None:
    """Make ``cernis fetch`` use a scripted web and skip pacing waits.

    :param monkeypatch: Used to replace the CLI's fetcher.
    :param site: The scripted web.
    """

    def build(config: FetchConfig) -> Fetcher:
        return Fetcher(
            config,
            transport=httpx.MockTransport(site.handler),
            sleep=lambda seconds: None,
            now=lambda: FIXED_NOW,
        )

    monkeypatch.setattr(cli, "Fetcher", build)


def test_fetch_prints_receipts_as_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``cernis fetch --format json`` prints the robots decision and every receipt."""
    site = Site()
    site.add("https://example.com/post", respond(200, b"hi", {"etag": '"v1"'}))
    _scripted_fetcher(monkeypatch, site)

    code = main(
        ["fetch", "https://example.com/post", "--format", "json", "--cache-dir", str(tmp_path)]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cernis_version"] == __version__
    assert payload["disallowed_url"] is None
    assert payload["robots"] == [
        {
            "url": "https://example.com/post",
            "robots_url": "https://example.com/robots.txt",
            "allowed": True,
            "basis": "UNAVAILABLE",
            "receipt_id": "r-001",
        }
    ]
    assert [r["status_code"] for r in payload["robots_receipts"]] == [404]
    (receipt,) = payload["receipts"]
    assert receipt == {
        "id": "r-002",
        "requested_url": "https://example.com/post",
        "final_url": "https://example.com/post",
        "redirect_chain": [],
        "status_code": 200,
        "error_kind": "NONE",
        "fetched_at": "2026-10-29T12:00:00+00:00",
        "body_sha256": hashlib.sha256(b"hi").hexdigest(),
        "body_truncated_at": None,
        "headers": {"etag": '"v1"'},
        "cernis_version": __version__,
        "user_agent": USER_AGENT,
    }
    assert (tmp_path / "entries").is_dir()


def test_fetch_prints_receipts_as_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default text format lists robots.txt, the decision, then each attempt."""
    site = Site()
    site.add("https://example.com/post", respond(429), respond(200))
    _scripted_fetcher(monkeypatch, site)

    assert main(["fetch", "https://example.com/post", "--cache-dir", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "receipt r-001 (robots.txt)" in out
    assert "robots: https://example.com/post allowed (UNAVAILABLE, r-001)" in out
    assert "receipt r-002 (attempt 1)" in out
    assert "  status_code: 429" in out
    assert "receipt r-003 (attempt 2)" in out
    assert "  redirect_chain: (none)" in out


def test_fetch_says_when_robots_txt_disallows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A disallowed URL is reported, not fetched, and the command still succeeds."""
    site = Site()
    site.add("https://example.com/robots.txt", respond(200, b"User-agent: *\nDisallow: /\n"))
    _scripted_fetcher(monkeypatch, site)

    assert main(["fetch", "https://example.com/post", "--cache-dir", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "not fetched: robots.txt disallows https://example.com/post" in out
    assert "attempt" not in out


def test_fetch_refuses_a_url_it_cannot_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A URL that is not absolute http or https exits 2 with a message, and requests nothing."""
    site = Site()
    _scripted_fetcher(monkeypatch, site)

    assert main(["fetch", "ftp://example.com/", "--cache-dir", str(tmp_path)]) == 2

    assert "cernis fetch:" in capsys.readouterr().err
    assert site.requests == []


def test_fetch_defaults_to_the_git_ignored_cache_directory() -> None:
    """Without --cache-dir, the cache is .cernis-cache."""
    args = cli.build_parser().parse_args(["fetch", "https://example.com/"])

    assert args.cache_dir == DEFAULT_CACHE_DIR
    assert args.format == "text"
