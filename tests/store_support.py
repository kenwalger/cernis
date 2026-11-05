"""Runs for the store tests: real audits of a scripted page, at a chosen time."""

from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fetch_support import Reply, Site, make_fetcher, respond

from cernis.audit import Target, audit
from cernis.model import Run
from cernis.parse import SiteType

PAGE = "https://blog.example.com/a-post/"
"""The page every store test run audits."""

HTML = (
    b"<!doctype html><html lang='en'><head><title>A post</title>"
    b"<link rel='canonical' href='https://blog.example.com/a-post/'></head>"
    b"<body><article><p>Unchanged text.</p></article></body></html>"
)
"""The page's body: the same in every run, so runs observe identical content."""

START = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
"""When the first run starts."""


def clock(start: datetime) -> Callable[[], datetime]:
    """Return a clock that reads ``start``, then a second later each time.

    :param start: The first reading.
    :return: The clock.
    """
    moments: Iterator[datetime] = (start + timedelta(seconds=n) for n in range(1000))
    return lambda: next(moments)


def make_run(
    tmp_path: Path,
    start: datetime = START,
    body: bytes = HTML,
    suffix: str = "000000",
    *,
    url: str = PAGE,
    site: SiteType | None = SiteType.OWNED,
    routes: Mapping[str, Reply] | None = None,
) -> Run:
    """Audit the page once, starting at ``start``.

    The fetcher's own clock is fixed, so two runs of the same body record
    identical receipts; only the run (its id and times) differs. The run id's
    suffix is fixed too, so a test can make two runs share an id.

    :param tmp_path: A directory for this run's cache.
    :param start: When the run starts; with ``suffix``, it sets the run id.
    :param body: The page's body.
    :param suffix: The run id's suffix.
    :param url: The page's URL.
    :param site: The page's declared site type; ``None`` to detect it from the host.
    :param routes: More replies, by URL, such as a canonical target's.
    :return: The run.
    """
    web = Site()
    web.add(url, respond(200, body, {"content-type": "text/html; charset=utf-8"}))
    for route, reply in (routes or {}).items():
        web.add(route, reply)
    cache = tmp_path / f"cache-{start:%H%M%S}-{suffix}"
    fetcher = make_fetcher(web, cache, min_interval=0)
    return audit(
        [Target(url=url, site=site)],
        fetcher,
        now=clock(start),
        run_suffix=lambda: suffix,
    )
