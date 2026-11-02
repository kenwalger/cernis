"""The AI crawlers ``epi.robots.access`` reports on (``data/ai_crawlers.toml``).

The list is data, not code, so it can change without a code change; its
``version`` is part of every ``epi.robots.access`` finding's check version,
so a change to the list is a ``CHECKER`` change in history (DESIGN.md
section 5). Each entry names its operator and the operator's own page
documenting the token.
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from cernis.urls import is_absolute_http_url

_TOKEN_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-")


class CrawlerListError(ValueError):
    """Raised when the crawler list breaks a rule (a bug in the shipped data)."""


@dataclass(frozen=True, kw_only=True)
class Crawler:
    """One AI crawler or robots.txt product token.

    :param token: The product token, as its operator writes it; robots.txt
        matching ignores case (RFC 9309 section 2.2.1).
    :param operator: Who runs it.
    :param purpose: What the operator says it is for, in a few words.
    :param source: The operator's page documenting the token.
    """

    token: str
    operator: str
    purpose: str
    source: str


@dataclass(frozen=True, kw_only=True)
class CrawlerList:
    """The crawler list and its version.

    :param version: The list's version.
    :param crawlers: The entries, in file order.
    """

    version: int
    crawlers: tuple[Crawler, ...]


def parse_crawler_list(text: str) -> CrawlerList:
    """Read a crawler list from TOML text.

    :param text: The TOML.
    :return: The list.
    :raises CrawlerListError: If an entry is malformed, a token is not a
        valid RFC 9309 product token, or a token repeats (ignoring case).
    """
    data = tomllib.loads(text)
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise CrawlerListError(f"version must be a positive integer, got {version!r}")
    entries = data.get("crawler")
    if not isinstance(entries, list) or not entries:
        raise CrawlerListError("there must be at least one [[crawler]]")
    crawlers: list[Crawler] = []
    seen: set[str] = set()
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry) != {"token", "operator", "purpose", "source"}:
            raise CrawlerListError(
                f"crawler {number}: must have exactly token, operator, purpose, and source"
            )
        values = {key: entry[key] for key in ("token", "operator", "purpose", "source")}
        if not all(isinstance(value, str) and value.strip() for value in values.values()):
            raise CrawlerListError(f"crawler {number}: every field must be non-empty text")
        token = values["token"]
        if not set(token) <= _TOKEN_CHARACTERS:
            raise CrawlerListError(f"crawler {number}: {token!r} is not a product token")
        if token.lower() in seen:
            raise CrawlerListError(f"crawler {number}: {token} repeats")
        if not is_absolute_http_url(values["source"]):
            raise CrawlerListError(f"crawler {number}: source must be an absolute http(s) URL")
        seen.add(token.lower())
        crawlers.append(Crawler(**values))
    return CrawlerList(version=version, crawlers=tuple(crawlers))


@cache
def crawler_list() -> CrawlerList:
    """Load the shipped crawler list, once.

    :return: The list.
    """
    text = files("cernis").joinpath("data", "ai_crawlers.toml").read_text(encoding="utf-8")
    return parse_crawler_list(text)
