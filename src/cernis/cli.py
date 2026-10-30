"""Command-line interface for Cernis."""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from cernis import REPOSITORY_URL, __version__
from cernis.audit import Target, audit
from cernis.checks.registry import CHECKS, CheckSpec
from cernis.fetch import FetchConfig, Fetcher, FetchError, FetchResult, RobotsDecision
from cernis.fetch.cache import DEFAULT_CACHE_DIR
from cernis.model import Receipt
from cernis.parse import SiteType
from cernis.report import report_json, report_markdown
from cernis.report.json_report import receipt_as_dict

STATUS_MESSAGE = (
    "Cernis is in early development and nothing is usable yet. It will be a "
    "content discoverability auditor for published articles: it will fetch a "
    "published article and the things around it, run deterministic checks, and "
    "report findings that distinguish what was observed, what is recommended, "
    "and what cannot be determined, with no scores and no predicted outcomes. "
    "Run `cernis audit <url>` to audit a page, or `cernis checks` to see the checks. "
    f"Follow along at {REPOSITORY_URL}."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``cernis`` command.

    :return: The configured argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="cernis",
        description="A content discoverability auditor for published articles.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    checks = commands.add_parser(
        "checks",
        help="list every check with its id, family, version, and status",
        description="List every registered check.",
    )
    checks.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="output format (default: table)",
    )
    audit_parser = commands.add_parser(
        "audit",
        help="audit published articles and report what was observed, recommended, and unknown",
        description=(
            "Fetch each URL politely, run the peritext checks on every page read whole, "
            "and report the findings."
        ),
    )
    audit_parser.add_argument(
        "urls", nargs="+", metavar="url", help="an absolute http or https URL"
    )
    audit_parser.add_argument(
        "--site-type",
        choices=[site.value for site in SiteType],
        help="declare the site type of every URL given (overrides host detection)",
    )
    audit_parser.add_argument(
        "--format",
        choices=("md", "json"),
        default="md",
        help="report format (default: md)",
    )
    audit_parser.add_argument(
        "--output",
        type=Path,
        help="write the report to this file instead of standard output",
    )
    audit_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"cache directory for conditional requests (default: {DEFAULT_CACHE_DIR})",
    )
    audit_parser.add_argument(
        "--allow-loopback",
        action="store_true",
        help="allow loopback addresses, for testing against a local server",
    )
    fetch = commands.add_parser(
        "fetch",
        help="fetch one URL politely and print its receipts, for manual checking",
        description=(
            "Fetch one URL, checking robots.txt first, and print every receipt: "
            "robots.txt fetches, then one per attempt at the URL."
        ),
    )
    fetch.add_argument("url", help="an absolute http or https URL")
    fetch.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )
    fetch.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"cache directory for conditional requests (default: {DEFAULT_CACHE_DIR})",
    )
    fetch.add_argument(
        "--allow-loopback",
        action="store_true",
        help=(
            "allow loopback addresses (127.0.0.0/8, ::1), for testing against a local "
            "server; every other non-public address is still refused"
        ),
    )
    return parser


def format_checks_table(checks: Sequence[CheckSpec]) -> str:
    """Render checks as a plain-text table.

    :param checks: The checks to list.
    :return: A header row and one row per check, columns aligned.
    """
    rows = [("ID", "FAMILY", "VERSION", "IMPLEMENTED")] + [
        (c.id, c.family.value, c.version, "yes" if c.implemented else "no") for c in checks
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row[:3], widths, strict=True))
        + "  "
        + row[3]
        for row in rows
    )


def format_checks_json(checks: Sequence[CheckSpec]) -> str:
    """Render checks as JSON.

    :param checks: The checks to list.
    :return: A JSON object with the Cernis version and one entry per check.
    """
    payload = {
        "cernis_version": __version__,
        "checks": [
            {
                "id": c.id,
                "family": c.family.value,
                "version": c.version,
                "implemented": c.implemented,
                "description": c.description,
            }
            for c in checks
        ],
    }
    return json.dumps(payload, indent=2)


def _decision_as_dict(decision: RobotsDecision) -> dict[str, object]:
    """Represent a robots decision as JSON-ready data.

    :param decision: The decision.
    :return: Its fields.
    """
    return {
        "url": decision.url,
        "robots_url": decision.robots_url,
        "allowed": decision.allowed,
        "basis": decision.basis.value,
        "receipt_id": decision.receipt_id,
        "rule": decision.rule,
        "matcher_version": decision.matcher_version,
    }


def format_fetch_json(result: FetchResult) -> str:
    """Render a fetch result as JSON.

    :param result: The result.
    :return: A JSON object with the robots decisions, every receipt, and the
        reason for each refused address.
    """
    payload = {
        "cernis_version": __version__,
        "requested_url": result.requested_url,
        "disallowed_url": result.disallowed_url,
        "robots": [_decision_as_dict(decision) for decision in result.robots],
        "robots_receipts": [receipt_as_dict(receipt) for receipt in result.robots_receipts],
        "receipts": [receipt_as_dict(receipt) for receipt in result.receipts],
        "refusals": [
            {"receipt_id": refusal.receipt_id, "url": refusal.url, "reason": refusal.reason}
            for refusal in result.refusals
        ],
    }
    return json.dumps(payload, indent=2)


def _format_receipt_text(receipt: Receipt, label: str) -> list[str]:
    """Render one receipt as indented lines.

    :param receipt: The receipt.
    :param label: What the receipt is for, shown after its id.
    :return: The lines.
    """
    lines = [f"receipt {receipt.id} ({label})"]
    for name, value in receipt_as_dict(receipt).items():
        if name == "id":
            continue
        if name == "redirect_chain":
            value = " -> ".join(receipt.redirect_chain) or "(none)"
        elif name == "headers":
            value = "; ".join(f"{key}: {text}" for key, text in receipt.headers) or "(none)"
        lines.append(f"  {name}: {value}")
    return lines


def format_fetch_text(result: FetchResult) -> str:
    """Render a fetch result as plain text.

    :param result: The result.
    :return: robots.txt receipts, robots decisions, then the URL's receipts.
    """
    lines: list[str] = []
    for receipt in result.robots_receipts:
        lines += _format_receipt_text(receipt, "robots.txt")
    for decision in result.robots:
        verdict = "allowed" if decision.allowed else "disallowed"
        line = f"robots: {decision.url} {verdict} ({decision.basis.value}, {decision.receipt_id})"
        if decision.rule is not None:
            line += f" by {decision.rule!r}"
        lines.append(line)
    for number, receipt in enumerate(result.receipts, start=1):
        lines += _format_receipt_text(receipt, f"attempt {number}")
    for refusal in result.refusals:
        lines.append(f"refused ({refusal.receipt_id}): {refusal.url}: {refusal.reason}")
    if result.disallowed_url is not None:
        lines.append(f"not fetched: robots.txt disallows {result.disallowed_url}")
    return "\n".join(lines)


def run_fetch(url: str, cache_dir: Path, output_format: str, allow_loopback: bool = False) -> int:
    """Fetch one URL and print the result.

    :param url: The URL.
    :param cache_dir: The cache directory.
    :param output_format: ``text`` or ``json``.
    :param allow_loopback: Whether loopback addresses are allowed.
    :return: The exit code: 0 when the fetch ran (whatever it found), 2 when
        the URL cannot be fetched at all.
    """
    try:
        config = FetchConfig(cache_dir=cache_dir, allow_loopback=allow_loopback)
        with Fetcher(config) as fetcher:
            result = fetcher.fetch(url)
    except FetchError as exc:
        print(f"cernis fetch: {exc}", file=sys.stderr)
        return 2
    print(format_fetch_json(result) if output_format == "json" else format_fetch_text(result))
    return 0


def run_audit(
    urls: Sequence[str],
    site_type: str | None,
    output_format: str,
    output: Path | None,
    cache_dir: Path,
    allow_loopback: bool = False,
) -> int:
    """Audit URLs and write the report.

    :param urls: The URLs.
    :param site_type: The declared site type for every URL, or ``None``.
    :param output_format: ``md`` or ``json``.
    :param output: The file to write, or ``None`` for standard output.
    :param cache_dir: The cache directory.
    :param allow_loopback: Whether loopback addresses are allowed.
    :return: The exit code: 0 when the audit ran (whatever it found), 2 when a
        URL cannot be fetched at all or the report cannot be written.
    """
    site = SiteType(site_type) if site_type is not None else None
    targets = [Target(url=url, site=site) for url in urls]
    config = FetchConfig(cache_dir=cache_dir, allow_loopback=allow_loopback)
    try:
        with Fetcher(config) as fetcher:
            run = audit(targets, fetcher, now=lambda: datetime.now(UTC))
    except FetchError as exc:
        print(f"cernis audit: {exc}", file=sys.stderr)
        return 2
    text = report_json(run) if output_format == "json" else report_markdown(run)
    if output is None:
        sys.stdout.write(text)
        return 0
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"cernis audit: cannot write {output}: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``cernis`` command.

    :param argv: Command-line arguments, excluding the program name. Defaults
        to ``sys.argv[1:]`` when ``None``.
    :return: The process exit code.
    """
    args = build_parser().parse_args(argv)
    if args.command == "checks":
        if args.format == "json":
            print(format_checks_json(CHECKS))
        else:
            print(format_checks_table(CHECKS))
        return 0
    if args.command == "audit":
        return run_audit(
            args.urls,
            args.site_type,
            args.format,
            args.output,
            args.cache_dir,
            args.allow_loopback,
        )
    if args.command == "fetch":
        return run_fetch(args.url, args.cache_dir, args.format, args.allow_loopback)
    print(STATUS_MESSAGE)
    return 0
