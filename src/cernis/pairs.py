"""The pair map: which article is the original and which the copy (docs/PAIR-MAP.md).

A pair map is a TOML file that lists original and copy URLs and, for each
URL, may declare its site type, and that may give site types to whole parts
of a site by URL prefix (``[[site]]``). A site type chooses the article-body
extractor (DESIGN.md section 3): a URL's own declaration wins, then the
longest matching prefix, then host detection. ``cernis audit --map`` reads
it for site types, and ``cernis pairs --map`` runs the pair check over it.
A ``[[pair]]`` names one original and either one ``copy`` or several
``copies`` (Session 5b); several copies load as one :class:`Pair` each.

Loading is strict, so a typo fails loudly instead of being ignored: unknown
keys, a missing URL, a URL that is not absolute http(s), an unknown site
type, a pair whose copy is its own original, one URL declared with two
different site types, a prefix with a query or fragment, and one prefix
given two different site types are all errors, each naming where it is.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cernis.parse.extractors import SitePrefix, SiteType
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
        A map entry with ``copies`` gives one pair per copy, sharing the
        original.
    """

    original: SiteUrl
    copy: SiteUrl


@dataclass(frozen=True, kw_only=True)
class PairMap:
    """A loaded pair map.

    :param pairs: The pairs, in file order.
    :param sites: The prefix rules, in file order.
    """

    pairs: tuple[Pair, ...]
    sites: tuple[SitePrefix, ...] = ()

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


def _site_type(value: object, where: str) -> SiteType:
    """Read a site type.

    :param value: The TOML value.
    :param where: Where it is, for messages.
    :return: The site type.
    :raises PairMapError: If it is not ``dev`` or ``wordpress``.
    """
    if isinstance(value, str) and value in {member.value for member in SiteType}:
        return SiteType(value)
    allowed = ", ".join(member.value for member in SiteType)
    raise PairMapError(f"{where}: must be one of {allowed}, got {value!r}")


def _site_prefixes(entries: object) -> tuple[SitePrefix, ...]:
    """Read the ``[[site]]`` prefix rules.

    :param entries: The TOML value of ``site``, or ``None``.
    :return: The rules, in file order.
    :raises PairMapError: If a rule breaks a rule.
    """
    if entries is None:
        return ()
    if not isinstance(entries, list):
        raise PairMapError("site must be an array of tables: [[site]]")
    rules: list[SitePrefix] = []
    seen: dict[str, tuple[SiteType, int]] = {}
    for number, entry in enumerate(entries, start=1):
        where = f"site {number}"
        if not isinstance(entry, dict):
            raise PairMapError(f"{where}: must be a table")
        unknown = sorted(set(entry) - {"prefix", "type"})
        if unknown:
            raise PairMapError(f"{where}: unknown key {', '.join(unknown)}")
        prefix = entry.get("prefix")
        if not isinstance(prefix, str) or not is_absolute_http_url(prefix):
            raise PairMapError(
                f"{where}: prefix must be an absolute http or https URL, got {prefix!r}"
            )
        parts = urlsplit(prefix)
        if parts.query or parts.fragment or "?" in prefix or "#" in prefix:
            raise PairMapError(f"{where}: prefix must not have a query or a fragment")
        site = _site_type(entry.get("type"), f"{where}, type")
        key = normalize_url(prefix)
        if key in seen and seen[key][0] is not site:
            raise PairMapError(
                f"{where}: {prefix} is given type {site} here but {seen[key][0]} "
                f"in site {seen[key][1]}"
            )
        seen.setdefault(key, (site, number))
        rules.append(SitePrefix(prefix=prefix, site=site))
    return tuple(rules)


def _copies(entry: dict[str, object], number: int) -> list[tuple[str, SiteUrl]]:
    """Read a pair's ``copy`` table or ``copies`` array, exactly one of them.

    :param entry: The ``[[pair]]`` table.
    :param number: The pair's number, for messages.
    :return: Each copy with where it is (``copy``, or ``copy 2``), in order.
    :raises PairMapError: If neither or both are given, or ``copies`` is
        not a non-empty array of tables.
    """
    if ("copy" in entry) == ("copies" in entry):
        raise PairMapError(f"pair {number}: give exactly one of copy or copies")
    if "copy" in entry:
        return [("copy", _site_url(entry["copy"], f"pair {number}, copy"))]
    copies = entry["copies"]
    if not isinstance(copies, list) or not copies:
        raise PairMapError(f"pair {number}: copies must be a non-empty array of tables")
    return [
        (f"copy {index}", _site_url(item, f"pair {number}, copy {index}"))
        for index, item in enumerate(copies, start=1)
    ]


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
    unknown = sorted(set(data) - {"format", "pair", "site"})
    if unknown:
        raise PairMapError(f"unknown top-level key {', '.join(unknown)}")
    if data.get("format") != FORMAT_VERSION:
        raise PairMapError(f"format must be {FORMAT_VERSION}, got {data.get('format')!r}")
    sites = _site_prefixes(data.get("site"))
    entries = data.get("pair", [])
    if not isinstance(entries, list):
        raise PairMapError("pair must be an array of tables: [[pair]]")
    if not entries and not sites:
        raise PairMapError("there must be at least one [[pair]] or [[site]]")
    pairs: list[Pair] = []
    declared: dict[str, tuple[SiteType, str]] = {}
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise PairMapError(f"pair {number}: must be a table")
        unknown = sorted(set(entry) - {"original", "copy", "copies"})
        if unknown:
            raise PairMapError(f"pair {number}: unknown key {', '.join(unknown)}")
        original = _site_url(entry.get("original"), f"pair {number}, original")
        copies = _copies(entry, number)
        seen_copies: set[str] = set()
        for role, copy in copies:
            if normalize_url(original.url) == normalize_url(copy.url):
                raise PairMapError(f"pair {number}: the {role} is the same URL as the original")
            if normalize_url(copy.url) in seen_copies:
                raise PairMapError(f"pair {number}: {copy.url} is listed as a copy twice")
            seen_copies.add(normalize_url(copy.url))
        for role, item in (("original", original), *copies):
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
        pairs.extend(Pair(original=original, copy=copy) for _, copy in copies)
    return PairMap(pairs=tuple(pairs), sites=sites)


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
