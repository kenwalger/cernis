"""Command-line interface for Cernis."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cernis import REPOSITORY_URL, __version__
from cernis.checks.registry import CHECKS, CheckSpec
from cernis.fetch import FetchConfig, Fetcher, FetchError, FetchResult, RobotsDecision
from cernis.fetch.cache import DEFAULT_CACHE_DIR
from cernis.model import Receipt

STATUS_MESSAGE = (
    "Cernis is in early development and nothing is usable yet. It will be a "
    "content discoverability auditor for published articles: it will fetch a "
    "published article and the things around it, run deterministic checks, and "
    "report findings that distinguish what was observed, what is recommended, "
    "and what cannot be determined, with no scores and no predicted outcomes. "
    "Run `cernis checks` to see the planned checks. "
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


def receipt_as_dict(receipt: Receipt) -> dict[str, object]:
    """Represent a receipt as JSON-ready data.

    :param receipt: The receipt.
    :return: Its fields, with the time in ISO 8601 and headers as an object.
    """
    return {
        "id": receipt.id,
        "requested_url": receipt.requested_url,
        "final_url": receipt.final_url,
        "redirect_chain": list(receipt.redirect_chain),
        "status_code": receipt.status_code,
        "error_kind": receipt.error_kind.value,
        "fetched_at": receipt.fetched_at.isoformat(),
        "body_sha256": receipt.body_sha256,
        "body_truncated_at": receipt.body_truncated_at,
        "headers": dict(receipt.headers),
        "cernis_version": receipt.cernis_version,
        "user_agent": receipt.user_agent,
    }


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
    }


def format_fetch_json(result: FetchResult) -> str:
    """Render a fetch result as JSON.

    :param result: The result.
    :return: A JSON object with the robots decisions and every receipt.
    """
    payload = {
        "cernis_version": __version__,
        "requested_url": result.requested_url,
        "disallowed_url": result.disallowed_url,
        "robots": [_decision_as_dict(decision) for decision in result.robots],
        "robots_receipts": [receipt_as_dict(receipt) for receipt in result.robots_receipts],
        "receipts": [receipt_as_dict(receipt) for receipt in result.receipts],
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
        lines.append(
            f"robots: {decision.url} {verdict} ({decision.basis.value}, {decision.receipt_id})"
        )
    for number, receipt in enumerate(result.receipts, start=1):
        lines += _format_receipt_text(receipt, f"attempt {number}")
    if result.disallowed_url is not None:
        lines.append(f"not fetched: robots.txt disallows {result.disallowed_url}")
    return "\n".join(lines)


def run_fetch(url: str, cache_dir: Path, output_format: str) -> int:
    """Fetch one URL and print the result.

    :param url: The URL.
    :param cache_dir: The cache directory.
    :param output_format: ``text`` or ``json``.
    :return: The exit code: 0 when the fetch ran (whatever it found), 2 when
        the URL cannot be fetched at all.
    """
    try:
        with Fetcher(FetchConfig(cache_dir=cache_dir)) as fetcher:
            result = fetcher.fetch(url)
    except FetchError as exc:
        print(f"cernis fetch: {exc}", file=sys.stderr)
        return 2
    print(format_fetch_json(result) if output_format == "json" else format_fetch_text(result))
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
    if args.command == "fetch":
        return run_fetch(args.url, args.cache_dir, args.format)
    print(STATUS_MESSAGE)
    return 0
