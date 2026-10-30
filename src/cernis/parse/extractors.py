"""Site-aware article-body extractors (DESIGN.md section 3, "Snapshot fields").

An extractor finds the article body: the part of the page the author wrote.
Each has an id and a version, recorded on every snapshot, so a change to an
extractor shows in history as a ``CHECKER`` change, not a page change.

- ``dev.article``: DEV's ``#article-body``.
- ``wordpress.entry``: ``.entry-content`` (classic themes), else
  ``.wp-block-post-content`` (block themes).
- ``generic``: finds no body, ever. ``content_sha256`` is then ``None``, and
  history says ``UNCLASSIFIED`` rather than guess which part is the article.

The extractor is chosen by a declared site type when there is one, else by
the longest matching prefix rule from the pair map, else by host
(``dev.to``), else ``generic`` (:func:`resolve_site`). A WordPress site
cannot be recognized by its host, so it must be declared, one URL at a time
or by prefix.

An extractor never guesses: if its selector matches more than one element,
the body is ambiguous and none is returned, with the reason.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from cernis.model import ExtractorSelection
from cernis.parse.html import Link, links_in, visible_text
from cernis.urls import normalize_url


class SiteType(StrEnum):
    """A site type the author can declare for a URL."""

    DEV = "dev"
    WORDPRESS = "wordpress"


@dataclass(frozen=True, kw_only=True)
class Extractor:
    """A way to find the article body on one kind of site.

    :param id: The extractor id, recorded on snapshots.
    :param version: Its version; any change to what it selects bumps it.
    :param selectors: CSS selectors tried in order; the first that matches
        anything decides.
    """

    id: str
    version: str
    selectors: tuple[str, ...]


DEV_ARTICLE = Extractor(id="dev.article", version="1", selectors=("#article-body",))
WORDPRESS_ENTRY = Extractor(
    id="wordpress.entry", version="1", selectors=(".entry-content", ".wp-block-post-content")
)
GENERIC = Extractor(id="generic", version="1", selectors=())

EXTRACTORS: tuple[Extractor, ...] = (DEV_ARTICLE, WORDPRESS_ENTRY, GENERIC)
"""Every extractor."""

_BY_SITE: dict[SiteType | None, Extractor] = {
    SiteType.DEV: DEV_ARTICLE,
    SiteType.WORDPRESS: WORDPRESS_ENTRY,
    None: GENERIC,
}
_SITE_BY_HOST = {"dev.to": SiteType.DEV, "www.dev.to": SiteType.DEV}


@dataclass(frozen=True, kw_only=True)
class SitePrefix:
    """A rule that every URL under a prefix is on one kind of site.

    :param prefix: An absolute http(s) URL naming a site or a part of one,
        such as ``https://www.kenwalger.com/blog/``.
    :param site: The site type of every URL under it.
    """

    prefix: str
    site: SiteType


def _under(url: str, prefix: str) -> bool:
    """Tell whether a normalized URL is at or under a normalized prefix.

    Matching is by whole path segments, so ``/blog`` covers ``/blog`` and
    ``/blog/a`` but not ``/blogger``.

    :param url: The URL, normalized.
    :param prefix: The prefix, normalized.
    :return: Whether the URL is under the prefix.
    """
    if url == prefix:
        return True
    head = prefix if prefix.endswith("/") else prefix + "/"
    return url.startswith(head) or url.startswith(prefix + "?")


def prefix_site(url: str, prefixes: Sequence[SitePrefix]) -> SiteType | None:
    """Find the site type the longest matching prefix gives a URL.

    Both sides are compared after URL normalization
    (:func:`cernis.urls.normalize_url`), so scheme and host case, default
    ports, and a trailing slash do not matter, while ``http`` and ``https``,
    or ``www`` and no ``www``, do.

    :param url: The URL.
    :param prefixes: The prefix rules.
    :return: The site type of the longest prefix the URL is under, or ``None``.
    """
    target = normalize_url(url)
    best: tuple[int, SiteType] | None = None
    for rule in prefixes:
        prefix = normalize_url(rule.prefix)
        if _under(target, prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), rule.site)
    return best[1] if best else None


def resolve_site(
    url: str, declared: SiteType | None = None, prefixes: Sequence[SitePrefix] = ()
) -> tuple[SiteType | None, ExtractorSelection]:
    """Decide a page's site type, and which rule decided it.

    The order is: a declaration (``--site-type``, or the URL's own entry in
    the pair map), then the longest matching prefix rule, then a known host
    (``dev.to``), then nothing.

    :param url: The page's URL.
    :param declared: The declared site type, if any.
    :param prefixes: Prefix rules from the pair map.
    :return: The site type (``None`` if no rule gives one) and the rule.
    """
    if declared is not None:
        return declared, ExtractorSelection.DECLARED
    by_prefix = prefix_site(url, prefixes)
    if by_prefix is not None:
        return by_prefix, ExtractorSelection.PREFIX
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    if host in _SITE_BY_HOST:
        return _SITE_BY_HOST[host], ExtractorSelection.HOST
    return None, ExtractorSelection.GENERIC


def select_extractor(
    url: str, site: SiteType | None = None, prefixes: Sequence[SitePrefix] = ()
) -> tuple[Extractor, ExtractorSelection]:
    """Choose the extractor for a page, and say how it was chosen.

    :param url: The page's URL (the receipt's ``final_url``).
    :param site: The site type the author declared, if any; it wins over
        prefixes and the host.
    :param prefixes: Prefix rules from the pair map.
    :return: The extractor, and whether it came from the declaration, a
        prefix rule, the host, or none of them.
    """
    found, selection = resolve_site(url, site, prefixes)
    return _BY_SITE[found], selection


def effective_site(
    url: str, declared: SiteType | None = None, prefixes: Sequence[SitePrefix] = ()
) -> SiteType | None:
    """Return a page's site type by :func:`resolve_site`'s rules.

    :param url: The page's URL.
    :param declared: The declared site type, if any.
    :param prefixes: Prefix rules from the pair map.
    :return: The site type, or ``None`` if no rule gives one.
    """
    return resolve_site(url, declared, prefixes)[0]


def choose_extractor(url: str, site: SiteType | None = None) -> Extractor:
    """Choose the extractor for a page.

    :param url: The page's URL (the receipt's ``final_url``).
    :param site: The site type the author declared, if any; it wins over the
        host.
    :return: The extractor.
    """
    return select_extractor(url, site)[0]


@dataclass(frozen=True, kw_only=True)
class BodyMatch:
    """What an extractor found.

    :param node: The article body element, or ``None`` if none was found.
    :param problem: Why there is no body, or ``None`` if there is one. The
        generic extractor's "no body" is by design and has no problem.
    """

    node: LexborNode | None
    problem: str | None


def find_body(tree: LexborHTMLParser, extractor: Extractor) -> BodyMatch:
    """Find the article body with an extractor.

    :param tree: The parsed document.
    :param extractor: The extractor.
    :return: The body element, or the reason there is none.
    """
    for selector in extractor.selectors:
        nodes = tree.css(selector)
        if len(nodes) == 1:
            return BodyMatch(node=nodes[0], problem=None)
        if len(nodes) > 1:
            return BodyMatch(
                node=None,
                problem=(
                    f"{extractor.id}: {len(nodes)} elements match {selector!r}, "
                    "so the article body is ambiguous"
                ),
            )
    if not extractor.selectors:
        return BodyMatch(node=None, problem=None)
    tried = ", ".join(repr(selector) for selector in extractor.selectors)
    return BodyMatch(node=None, problem=f"{extractor.id}: no element matches {tried}")


@dataclass(frozen=True, kw_only=True)
class Article:
    """The article body, as an extractor found it.

    :param extractor: The extractor used.
    :param found: Whether a body was found.
    :param text: The body's visible text, normalized, or ``None`` if not found.
    :param links: The ``<a href>`` links in the body, in order; empty if not
        found.
    :param problem: Why no body was found, or ``None``.
    """

    extractor: Extractor
    found: bool
    text: str | None
    links: tuple[Link, ...]
    problem: str | None


def read_article(
    tree: LexborHTMLParser,
    url: str,
    site: SiteType | None = None,
    prefixes: Sequence[SitePrefix] = (),
) -> Article:
    """Find and read a page's article body.

    :param tree: The parsed document.
    :param url: The page's URL, for choosing the extractor.
    :param site: The site type the author declared, if any.
    :param prefixes: Prefix rules from the pair map.
    :return: The article body, or the reason there is none.
    """
    extractor = select_extractor(url, site, prefixes)[0]
    match = find_body(tree, extractor)
    if match.node is None:
        return Article(extractor=extractor, found=False, text=None, links=(), problem=match.problem)
    return Article(
        extractor=extractor,
        found=True,
        text=visible_text(match.node),
        links=links_in(match.node),
        problem=None,
    )
