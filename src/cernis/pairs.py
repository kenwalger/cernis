"""The pair map: which article is the original and which the copy (docs/PAIR-MAP.md).

A pair map is a TOML file that lists original and copy URLs and, for each
URL, may declare its site type. A declared site type chooses the article-body
extractor and overrides host detection (DESIGN.md section 3). Phase 4's
``cernis pairs --map`` runs the pair check over it; this module only reads
and validates it.

Loading is strict, so a typo fails loudly instead of being ignored: unknown
keys, a missing URL, a URL that is not absolute http(s), an unknown site
type, a pair whose copy is its own original, and one URL declared with two
different site types are all errors, each naming where it is.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from cernis.parse.extractors import SiteType
from cernis.urls import is_absolute_http_url, normalize_url

FORMAT_VERSION = 1
"""The pair map format this module reads."""


class PairMapError(ValueError):
    """Raised when a pair map cannot be read or breaks a rule."""


@dataclass(frozen=True, kw_only=True)
class SiteUrl:
    """One URL in the map, with its declared site type.

    :param url: The URL, as written in the map.
    :param site: The declared site type, or ``None`` to use host detection.
    """

    url: str
    site: SiteType | None


@dataclass(frozen=True, kw_only=True)
class Pair:
    """One original and its copy.

    :param original: The original article.
    :param copy: The copy, which should name the original as its canonical.
    """

    original: SiteUrl
    copy: SiteUrl


@dataclass(frozen=True, kw_only=True)
class PairMap:
    """A loaded pair map.

    :param pairs: The pairs, in file order.
    """

    pairs: tuple[Pair, ...]

    def site_types(self) -> dict[str, SiteType]:
        """Return every declared site type, by normalized URL.

        :return: The declarations; URLs with no ``site`` are left out.
        """
        declared: dict[str, SiteType] = {}
        for pair in self.pairs:
            for entry in (pair.original, pair.copy):
                if entry.site is not None:
                    declared[normalize_url(entry.url)] = entry.site
        return declared


def _site_url(value: object, where: str) -> SiteUrl:
    """Read one ``original`` or ``copy`` table.

    :param value: The TOML value.
    :param where: Where it is, for messages, such as ``pair 2, copy``.
    :return: The URL and its site type.
    :raises PairMapError: If the table breaks a rule.
    """
    if not isinstance(value, dict):
        raise PairMapError(f"{where}: must be a table with a url (and optionally a site)")
    unknown = sorted(set(value) - {"url", "site"})
    if unknown:
        raise PairMapError(f"{where}: unknown key {', '.join(unknown)}")
    url = value.get("url")
    if not isinstance(url, str) or not is_absolute_http_url(url):
        raise PairMapError(f"{where}: url must be an absolute http or https URL, got {url!r}")
    site = value.get("site")
    if site is None:
        return SiteUrl(url=url, site=None)
    try:
        return SiteUrl(url=url, site=SiteType(site))
    except ValueError:
        allowed = ", ".join(member.value for member in SiteType)
        raise PairMapError(f"{where}: site must be one of {allowed}, got {site!r}") from None


def parse_pair_map(text: str) -> PairMap:
    """Read a pair map from TOML text.

    :param text: The TOML.
    :return: The pair map.
    :raises PairMapError: If the TOML does not parse or breaks a rule.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PairMapError(f"not valid TOML: {exc}") from exc
    unknown = sorted(set(data) - {"format", "pair"})
    if unknown:
        raise PairMapError(f"unknown top-level key {', '.join(unknown)}")
    if data.get("format") != FORMAT_VERSION:
        raise PairMapError(f"format must be {FORMAT_VERSION}, got {data.get('format')!r}")
    entries = data.get("pair")
    if not isinstance(entries, list) or not entries:
        raise PairMapError("there must be at least one [[pair]]")
    pairs: list[Pair] = []
    declared: dict[str, tuple[SiteType, str]] = {}
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise PairMapError(f"pair {number}: must be a table")
        unknown = sorted(set(entry) - {"original", "copy"})
        if unknown:
            raise PairMapError(f"pair {number}: unknown key {', '.join(unknown)}")
        original = _site_url(entry.get("original"), f"pair {number}, original")
        copy = _site_url(entry.get("copy"), f"pair {number}, copy")
        if normalize_url(original.url) == normalize_url(copy.url):
            raise PairMapError(f"pair {number}: the copy is the same URL as the original")
        for role, item in (("original", original), ("copy", copy)):
            if item.site is None:
                continue
            key = normalize_url(item.url)
            if key in declared and declared[key][0] != item.site:
                first_site, first_where = declared[key]
                raise PairMapError(
                    f"pair {number}, {role}: {item.url} is declared as {item.site} here "
                    f"but as {first_site} in {first_where}"
                )
            declared.setdefault(key, (item.site, f"pair {number}, {role}"))
        pairs.append(Pair(original=original, copy=copy))
    return PairMap(pairs=tuple(pairs))


def load_pair_map(path: Path) -> PairMap:
    """Read a pair map file.

    :param path: The file.
    :return: The pair map.
    :raises PairMapError: If the file cannot be read, does not parse, or
        breaks a rule.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PairMapError(f"cannot read {path}: {exc}") from exc
    return parse_pair_map(text)
