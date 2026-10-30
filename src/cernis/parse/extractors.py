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
host (``dev.to``), else ``generic``. A WordPress site cannot be recognized by
its host, so it must be declared.

An extractor never guesses: if its selector matches more than one element,
the body is ambiguous and none is returned, with the reason.
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from cernis.parse.html import Link, links_in, visible_text


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

_BY_SITE = {SiteType.DEV: DEV_ARTICLE, SiteType.WORDPRESS: WORDPRESS_ENTRY}
_BY_HOST = {"dev.to": DEV_ARTICLE, "www.dev.to": DEV_ARTICLE}


def choose_extractor(url: str, site: SiteType | None = None) -> Extractor:
    """Choose the extractor for a page.

    :param url: The page's URL (the receipt's ``final_url``).
    :param site: The site type the author declared, if any; it wins over the
        host.
    :return: The extractor.
    """
    if site is not None:
        return _BY_SITE[site]
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    return _BY_HOST.get(host, GENERIC)


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


def read_article(tree: LexborHTMLParser, url: str, site: SiteType | None = None) -> Article:
    """Find and read a page's article body.

    :param tree: The parsed document.
    :param url: The page's URL, for choosing the extractor.
    :param site: The site type the author declared, if any.
    :return: The article body, or the reason there is none.
    """
    extractor = choose_extractor(url, site)
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
