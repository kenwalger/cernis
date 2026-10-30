"""Tests for the ``cernis`` command-line interface."""

import hashlib
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest
from fetch_support import FIXED_NOW, FakeResolver, Site, respond

from cernis import REPOSITORY_URL, __version__, cli
from cernis.checks.registry import CHECKS
from cernis.cli import main
from cernis.fetch import USER_AGENT, FetchConfig, Fetcher
from cernis.fetch.cache import DEFAULT_CACHE_DIR
from cernis.fetch.rfc9309 import MATCHER_VERSION


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
    assert rows == [
        [check.id, check.family.value, check.version, "yes" if check.implemented else "no"]
        for check in CHECKS
    ]


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


def _scripted_fetcher(
    monkeypatch: pytest.MonkeyPatch, site: Site, resolver: FakeResolver | None = None
) -> list[FetchConfig]:
    """Make ``cernis fetch`` use a scripted web and skip pacing waits.

    :param monkeypatch: Used to replace the CLI's fetcher.
    :param site: The scripted web.
    :param resolver: The fake resolver; a new one if ``None``.
    :return: The configurations the CLI built, one per fetch.
    """
    configs: list[FetchConfig] = []

    def build(config: FetchConfig) -> Fetcher:
        configs.append(config)
        return Fetcher(
            config,
            transport=httpx.MockTransport(site.handler),
            sleep=lambda seconds: None,
            now=lambda: FIXED_NOW,
            resolver=resolver or FakeResolver(),
        )

    monkeypatch.setattr(cli, "Fetcher", build)
    return configs


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
            "rule": None,
            "matcher_version": MATCHER_VERSION,
        }
    ]
    assert payload["refusals"] == []
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


def test_fetch_reports_a_refused_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal prints its receipt and its reason, in text and in JSON."""
    resolver = FakeResolver({"example.com": ["169.254.169.254"]})
    _scripted_fetcher(monkeypatch, Site(), resolver)

    assert main(["fetch", "https://example.com/post", "--cache-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "  error_kind: ADDRESS_REFUSED" in out
    assert (
        "refused (r-001): https://example.com/post: example.com resolves to 169.254.169.254" in out
    )

    main(["fetch", "https://example.com/post", "--format", "json", "--cache-dir", str(tmp_path)])
    (refusal,) = json.loads(capsys.readouterr().out)["refusals"]
    assert refusal["receipt_id"] == "r-001"
    assert "link-local" in refusal["reason"]


def test_fetch_allow_loopback_reaches_the_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--allow-loopback turns on the opt-in; without it, loopback stays refused."""
    configs = _scripted_fetcher(monkeypatch, Site())

    main(["fetch", "http://127.0.0.1/", "--cache-dir", str(tmp_path)])
    main(["fetch", "http://127.0.0.1/", "--allow-loopback", "--cache-dir", str(tmp_path)])

    assert [config.allow_loopback for config in configs] == [False, True]


def test_fetch_text_names_the_deciding_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The text output shows which robots.txt rule decided."""
    site = Site()
    site.add("https://example.com/robots.txt", respond(200, b"User-agent: *\nDisallow: /post\n"))
    _scripted_fetcher(monkeypatch, site)

    main(["fetch", "https://example.com/post", "--cache-dir", str(tmp_path)])

    assert "disallowed (RULES, r-001) by 'Disallow: /post'" in capsys.readouterr().out


# cernis audit


WP_PAGE = "https://blog.example.com/two-canonicals/"


def _audit_site(monkeypatch: pytest.MonkeyPatch) -> list[FetchConfig]:
    """Serve one synthetic WordPress page to ``cernis audit``.

    :param monkeypatch: Used to replace the CLI's fetcher.
    :return: The configurations the CLI built.
    """
    site = Site()
    site.add(
        WP_PAGE,
        respond(
            200,
            (Path(__file__).parent / "fixtures" / "two-canonicals.html").read_bytes(),
            {"content-type": "text/html"},
        ),
    )
    return _scripted_fetcher(monkeypatch, site)


def test_audit_prints_a_markdown_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default format is Markdown, on standard output."""
    _audit_site(monkeypatch)

    code = main(["audit", WP_PAGE, "--site-type", "wordpress", "--cache-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("# Cernis audit: A Post With Two Canonicals\n")
    assert "## Observed (13)" in out
    assert "## Recommendations (1)" in out
    assert "extractor wordpress.entry 1+n1, declared" in out


def test_audit_writes_json_to_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--format json --output writes the versioned JSON report and prints nothing."""
    _audit_site(monkeypatch)
    output = tmp_path / "report.json"

    code = main(
        [
            "audit",
            WP_PAGE,
            "--format",
            "json",
            "--output",
            str(output),
            "--cache-dir",
            str(tmp_path),
        ]
    )

    assert code == 0
    assert capsys.readouterr().out == ""
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert (payload["format"], payload["subjects"]) == ("cernis-report", [WP_PAGE])


def test_audit_without_a_site_type_uses_host_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An undeclared WordPress page gets the generic extractor and unknown actors."""
    _audit_site(monkeypatch)

    main(["audit", WP_PAGE, "--cache-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert "extractor generic 1+n1, generic" in out
    assert "- UNKNOWN · peri.canonical.present" in out


def test_audit_refuses_a_url_it_cannot_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A URL that is not absolute http(s) exits 2 with a message."""
    _audit_site(monkeypatch)

    assert main(["audit", "ftp://example.com/", "--cache-dir", str(tmp_path)]) == 2
    assert "cernis audit:" in capsys.readouterr().err


def test_audit_reports_an_unwritable_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An output path that cannot be written exits 2."""
    _audit_site(monkeypatch)

    code = main(
        [
            "audit",
            WP_PAGE,
            "--output",
            str(tmp_path / "no" / "such" / "dir" / "r.md"),
            "--cache-dir",
            str(tmp_path),
        ]
    )

    assert code == 2
    assert "cannot write" in capsys.readouterr().err


def test_audit_rejects_an_unknown_site_type(capsys: pytest.CaptureFixture[str]) -> None:
    """--site-type is dev or wordpress."""
    with pytest.raises(SystemExit) as excinfo:
        main(["audit", WP_PAGE, "--site-type", "medium"])

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_audit_reads_site_types_from_a_pair_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--map applies [[site]] prefixes; --site-type overrides them."""
    _audit_site(monkeypatch)
    pair_map = tmp_path / "pairs.toml"
    pair_map.write_text(
        'format = 1\n[[site]]\nprefix = "https://blog.example.com/"\ntype = "wordpress"\n',
        encoding="utf-8",
    )
    cache = str(tmp_path / "cache")

    main(["audit", WP_PAGE, "--map", str(pair_map), "--cache-dir", cache])
    by_prefix = capsys.readouterr().out
    main(["audit", WP_PAGE, "--map", str(pair_map), "--site-type", "dev", "--cache-dir", cache])
    overridden = capsys.readouterr().out

    assert "extractor wordpress.entry 1+n1, prefix" in by_prefix
    assert "extractor dev.article 1+n1, declared" in overridden


def test_audit_uses_a_urls_own_site_in_the_map_over_a_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A URL declared in a [[pair]] beats a [[site]] prefix that covers it."""
    _audit_site(monkeypatch)
    pair_map = tmp_path / "pairs.toml"
    pair_map.write_text(
        "format = 1\n"
        f'[[pair]]\noriginal = {{ url = "{WP_PAGE}", site = "dev" }}\n'
        'copy = { url = "https://dev.to/x/y" }\n'
        '[[site]]\nprefix = "https://blog.example.com/"\ntype = "wordpress"\n',
        encoding="utf-8",
    )

    main(["audit", WP_PAGE, "--map", str(pair_map), "--cache-dir", str(tmp_path / "c")])

    assert "extractor dev.article 1+n1, declared" in capsys.readouterr().out


def test_audit_refuses_a_bad_pair_map(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A map that does not load exits 2 with the loader's message, before any request."""
    _audit_site(monkeypatch)
    bad = tmp_path / "bad.toml"
    bad.write_text("format = 2\n", encoding="utf-8")

    assert main(["audit", WP_PAGE, "--map", str(bad)]) == 2
    assert "format must be 1" in capsys.readouterr().err
