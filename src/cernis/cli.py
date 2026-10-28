"""Command-line interface for Cernis."""

import argparse
import json
from collections.abc import Sequence

from cernis import __version__
from cernis.checks.registry import CHECKS, CheckSpec

REPOSITORY_URL = "https://github.com/kenwalger/cernis"

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
    print(STATUS_MESSAGE)
    return 0
