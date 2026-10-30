"""Tests for the JSON and Markdown reports: golden files, and the rules each format keeps.

The golden files in ``tests/golden/`` are a run over synthetic fixtures with
a fixed clock and fixed ids. To regenerate them after a deliberate change,
run ``CERNIS_UPDATE_GOLDEN=1 uv run pytest tests/test_reports.py`` and read
the diff before committing.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fetch_support import Site, make_fetcher, respond
from parse_support import DEV_URL, fixture

from cernis.audit import Target, audit
from cernis.model import Run
from cernis.parse import SiteType
from cernis.promises import find_outcome_language
from cernis.report import FORMAT, FORMAT_VERSION, report_json, report_markdown
from cernis.report.markdown import code, escape

GOLDEN = Path(__file__).parent / "golden"
WORDPRESS_PAGE = "https://blog.example.com/two-canonicals/"
GONE = "https://blog.example.com/gone/"
HTML = {"content-type": "text/html; charset=utf-8"}


def fixed_clock() -> object:
    """Return a clock that reads 12:00:00 UTC, then a second later each time.

    :return: The clock.
    """
    moments = (datetime(2026, 10, 30, 12, 0, tzinfo=UTC) + timedelta(seconds=n) for n in range(100))
    return lambda: next(moments)


def golden_run(tmp_path: Path) -> Run:
    """Audit three synthetic pages: a DEV copy, a WordPress page, and one that times out.

    :param tmp_path: The cache directory.
    :return: The run.
    """
    site = Site()
    site.add(DEV_URL, respond(200, fixture("dev-article"), HTML))
    site.add(WORDPRESS_PAGE, respond(200, fixture("two-canonicals"), HTML))
    site.add(GONE, httpx.ConnectTimeout("slow"))
    fetcher = make_fetcher(site, tmp_path, min_interval=0)
    targets = [
        Target(url=DEV_URL),
        Target(url=WORDPRESS_PAGE, site=SiteType.WORDPRESS),
        Target(url=GONE, site=SiteType.WORDPRESS),
    ]
    return audit(targets, fetcher, now=fixed_clock())  # type: ignore[arg-type]


def check_golden(name: str, text: str) -> None:
    """Compare text with a golden file, or rewrite it when asked to.

    :param name: The golden file's name.
    :param text: The text produced now.
    """
    path = GOLDEN / name
    if os.environ.get("CERNIS_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert text == path.read_text(encoding="utf-8")


def test_the_markdown_report_matches_its_golden_file(tmp_path: Path) -> None:
    """The whole Markdown report, byte for byte."""
    check_golden("audit.md", report_markdown(golden_run(tmp_path)))


def test_the_json_report_matches_its_golden_file(tmp_path: Path) -> None:
    """The whole JSON report, byte for byte."""
    check_golden("audit.json", report_json(golden_run(tmp_path)))


# JSON


def test_the_json_report_is_versioned_and_complete(tmp_path: Path) -> None:
    """Every finding, receipt, and snapshot is in it, with the format and version."""
    run = golden_run(tmp_path)
    payload = json.loads(report_json(run))

    assert (payload["format"], payload["format_version"]) == (FORMAT, FORMAT_VERSION)
    assert (FORMAT, FORMAT_VERSION) == ("cernis-report", 1)
    assert payload["run"]["id"] == run.id
    assert [f["id"] for f in payload["findings"]] == [f.id for f in run.findings]
    assert [f["key"] for f in payload["findings"]] == [f.key for f in run.findings]
    assert [r["id"] for r in payload["receipts"]] == [r.id for r in run.receipts]
    assert len(payload["snapshots"]) == len(run.snapshots) == 2
    assert payload["subjects"] == list(run.subjects)


def test_the_json_report_counts_sections_and_nothing_else(tmp_path: Path) -> None:
    """Principle 2: plain counts per section, no score."""
    payload = json.loads(report_json(golden_run(tmp_path)))

    assert set(payload["counts"]) == {"observed", "recommendations", "not_determinable"}
    statuses = [f["status"] for f in payload["findings"]]
    assert payload["counts"] == {
        "observed": statuses.count("OBSERVED"),
        "recommendations": statuses.count("RECOMMENDATION"),
        "not_determinable": statuses.count("NOT_DETERMINABLE"),
    }
    text = json.dumps(payload).lower()
    assert "score" not in text
    assert "grade" not in text


def test_the_json_report_names_every_check_version_used(tmp_path: Path) -> None:
    """Each check with a finding in the run, with its version."""
    payload = json.loads(report_json(golden_run(tmp_path)))

    used = {(f["check_id"], f["check_version"]) for f in payload["findings"]}
    assert {(c["id"], c["version"]) for c in payload["checks"]} == used


# Markdown


def test_the_markdown_report_has_the_header_and_three_sections(tmp_path: Path) -> None:
    """Run id, Cernis version, check versions; Observed, Recommendations, non liquet."""
    run = golden_run(tmp_path)
    text = report_markdown(run)

    assert f"Run: {run.id} · Cernis {run.cernis_version}" in text
    assert "peri.canonical.single 1" in text
    statuses = [f.status.value for f in run.findings]
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        f"## Observed ({statuses.count('OBSERVED')})",
        f"## Recommendations ({statuses.count('RECOMMENDATION')})",
        f"## Not determinable (non liquet) ({statuses.count('NOT_DETERMINABLE')})",
    ]


def test_based_on_is_rendered_as_check_id_and_summary_never_a_bare_id(tmp_path: Path) -> None:
    """DESIGN.md section 7: Based on: <check id> (<summary>)."""
    run = golden_run(tmp_path)
    lines = report_markdown(run).splitlines()

    based = [line for line in lines if line.strip().startswith("Based on:")]
    assert based
    for line in based:
        assert "f-0" not in line
    assert (
        "  Based on: peri.canonical.single (The page declares 2 canonical links that name "
        "different URLs.)" in lines
    )


def test_the_markdown_report_makes_no_promise(tmp_path: Path) -> None:
    """Principle 3 holds for the rendered report's recommendation text."""
    run = golden_run(tmp_path)
    for finding in run.findings:
        if finding.status.value == "RECOMMENDATION":
            assert find_outcome_language(finding.summary) == ()
            assert find_outcome_language(finding.rationale or "") == ()


def test_a_single_page_report_is_titled_after_the_page(tmp_path: Path) -> None:
    """One subject with a title: the heading names it, and there are no subject subheadings."""
    site = Site()
    site.add(WORDPRESS_PAGE, respond(200, fixture("two-canonicals"), HTML))
    run = audit(
        [Target(url=WORDPRESS_PAGE, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path),
        now=fixed_clock(),  # type: ignore[arg-type]
    )

    text = report_markdown(run)

    assert text.startswith("# Cernis audit: A Post With Two Canonicals\n")
    assert "\n### " not in text


def test_an_empty_section_says_none(tmp_path: Path) -> None:
    """A page with no defects has no recommendations, and the section says so."""
    site = Site()
    site.add(WORDPRESS_PAGE, respond(200, fixture("wordpress-entry"), HTML))
    run = audit(
        [Target(url=WORDPRESS_PAGE, site=SiteType.WORDPRESS)],
        make_fetcher(site, tmp_path),
        now=fixed_clock(),  # type: ignore[arg-type]
    )

    assert "## Recommendations (0)\n\nNone.\n" in report_markdown(run)


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ("<html>", "\\<html\\>"),
        ("*bold* and [link]", "\\*bold\\* and \\[link\\]"),
        ("a`b\\c", "a\\`b\\\\c"),
        ("plain og:url_text", "plain og:url_text"),
    ],
)
def test_page_text_is_escaped(text: str, escaped: str) -> None:
    """Text from a page cannot become Markdown or HTML."""
    assert escape(text) == escaped


@pytest.mark.parametrize(
    ("text", "span"),
    [("plain", "`plain`"), ("a`b", "``a`b``"), ("`x`", "`` `x` ``"), ("", "` `")],
)
def test_code_spans_cannot_be_closed_by_their_content(text: str, span: str) -> None:
    """A value with backticks gets a longer fence."""
    assert code(text) == span
