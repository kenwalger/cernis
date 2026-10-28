"""Command-line interface for Cernis."""

import argparse
from collections.abc import Sequence

from cernis import __version__

REPOSITORY_URL = "https://github.com/kenwalger/cernis"

STATUS_MESSAGE = (
    "Cernis is in early development and nothing is usable yet. It will be a "
    "content discoverability auditor for published articles: it will fetch a "
    "published article and the things around it, run deterministic checks, and "
    "report findings that distinguish what was observed, what is recommended, "
    "and what cannot be determined, with no scores and no predicted outcomes. "
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``cernis`` command.

    :param argv: Command-line arguments, excluding the program name. Defaults
        to ``sys.argv[1:]`` when ``None``.
    :return: The process exit code.
    """
    build_parser().parse_args(argv)
    print(STATUS_MESSAGE)
    return 0
