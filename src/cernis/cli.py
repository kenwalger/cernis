"""Command-line interface for Cernis."""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cernis import REPOSITORY_URL, __version__
from cernis.audit import AuditLimits, PairTarget, RunFetches, Target, audit
from cernis.checks.links import LinkLimits
from cernis.checks.registry import CHECKS, CheckSpec
from cernis.fetch import FetchConfig, Fetcher, FetchError, FetchResult, RobotsDecision
from cernis.fetch.cache import DEFAULT_CACHE_DIR
from cernis.model import Receipt, RunSource
from cernis.pairs import PairMap, PairMapError, load_pair_map
from cernis.parse import SitePrefix, SiteType
from cernis.report import report_json, report_markdown
from cernis.report.json_report import receipt_as_dict
from cernis.sources import Listing, SourceError, from_dev_user, from_sitemap
from cernis.urls import normalize_url

STATUS_MESSAGE = (
    "Cernis is in early development and nothing is usable yet. It will be a "
    "content discoverability auditor for published articles: it will fetch a "
    "published article and the things around it, run deterministic checks, and "
    "report findings that distinguish what was observed, what is recommended, "
    "and what cannot be determined, with no scores and no predicted outcomes. "
    "Run `cernis audit <url>` to audit a page, or `cernis checks` to see the checks. "
    f"Follow along at {REPOSITORY_URL}."
)


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    """Add the report and fetch options every auditing command shares.

    :param parser: The subcommand's parser.
    """
    parser.add_argument(
        "--format", choices=("md", "json"), default="md", help="report format (default: md)"
    )
    parser.add_argument(
        "--output", type=Path, help="write the report to this file instead of standard output"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"cache directory for conditional requests (default: {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument(
        "--allow-loopback",
        action="store_true",
        help="allow loopback addresses, for testing against a local server",
    )
    parser.add_argument(
        "--max-links-per-page",
        type=_count,
        default=LinkLimits().per_page,
        metavar="N",
        help=f"check at most N article-body links per page (default: {LinkLimits().per_page})",
    )
    parser.add_argument(
        "--max-links-per-host",
        type=_count,
        default=LinkLimits().per_external_host,
        metavar="N",
        help=(
            "check at most N links per external host in the run "
            f"(default: {LinkLimits().per_external_host})"
        ),
    )
    parser.add_argument(
        "--max-sitemap-documents",
        type=_positive,
        default=AuditLimits().sitemap_documents,
        metavar="N",
        help=(
            "read at most N sitemap documents per site "
            f"(default: {AuditLimits().sitemap_documents})"
        ),
    )


def _add_listing_options(parser: argparse.ArgumentParser) -> None:
    """Add ``--limit`` and ``--list-only``, for commands that list URLs from a source.

    :param parser: The subcommand's parser.
    """
    parser.add_argument(
        "--limit", type=_positive, metavar="N", help="list at most N URLs from the source"
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="print what the source lists and stop after the listing requests",
    )


def _count(text: str) -> int:
    """Read a whole number that may be zero, for argparse.

    :param text: The argument.
    :return: The number.
    :raises argparse.ArgumentTypeError: If it is not a whole number of zero or more.
    """
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"must be a whole number of zero or more, got {text!r}")
    return int(text)


def _positive(text: str) -> int:
    """Read a whole number of at least 1, for argparse.

    :param text: The argument.
    :return: The number.
    :raises argparse.ArgumentTypeError: If it is not a whole number of at least 1.
    """
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"must be a whole number of at least 1, got {text!r}")
    return int(text)


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
        "urls", nargs="*", metavar="url", help="an absolute http or https URL"
    )
    audit_parser.add_argument(
        "--from-sitemap",
        metavar="URL",
        help="audit the pages a sitemap (or sitemap index) lists, instead of URLs",
    )
    audit_parser.add_argument(
        "--include-prefix",
        metavar="PREFIX",
        help="with --from-sitemap, only the pages at or under this URL prefix",
    )
    audit_parser.add_argument(
        "--from-dev-user",
        metavar="USERNAME",
        help="audit a DEV user's published articles (DEV's public API), instead of URLs",
    )
    audit_parser.add_argument(
        "--site-type",
        choices=[site.value for site in SiteType],
        help="declare the site type of every URL given (overrides host detection)",
    )
    audit_parser.add_argument(
        "--map",
        type=Path,
        metavar="FILE",
        help=(
            "a pair map (docs/PAIR-MAP.md) whose per-URL site types and [[site]] prefix "
            "rules apply; --site-type overrides both"
        ),
    )
    _add_listing_options(audit_parser)
    pair_parser = commands.add_parser(
        "pair",
        help="audit an original and its copy, then check the copy names the original",
        description=(
            "Audit both pages (every peritext check), check each page's canonical and "
            "og:image, then run the pair check: the copy's canonical against the original, "
            "and the original's against itself."
        ),
    )
    pair_parser.add_argument("--original", required=True, metavar="URL", help="the original")
    pair_parser.add_argument("--copy", required=True, metavar="URL", help="the copy")
    site_choices = [site.value for site in SiteType]
    pair_parser.add_argument(
        "--original-site", choices=site_choices, help="declare the original's site type"
    )
    pair_parser.add_argument(
        "--copy-site", choices=site_choices, help="declare the copy's site type"
    )
    pair_parser.add_argument(
        "--map",
        type=Path,
        metavar="FILE",
        help="a pair map whose site types and [[site]] prefix rules apply",
    )
    pairs_parser = commands.add_parser(
        "pairs",
        help="audit every [[pair]] in a pair map, or a DEV user's cross-posts, in one run",
        description=(
            "Audit every original and copy listed in a pair map (docs/PAIR-MAP.md), or every "
            "DEV article of a user whose canonical URL names a page off dev.to."
        ),
    )
    pairs_parser.add_argument(
        "--map",
        type=Path,
        metavar="FILE",
        help="the pair map; with --from-dev-user, only its site types and prefix rules apply",
    )
    pairs_parser.add_argument(
        "--from-dev-user",
        metavar="USERNAME",
        help="pair each of this DEV user's cross-posted articles with its original",
    )
    _add_listing_options(pairs_parser)
    for sub in (audit_parser, pair_parser, pairs_parser):
        _add_run_options(sub)
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


@dataclass(frozen=True, kw_only=True)
class RunOptions:
    """Report, fetch, and limit options shared by ``audit``, ``pair``, and ``pairs``.

    :param command: The command name, for messages.
    :param output_format: ``md`` or ``json``.
    :param output: The file to write, or ``None`` for standard output.
    :param cache_dir: The cache directory.
    :param allow_loopback: Whether loopback addresses are allowed.
    :param limits: The limits on fetches around each page.
    """

    command: str
    output_format: str
    output: Path | None
    cache_dir: Path
    allow_loopback: bool = False
    limits: AuditLimits = field(default_factory=AuditLimits)


def _load_map(pair_map: Path | None, command: str) -> PairMap | None:
    """Load a pair map, printing the problem if it cannot be loaded.

    :param pair_map: The file, or ``None``.
    :param command: The command name, for the message.
    :return: The map, an empty map when none was given, or ``None`` if it
        failed to load.
    """
    if pair_map is None:
        return PairMap(pairs=())
    try:
        return load_pair_map(pair_map)
    except PairMapError as exc:
        print(f"cernis {command}: {exc}", file=sys.stderr)
        return None


def _site_for(url: str, declared: SiteType | None, pair_map: PairMap) -> SiteType | None:
    """Return a URL's declared site type: the command line's, else its own in the map.

    :param url: The URL.
    :param declared: The site type given on the command line, if any.
    :param pair_map: The pair map.
    :return: The site type, or ``None`` to use prefix rules and the host.
    """
    return declared or pair_map.site_types().get(normalize_url(url))


Work = Callable[[RunFetches], int]
"""What a command does with the run's fetches; returns the exit code."""


def _loopback_refused(options: RunOptions, source: "SourceOptions") -> bool:
    """Refuse loopback with a URL source, and warn about it otherwise.

    ``--allow-loopback`` opens the address screen for every fetch in the run,
    including the links, canonicals, and sitemaps the pages name. With a
    sitemap or a DEV user as the source, Cernis does not choose those pages,
    so the combination is refused.

    :param options: The shared options.
    :param source: The URL source options.
    :return: Whether the command must stop (exit 2).
    """
    if not options.allow_loopback:
        return False
    if source.from_sitemap is not None or source.from_dev_user is not None:
        print(
            f"cernis {options.command}: --allow-loopback cannot be combined with "
            "--from-sitemap or --from-dev-user",
            file=sys.stderr,
        )
        return True
    print(
        f"cernis {options.command}: warning: with --allow-loopback, links, canonicals, and "
        "sitemaps the pages name may reach services on this machine",
        file=sys.stderr,
    )
    return False


def _with_fetches(options: RunOptions, work: Work) -> int:
    """Open one fetcher for the run, and do the work with it.

    :param options: The shared options.
    :param work: The work.
    :return: The work's exit code, or 2 when a URL cannot be fetched at all
        or a source cannot be listed.
    """
    config = FetchConfig(cache_dir=options.cache_dir, allow_loopback=options.allow_loopback)
    try:
        with Fetcher(config) as fetcher:
            return work(RunFetches(fetcher))
    except (FetchError, SourceError) as exc:
        print(f"cernis {options.command}: {exc}", file=sys.stderr)
        return 2


def _write(options: RunOptions, text: str) -> int:
    """Write a report or listing to the output file or standard output.

    :param options: The shared options.
    :param text: The text.
    :return: 0, or 2 when the file cannot be written.
    """
    if options.output is None:
        sys.stdout.write(text)
        return 0
    try:
        options.output.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"cernis {options.command}: cannot write {options.output}: {exc}", file=sys.stderr)
        return 2
    return 0


def _audit_and_write(
    options: RunOptions,
    fetches: RunFetches,
    targets: Sequence[Target],
    pairs: Sequence[PairTarget],
    prefixes: Sequence[SitePrefix],
    sources: Sequence[RunSource] = (),
) -> int:
    """Run an audit and write its report.

    :param options: The shared options.
    :param fetches: The run's fetches.
    :param targets: Single pages.
    :param pairs: Original and copy pairs.
    :param prefixes: Prefix rules.
    :param sources: Where the URLs came from.
    :return: The exit code: 0 when the audit ran (whatever it found), 2 when
        there is nothing to audit or the report cannot be written.
    """
    if not targets and not pairs:
        print(f"cernis {options.command}: nothing to audit", file=sys.stderr)
        return 2
    run = audit(
        targets,
        fetches.fetcher,
        now=lambda: datetime.now(UTC),
        prefixes=prefixes,
        pairs=pairs,
        limits=options.limits,
        fetches=fetches,
        sources=sources,
    )
    return _write(
        options, report_json(run) if options.output_format == "json" else report_markdown(run)
    )


def _run_and_write(
    options: RunOptions,
    targets: Sequence[Target],
    pairs: Sequence[PairTarget],
    prefixes: Sequence[SitePrefix],
) -> int:
    """Run an audit of given URLs and write its report.

    :param options: The shared options.
    :param targets: Single pages.
    :param pairs: Original and copy pairs.
    :param prefixes: Prefix rules.
    :return: The exit code, as for :func:`_audit_and_write`; also 2 when a
        page URL cannot be fetched at all.
    """
    return _with_fetches(
        options, lambda fetches: _audit_and_write(options, fetches, targets, pairs, prefixes)
    )


def format_listing(listing: Listing, fetches: RunFetches, *, pairs_only: bool = False) -> str:
    """Render what a source listed, for ``--list-only``.

    :param listing: The listing.
    :param fetches: The run's fetches, for the receipts.
    :param pairs_only: For ``pairs --from-dev-user``: show the pairs formed.
    :return: The text, with a trailing newline.
    """
    source = listing.source
    what = "DEV user" if source.kind == "dev-user" else "sitemap"
    lines = [f"Source: {what} {source.query}", "", "Requests:", ""]
    for rid in source.receipt_ids:
        receipt = fetches.receipts[rid]
        answer = receipt.status_code if receipt.status_code is not None else receipt.error_kind
        lines.append(f"- {rid}: {receipt.requested_url} ({answer})")
    if pairs_only:
        crossed = [a for a in listing.articles if a.original is not None]
        lines += ["", f"Pairs ({len(crossed)}):", ""]
        lines += [f"- original {a.original}; copy {a.url}" for a in crossed]
    else:
        lines += ["", f"URLs ({len(source.listed)}):", ""]
        lines += [f"- {url}" for url in source.listed]
    if source.notes:
        lines += ["", f"Notes ({len(source.notes)}):", ""]
        lines += [f"- {note.url}: {note.note}" for note in source.notes]
    return "\n".join(lines) + "\n"


def format_listing_json(listing: Listing, *, pairs_only: bool = False) -> str:
    """Render what a source listed as JSON, for ``--list-only --format json``.

    :param listing: The listing.
    :param pairs_only: For ``pairs --from-dev-user``: include the pairs formed.
    :return: The JSON, with a trailing newline.
    """
    source = listing.source
    payload: dict[str, object] = {
        "cernis_version": __version__,
        "source": {"kind": source.kind, "query": source.query},
        "receipt_ids": list(source.receipt_ids),
        "listed": list(source.listed),
        "notes": [{"url": note.url, "note": note.note} for note in source.notes],
    }
    if pairs_only:
        payload["pairs"] = [
            {"original": a.original, "copy": a.url}
            for a in listing.articles
            if a.original is not None
        ]
    return json.dumps(payload, indent=2) + "\n"


def _show_listing(
    options: RunOptions, listing: Listing, fetches: RunFetches, pairs_only: bool
) -> int:
    """Write a listing for ``--list-only``.

    :param options: The shared options.
    :param listing: The listing.
    :param fetches: The run's fetches.
    :param pairs_only: Whether the command forms pairs.
    :return: The exit code from writing it.
    """
    if options.output_format == "json":
        return _write(options, format_listing_json(listing, pairs_only=pairs_only))
    return _write(options, format_listing(listing, fetches, pairs_only=pairs_only))


@dataclass(frozen=True, kw_only=True)
class SourceOptions:
    """Where ``audit`` or ``pairs`` gets its URLs from, when not the command line.

    :param from_sitemap: A sitemap URL, or ``None``.
    :param include_prefix: With a sitemap, keep only pages under this prefix.
    :param from_dev_user: A DEV username, or ``None``.
    :param limit: The most URLs listed, or ``None``.
    :param list_only: Print the listing and stop.
    """

    from_sitemap: str | None = None
    include_prefix: str | None = None
    from_dev_user: str | None = None
    limit: int | None = None
    list_only: bool = False


def run_audit(
    urls: Sequence[str],
    site_type: str | None,
    options: RunOptions,
    pair_map: Path | None = None,
    source: SourceOptions | None = None,
) -> int:
    """Audit URLs, or the URLs a source lists, and write the report.

    :param urls: The URLs given on the command line.
    :param site_type: The declared site type for every URL, or ``None``.
    :param options: The shared options.
    :param pair_map: A pair map whose site types apply, or ``None``.
    :param source: Where else the URLs come from, or ``None``.
    :return: The exit code: 0 when the audit or listing ran (whatever it
        found), 2 when the arguments conflict, a URL cannot be fetched at
        all, the pair map cannot be read, there is nothing to audit, or the
        report cannot be written.
    """
    source = source or SourceOptions()
    given = [bool(urls), source.from_sitemap is not None, source.from_dev_user is not None]
    if sum(given) != 1:
        print(
            "cernis audit: give URLs, --from-sitemap, or --from-dev-user (exactly one)",
            file=sys.stderr,
        )
        return 2
    if source.include_prefix is not None and source.from_sitemap is None:
        print("cernis audit: --include-prefix needs --from-sitemap", file=sys.stderr)
        return 2
    if (source.limit is not None or source.list_only) and urls:
        print("cernis audit: --limit and --list-only need a source", file=sys.stderr)
        return 2
    if _loopback_refused(options, source):
        return 2
    loaded = _load_map(pair_map, "audit")
    if loaded is None:
        return 2
    site = SiteType(site_type) if site_type is not None else None

    def work(fetches: RunFetches) -> int:
        sources: list[RunSource] = []
        listed: Sequence[str] = urls
        if source.from_sitemap is not None or source.from_dev_user is not None:
            listing = (
                from_sitemap(
                    fetches,
                    source.from_sitemap,
                    include_prefix=source.include_prefix,
                    limit=source.limit,
                    max_documents=options.limits.sitemap_documents,
                )
                if source.from_sitemap is not None
                else from_dev_user(fetches, source.from_dev_user or "", limit=source.limit)
            )
            if source.list_only:
                return _show_listing(options, listing, fetches, pairs_only=False)
            sources.append(listing.source)
            listed = listing.source.listed
        targets = [Target(url=url, site=_site_for(url, site, loaded)) for url in listed]
        return _audit_and_write(options, fetches, targets, (), loaded.sites, sources)

    return _with_fetches(options, work)


def run_pair(
    original: str,
    copy: str,
    original_site: str | None,
    copy_site: str | None,
    pair_map: Path | None,
    options: RunOptions,
) -> int:
    """Audit one original and copy, and write the report.

    :param original: The original's URL.
    :param copy: The copy's URL.
    :param original_site: The original's declared site type, or ``None``.
    :param copy_site: The copy's declared site type, or ``None``.
    :param pair_map: A pair map whose site types and prefixes apply, or ``None``.
    :param options: The shared options.
    :return: The exit code, as for ``audit``; also 2 when the copy is the
        original.
    """
    if _loopback_refused(options, SourceOptions()):
        return 2
    loaded = _load_map(pair_map, "pair")
    if loaded is None:
        return 2
    if normalize_url(original) == normalize_url(copy):
        print("cernis pair: the copy is the same URL as the original", file=sys.stderr)
        return 2
    pair = PairTarget(
        original=Target(
            url=original,
            site=_site_for(original, SiteType(original_site) if original_site else None, loaded),
        ),
        copy=Target(
            url=copy, site=_site_for(copy, SiteType(copy_site) if copy_site else None, loaded)
        ),
    )
    return _run_and_write(options, (), (pair,), loaded.sites)


def run_pairs(
    pair_map: Path | None, options: RunOptions, source: SourceOptions | None = None
) -> int:
    """Audit every pair in a pair map, or a DEV user's cross-posts, and write the report.

    :param pair_map: The pair map, or ``None``.
    :param options: The shared options.
    :param source: ``--from-dev-user``, ``--limit``, and ``--list-only``, or ``None``.
    :return: The exit code, as for ``audit``; also 2 when neither or both
        sources of pairs are given, or the map has no pairs.
    """
    source = source or SourceOptions()
    if source.from_dev_user is None:
        if pair_map is None:
            print("cernis pairs: give --map or --from-dev-user", file=sys.stderr)
            return 2
        if source.limit is not None or source.list_only:
            print("cernis pairs: --limit and --list-only need --from-dev-user", file=sys.stderr)
            return 2
    if _loopback_refused(options, source):
        return 2
    loaded = _load_map(pair_map, "pairs")
    if loaded is None:
        return 2
    if source.from_dev_user is not None:
        username = source.from_dev_user

        def work(fetches: RunFetches) -> int:
            listing = from_dev_user(fetches, username, limit=source.limit)
            if source.list_only:
                return _show_listing(options, listing, fetches, pairs_only=True)
            pairs = [
                PairTarget(
                    original=Target(
                        url=article.original, site=_site_for(article.original, None, loaded)
                    ),
                    copy=Target(url=article.url, site=_site_for(article.url, None, loaded)),
                )
                for article in listing.articles
                if article.original is not None
            ]
            return _audit_and_write(options, fetches, (), pairs, loaded.sites, [listing.source])

        return _with_fetches(options, work)
    if not loaded.pairs:
        print(f"cernis pairs: {pair_map} has no [[pair]]", file=sys.stderr)
        return 2
    declared = loaded.site_types()
    pairs = [
        PairTarget(
            original=Target(
                url=p.original.url,
                site=p.original.site or declared.get(normalize_url(p.original.url)),
            ),
            copy=Target(
                url=p.copy.url, site=p.copy.site or declared.get(normalize_url(p.copy.url))
            ),
        )
        for p in loaded.pairs
    ]
    return _run_and_write(options, (), pairs, loaded.sites)


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
    if args.command in ("audit", "pair", "pairs"):
        options = RunOptions(
            command=args.command,
            output_format=args.format,
            output=args.output,
            cache_dir=args.cache_dir,
            allow_loopback=args.allow_loopback,
            limits=AuditLimits(
                links=LinkLimits(
                    per_page=args.max_links_per_page,
                    per_external_host=args.max_links_per_host,
                ),
                sitemap_documents=args.max_sitemap_documents,
            ),
        )
        if args.command == "pair":
            return run_pair(
                args.original, args.copy, args.original_site, args.copy_site, args.map, options
            )
        source = SourceOptions(
            from_sitemap=getattr(args, "from_sitemap", None),
            include_prefix=getattr(args, "include_prefix", None),
            from_dev_user=args.from_dev_user,
            limit=args.limit,
            list_only=args.list_only,
        )
        if args.command == "audit":
            return run_audit(args.urls, args.site_type, options, args.map, source)
        return run_pairs(args.map, options, source)
    if args.command == "fetch":
        return run_fetch(args.url, args.cache_dir, args.format, args.allow_loopback)
    print(STATUS_MESSAGE)
    return 0
