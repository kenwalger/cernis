"""Reading sitemaps: discovery, indexes, and gzip (sitemaps.org protocol).

Used by ``epi.sitemap.listed`` and by ``cernis audit --from-sitemap``.

- **Discovery** for a page: the ``Sitemap:`` lines in its origin's
  robots.txt; if none of them is a sitemap, ``sitemap.xml``, then
  ``wp-sitemap.xml``, first at the site's root (the ``[[site]]`` prefix that
  covers the page, such as a WordPress install under ``/blog/``) and then at
  the origin's root. The first that is a sitemap is read.
- **Indexes** (``<sitemapindex>``) are followed, child by child, breadth
  first, at most ``max_documents`` documents per read and at most
  ``max_depth`` levels below the first. Only children on the index's own
  host are followed (sitemaps.org: an index lists sitemaps of its own
  site); the others are recorded, not fetched. Each document is fetched once
  per run, through the normal fetcher.
- **Caps**: at most :data:`MAX_ENTRIES_PER_DOCUMENT` ``<loc>`` values are
  read from one document (the protocol's own limit) and
  :data:`MAX_ENTRIES_PER_READ` in all; a cap reached is ``limit_reached``,
  never a silent skip. The queue of children never holds more than the
  documents left to read.
- **gzip**: a body that starts with the gzip magic bytes (a ``.xml.gz``
  sitemap, served as a file rather than with ``Content-Encoding``) is
  decompressed here, every member of it, never past the fetcher's body
  limit.
- **Safety**: documents are parsed by expat with handlers that refuse any
  ``DOCTYPE`` or entity declaration, whatever the encoding (a sitemap needs
  neither), so entity expansion cannot happen. A ``<loc>`` the fetcher would
  not fetch (not an absolute http(s) URL that parses, or with user
  information) is counted, never used.

Nothing here judges anything; it records what was read, what was missing,
and what could not be read, for the check or the listing to report.
"""

import zlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from xml.parsers import expat

import httpx

from cernis.checks.epitext import unanswered
from cernis.checks.outcomes import Unreadable
from cernis.fetch import FetchError, FetchResult
from cernis.fetch.client import url_problem
from cernis.fetch.robots import robots_url_for
from cernis.model import Actor, Evidence, ReasonCode
from cernis.urls import is_absolute_http_url, normalize_url

_GZIP_MAGIC = b"\x1f\x8b"

MAX_ENTRIES_PER_DOCUMENT = 50_000
"""The most ``<loc>`` values read from one sitemap document (sitemaps.org's limit)."""

MAX_ENTRIES_PER_READ = 200_000
"""The most page entries one read of a site's sitemaps keeps."""

NEWS_NAMESPACE = "http://www.google.com/schemas/sitemap-news/0.9"
"""The Google News sitemap namespace: such a sitemap lists only recent articles."""

ABSENT_STATUSES: frozenset[int] = frozenset({404, 410})
"""The statuses that mean there is no sitemap at a URL."""


def fetchable(url: str) -> bool:
    """Tell whether a URL from a document is one the fetcher would fetch.

    :param url: The URL, as written.
    :return: Whether it is an absolute http(s) URL that parses, with no user
        information.
    """
    return is_absolute_http_url(url) and url_problem(url) is None


@dataclass(frozen=True, kw_only=True)
class ParsedSitemap:
    """What one sitemap document holds.

    :param kind: ``urlset`` or ``sitemapindex``, or ``None`` if it is neither.
    :param locs: Every ``<loc>`` value, stripped, in order, up to the cap.
    :param problem: Why it could not be read as a sitemap, or ``None``.
    :param capped: Whether ``<loc>`` values past the cap were left unread.
    :param news: Whether it uses the Google News sitemap namespace.
    """

    kind: str | None
    locs: tuple[str, ...]
    problem: str | None
    capped: bool = False
    news: bool = False


class _Refused(Exception):
    """Raised inside the parser at a DOCTYPE or entity declaration."""


class _NotSitemap(Exception):
    """Raised inside the parser at a root element that is not a sitemap's."""


def _inflate(body: bytes, limit: int) -> tuple[bytes | None, str | None]:
    """Decompress every member of a gzip body, never past the limit.

    :param body: The gzip data.
    :param limit: The most bytes it may expand to.
    :return: The data, or ``None`` with the problem.
    """
    out = bytearray()
    data = body
    while data:
        inflater = zlib.decompressobj(zlib.MAX_WBITS | 16)
        try:
            out += inflater.decompress(data, limit + 1 - len(out))
        except zlib.error as exc:
            return None, f"the gzip data is corrupt ({exc})"
        if len(out) > limit or inflater.unconsumed_tail:
            return None, f"it expands past Cernis's {limit}-byte limit"
        if not inflater.eof:
            return None, "the gzip data is cut off"
        data = inflater.unused_data
    return bytes(out), None


def parse_sitemap(
    body: bytes, *, limit: int, max_entries: int = MAX_ENTRIES_PER_DOCUMENT
) -> ParsedSitemap:
    """Read a sitemap document, gzipped or not. Never raises on bad input.

    :param body: The body as fetched.
    :param limit: The most bytes a gzipped body may expand to.
    :param max_entries: The most ``<loc>`` values read.
    :return: The document's kind and locations, or the problem.
    """
    data: bytes | None = body
    if body.startswith(_GZIP_MAGIC):
        data, problem = _inflate(body, limit)
        if data is None:
            return ParsedSitemap(kind=None, locs=(), problem=problem)
    assert data is not None
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    stack: list[str] = []
    locs: list[str] = []
    text: list[str] = []
    state = {"root": "", "capped": False, "news": False, "in_loc": False}

    def refuse(*_: object) -> None:
        raise _Refused

    def refuse_reference(*_: object) -> int:
        raise _Refused

    def start(name: str, _attributes: dict[str, str]) -> None:
        uri, _, local = name.rpartition(" ")
        if uri == NEWS_NAMESPACE:
            state["news"] = True
        if not stack:
            if local not in ("urlset", "sitemapindex"):
                state["root"] = local
                raise _NotSitemap
            state["root"] = local
        entry = "url" if state["root"] == "urlset" else "sitemap"
        stack.append(local)
        if local == "loc" and len(stack) == 3 and stack[1] == entry:
            state["in_loc"] = True
            text.clear()

    def end(name: str) -> None:
        if state["in_loc"] and name.rpartition(" ")[2] == "loc":
            value = "".join(text).strip()
            if value:
                if len(locs) >= max_entries:
                    state["capped"] = True
                else:
                    locs.append(value)
            state["in_loc"] = False
        stack.pop()

    def characters(chunk: str) -> None:
        if state["in_loc"]:
            text.append(chunk)

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.UnparsedEntityDeclHandler = refuse
    parser.NotationDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse_reference
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    try:
        parser.Parse(data, True)
    except _Refused:
        return ParsedSitemap(
            kind=None,
            locs=(),
            problem="it declares a DOCTYPE or entities, which Cernis does not read",
        )
    except _NotSitemap:
        return ParsedSitemap(
            kind=None, locs=(), problem=f"its root element is <{state['root']}>, not a sitemap"
        )
    except expat.ExpatError as exc:
        return ParsedSitemap(kind=None, locs=(), problem=f"it is not well-formed XML ({exc})")
    return ParsedSitemap(
        kind=str(state["root"]),
        locs=tuple(locs),
        problem=None,
        capped=bool(state["capped"]),
        news=bool(state["news"]),
    )


@dataclass(frozen=True, kw_only=True)
class SitemapDocument:
    """One sitemap document Cernis tried to read.

    :param url: Its URL.
    :param receipt_id: The receipt of its fetch, or of the robots.txt or
        index that named it when the fetcher would not fetch it at all.
    :param status: The status it answered, or ``None`` if there was none.
    :param kind: ``urlset`` or ``sitemapindex`` if it was read as one.
    :param missing: Whether it answered 404 or 410, so there is no sitemap
        at that URL.
    :param unreadable: Why it was not read, when it was not missing and not read.
    :param news: Whether it is a Google News sitemap (recent articles only).
    """

    url: str
    receipt_id: str
    status: int | None
    kind: str | None
    missing: bool
    unreadable: Unreadable | None
    news: bool = False


@dataclass(frozen=True, kw_only=True)
class SitemapEntry:
    """One page a sitemap lists.

    :param loc: The ``<loc>`` value.
    :param key: The value, normalized (:func:`cernis.urls.normalize_url`).
    :param sitemap_url: The ``<urlset>`` that lists it.
    :param receipt_id: That document's receipt.
    """

    loc: str
    key: str
    sitemap_url: str
    receipt_id: str


@dataclass(frozen=True, kw_only=True)
class SitemapRead:
    """Everything one read of a site's sitemaps found.

    :param roots: The URLs the read started from, in order.
    :param documents: Every document tried, in the order fetched.
    :param entries: Every page the ``<urlset>`` documents list, in order.
    :param limit_reached: Whether documents or entries were left unread
        because of a limit (documents, index depth, or entries).
    :param robots_receipt_id: The robots.txt receipt the ``Sitemap:`` lines
        came from, for discovery; ``None`` otherwise.
    :param robots_sitemaps: The ``Sitemap:`` lines robots.txt listed.
    :param offsite_children: Child sitemaps an index named on another host,
        not followed.
    :param unusable_locs: How many ``<loc>`` values were not URLs the fetcher
        would fetch.
    """

    roots: tuple[str, ...]
    documents: tuple[SitemapDocument, ...]
    entries: tuple[SitemapEntry, ...]
    limit_reached: bool
    robots_receipt_id: str | None = None
    robots_sitemaps: tuple[str, ...] = ()
    offsite_children: tuple[str, ...] = ()
    unusable_locs: int = 0

    @property
    def found(self) -> bool:
        """Whether at least one document was read as a sitemap."""
        return any(doc.kind is not None for doc in self.documents)

    @property
    def complete(self) -> bool:
        """Whether every document reached was read, and no limit stopped the read."""
        return not self.limit_reached and all(
            doc.kind is not None or doc.missing for doc in self.documents
        )

    @property
    def news(self) -> bool:
        """Whether any document read is a Google News sitemap."""
        return any(doc.news for doc in self.documents)


Fetch = Callable[[str], FetchResult]
"""Fetches a URL for the run (each distinct URL once)."""


def _unreadable(url: str, receipt_id: str, why: str, observed: str) -> Unreadable:
    """Describe a document that could not be read.

    :param url: The document's URL.
    :param receipt_id: The receipt the evidence cites.
    :param why: Why, in a clause naming the URL.
    :param observed: What was observed.
    :return: The reason.
    """
    return Unreadable(
        reason_code=ReasonCode.FETCH_FAILED,
        why=why,
        evidence=(Evidence(receipt_id=receipt_id, location=url, observed=observed),),
        actor=Actor.UNKNOWN,
    )


def _document(url: str, result: FetchResult, limit: int) -> tuple[SitemapDocument, ParsedSitemap]:
    """Record one fetched document and read it.

    :param url: The document's URL.
    :param result: Its fetch.
    :param limit: The body limit, for gzip.
    :return: The record, and what it holds.
    """
    nothing = ParsedSitemap(kind=None, locs=(), problem=None)
    reason = unanswered(result, Actor.UNKNOWN)
    final = result.final
    if reason is not None:
        reason = replace(reason, why=f"{url} could not be read: {reason.why}")
        receipt_id = final.id if final is not None else reason.evidence[0].receipt_id
        status = final.status_code if final is not None else None
        document = SitemapDocument(
            url=url,
            receipt_id=receipt_id,
            status=status,
            kind=None,
            missing=False,
            unreadable=reason,
        )
        return document, nothing
    assert final is not None
    status = final.status_code
    if status is None or (not 200 <= status <= 299 and status != 304):
        missing = status in ABSENT_STATUSES
        document = SitemapDocument(
            url=url,
            receipt_id=final.id,
            status=status,
            kind=None,
            missing=missing,
            unreadable=None
            if missing
            else _unreadable(url, final.id, f"{url} answered {status}", f"answered {status}"),
        )
        return document, nothing
    if final.body_truncated_at is not None or result.body is None:
        why = (
            f"{url} is longer than Cernis's {final.body_truncated_at}-byte limit"
            if final.body_truncated_at is not None
            else f"{url} has no body Cernis could read"
        )
        document = SitemapDocument(
            url=url,
            receipt_id=final.id,
            status=status,
            kind=None,
            missing=False,
            unreadable=_unreadable(url, final.id, why, why),
        )
        return document, nothing
    parsed = parse_sitemap(result.body, limit=limit)
    unreadable = None
    if parsed.problem is not None:
        unreadable = _unreadable(
            url,
            final.id,
            f"{url} is not a sitemap Cernis can read: {parsed.problem}",
            parsed.problem,
        )
    document = SitemapDocument(
        url=url,
        receipt_id=final.id,
        status=status,
        kind=parsed.kind,
        missing=False,
        unreadable=unreadable,
        news=parsed.news,
    )
    return document, parsed


def _host(url: str) -> str:
    """Return a URL's host, lowercase.

    :param url: A URL the fetcher would fetch.
    :return: The host.
    """
    return (httpx.URL(url).host or "").lower()


def read_sitemaps(
    fetch: Fetch,
    roots: list[str],
    *,
    limit: int,
    max_documents: int = 50,
    max_depth: int = 2,
    named_by: str | None = None,
) -> SitemapRead:
    """Read sitemaps from their root URLs, following indexes.

    :param fetch: Fetches a URL for the run.
    :param roots: The URLs to start from.
    :param limit: The body limit, for gzip.
    :param max_documents: The most documents read.
    :param max_depth: The most index levels followed below the roots.
    :param named_by: The receipt of what named the roots (a robots.txt), for
        a root the fetcher would not fetch; ``None`` if the roots were given
        directly, in which case such a root's ``FetchError`` propagates.
    :return: What was read.
    :raises FetchError: If a root given directly cannot be fetched at all.
    """
    documents: list[SitemapDocument] = []
    entries: list[SitemapEntry] = []
    seen: set[str] = set()
    queue: list[tuple[str, int, str | None]] = [(url, 0, named_by) for url in roots]
    offsite: list[str] = []
    unusable = 0
    limit_reached = False
    while queue:
        url, depth, parent = queue.pop(0)
        if len(documents) >= max_documents:
            limit_reached = True
            break
        try:
            key = str(httpx.URL(url))
            if key in seen:
                continue
            seen.add(key)
            result = fetch(url)
        except (FetchError, httpx.InvalidURL) as exc:
            if parent is None:
                raise FetchError(str(exc)) from exc
            documents.append(
                SitemapDocument(
                    url=url,
                    receipt_id=parent,
                    status=None,
                    kind=None,
                    missing=False,
                    unreadable=_unreadable(
                        url, parent, f"Cernis cannot fetch {url}: {exc}", str(exc)
                    ),
                )
            )
            continue
        document, parsed = _document(url, result, limit)
        documents.append(document)
        limit_reached = limit_reached or parsed.capped
        if parsed.kind == "urlset":
            for loc in parsed.locs:
                if not fetchable(loc):
                    unusable += 1
                elif len(entries) >= MAX_ENTRIES_PER_READ:
                    limit_reached = True
                    break
                else:
                    entries.append(
                        SitemapEntry(
                            loc=loc,
                            key=normalize_url(loc),
                            sitemap_url=url,
                            receipt_id=document.receipt_id,
                        )
                    )
        elif parsed.kind == "sitemapindex":
            host = _host(url)
            children: list[str] = []
            for loc in parsed.locs:
                # A child the fetcher would refuse is still queued, so it is
                # recorded as an unread document and the read is incomplete.
                try:
                    child_host = _host(loc) if is_absolute_http_url(loc) else host
                except httpx.InvalidURL:
                    child_host = host
                if child_host != host:
                    offsite.append(loc)
                else:
                    children.append(loc)
            room = max_documents - len(documents) - len(queue)
            if children and (depth >= max_depth or room < len(children)):
                limit_reached = True
            if depth < max_depth:
                queue.extend(
                    (child, depth + 1, document.receipt_id) for child in children[: max(room, 0)]
                )
    return SitemapRead(
        roots=tuple(roots),
        documents=tuple(documents),
        entries=tuple(entries),
        limit_reached=limit_reached,
        offsite_children=tuple(offsite),
        unusable_locs=unusable,
    )


def discover_sitemaps(
    fetch: Fetch,
    page_url: str,
    robots_sitemaps: tuple[str, ...],
    robots_receipt_id: str,
    *,
    limit: int,
    max_documents: int = 50,
    site_root: str | None = None,
) -> SitemapRead:
    """Find and read a site's sitemaps for a page.

    :param fetch: Fetches a URL for the run.
    :param page_url: The page's URL.
    :param robots_sitemaps: The ``Sitemap:`` lines of its origin's robots.txt.
    :param robots_receipt_id: That robots.txt's receipt.
    :param limit: The body limit, for gzip.
    :param max_documents: The most documents read in all.
    :param site_root: The ``[[site]]`` prefix covering the page, if any; its
        ``sitemap.xml`` and ``wp-sitemap.xml`` are tried before the origin's.
    :return: The first read that found a sitemap, else the last one tried,
        with every document tried along the way.
    """
    origin = robots_url_for(page_url).removesuffix("/robots.txt")
    candidates: list[list[str]] = []
    if robots_sitemaps:
        candidates.append(list(robots_sitemaps))
    bases = [f"{origin}/"]
    if site_root is not None:
        root = site_root if site_root.endswith("/") else site_root + "/"
        if root != bases[0]:
            bases.insert(0, root)
    candidates += [
        [f"{base}{name}"] for base in bases for name in ("sitemap.xml", "wp-sitemap.xml")
    ]
    documents: list[SitemapDocument] = []
    offsite: list[str] = []
    unusable = 0
    read = SitemapRead(roots=(), documents=(), entries=(), limit_reached=False)
    for roots in candidates:
        remaining = max_documents - len(documents)
        if remaining < 1:
            read = SitemapRead(roots=read.roots, documents=(), entries=(), limit_reached=True)
            break
        read = read_sitemaps(
            fetch, roots, limit=limit, max_documents=remaining, named_by=robots_receipt_id
        )
        documents.extend(read.documents)
        offsite.extend(read.offsite_children)
        unusable += read.unusable_locs
        if read.found:
            break
    return SitemapRead(
        roots=read.roots,
        documents=tuple(documents),
        entries=read.entries,
        limit_reached=read.limit_reached,
        robots_receipt_id=robots_receipt_id,
        robots_sitemaps=robots_sitemaps,
        offsite_children=tuple(offsite),
        unusable_locs=unusable,
    )
