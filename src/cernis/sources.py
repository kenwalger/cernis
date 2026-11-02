"""URL sources: a sitemap, or a DEV user's published articles (DESIGN.md section 7).

Both list URLs for a run through the run's own fetches, so every request
(robots.txt included) goes through the normal fetcher and is a receipt in
the run, and a URL listed and then audited is fetched once.

- :func:`from_sitemap` reads a sitemap (following indexes, gzip included,
  :mod:`cernis.sitemaps`), keeps the pages on the sitemap's own host
  (sitemaps.org: a sitemap lists its own site's pages; the others are
  counted in a note) and under ``include_prefix`` if one is given, and stops
  at ``limit``.
- :func:`from_dev_user` reads DEV's public articles API
  (``https://dev.to/api/articles?username=...``), which needs no key and
  lists only published articles, page by page, until a short page, the
  ``limit``, or :data:`MAX_DEV_PAGES`. An article whose ``canonical_url``
  names a page off dev.to is cross-posted: that page is the original and the
  DEV article the copy. Any other article is listed as not cross-posted, a
  fact recorded in the source's notes.

A request that fails stops the listing, and a note says where, so a short
listing is never mistaken for a complete one.
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from cernis.audit import RunFetches
from cernis.checks.epitext import unanswered
from cernis.model import Actor, RunSource, SourceNote
from cernis.parse.extractors import under_prefix
from cernis.sitemaps import read_sitemaps
from cernis.urls import is_absolute_http_url, normalize_url

DEV_API = "https://dev.to/api/articles"
"""DEV's public articles endpoint."""

DEV_HOSTS: frozenset[str] = frozenset({"dev.to", "www.dev.to"})
"""Hosts that are DEV itself, so a canonical URL there is not an original elsewhere."""

MAX_DEV_PAGES = 50
"""The most API pages one listing reads."""

DEV_PAGE_SIZE = 100
"""The most articles asked for per API page."""

_USERNAME = re.compile(r"[A-Za-z0-9_]{1,64}")


class SourceError(ValueError):
    """Raised when a source cannot be listed at all (a bad username or URL)."""


@dataclass(frozen=True, kw_only=True)
class DevArticle:
    """One published DEV article.

    :param url: The article's URL on dev.to.
    :param canonical_url: Its ``canonical_url``, or ``None`` if it has none.
    :param title: Its title.
    """

    url: str
    canonical_url: str | None
    title: str

    @property
    def original(self) -> str | None:
        """The original this article copies: its canonical URL, when that is off dev.to."""
        if self.canonical_url is None:
            return None
        host = (httpx.URL(self.canonical_url).host or "").lower()
        return None if host in DEV_HOSTS else self.canonical_url


@dataclass(frozen=True, kw_only=True)
class Listing:
    """What a source listed.

    :param source: The record for the run.
    :param articles: For a DEV user, every published article read, in order.
    """

    source: RunSource
    articles: tuple[DevArticle, ...] = ()


def _new_receipts(fetches: RunFetches, before: set[str]) -> tuple[str, ...]:
    """Name the receipts a listing added to the run.

    :param fetches: The run's fetches.
    :param before: The receipt ids from before the listing.
    :return: The new ids, in order.
    """
    return tuple(rid for rid in fetches.receipts if rid not in before)


def from_sitemap(
    fetches: RunFetches,
    sitemap_url: str,
    *,
    include_prefix: str | None = None,
    limit: int | None = None,
    max_documents: int = 50,
) -> Listing:
    """List the pages a sitemap names.

    :param fetches: The run's fetches.
    :param sitemap_url: The sitemap (or sitemap index) URL.
    :param include_prefix: Keep only pages at or under this URL prefix (by
        whole path segments, after normalization), or ``None`` for all.
    :param limit: The most pages listed, or ``None`` for all.
    :param max_documents: The most sitemap documents read.
    :return: The listing.
    :raises SourceError: If the sitemap URL or the prefix is not an absolute
        http(s) URL.
    """
    for value in (sitemap_url, include_prefix):
        if value is not None and not is_absolute_http_url(value):
            raise SourceError(f"not an absolute http or https URL: {value!r}")
    before = set(fetches.receipts)
    read = read_sitemaps(
        fetches.fetch,
        [sitemap_url],
        limit=fetches.fetcher.config.max_body_bytes,
        max_documents=max_documents,
    )
    prefix = normalize_url(include_prefix) if include_prefix is not None else None
    host = (httpx.URL(sitemap_url).host or "").lower()
    listed: list[str] = []
    seen: set[str] = set()
    offsite = 0
    for entry in read.entries:
        key = entry.key
        if key in seen:
            continue
        if (httpx.URL(entry.loc).host or "").lower() != host:
            offsite += 1
            continue
        if prefix is not None and not under_prefix(key, prefix):
            continue
        if limit is not None and len(listed) >= limit:
            break
        seen.add(key)
        listed.append(entry.loc)
    notes = [
        SourceNote(url=doc.url, note=f"not read: {doc.unreadable.why}")
        for doc in read.documents
        if doc.unreadable is not None
    ]
    notes += [
        SourceNote(url=doc.url, note=f"no sitemap here: it answered {doc.status}")
        for doc in read.documents
        if doc.missing
    ]
    if offsite:
        notes.append(
            SourceNote(
                url=sitemap_url,
                note=f"{offsite} listed pages on other hosts than {host} were left out",
            )
        )
    if read.offsite_children:
        notes.append(
            SourceNote(
                url=sitemap_url,
                note=(
                    f"{len(read.offsite_children)} child sitemaps on other hosts were not followed"
                ),
            )
        )
    if read.unusable_locs:
        notes.append(
            SourceNote(
                url=sitemap_url,
                note=f"{read.unusable_locs} <loc> values were not fetchable URLs",
            )
        )
    if read.limit_reached:
        notes.append(
            SourceNote(
                url=sitemap_url,
                note=(
                    f"Cernis stopped at a limit after {len(read.documents)} sitemap documents "
                    "(documents, index depth, or entries), so the listing may be incomplete"
                ),
            )
        )
    return Listing(
        source=RunSource(
            kind="sitemap",
            query=sitemap_url,
            receipt_ids=_new_receipts(fetches, before),
            listed=tuple(listed),
            notes=tuple(notes),
        )
    )


def _article(item: object) -> DevArticle | None:
    """Read one article from the API's JSON, if it is a published article.

    :param item: One element of the API's array.
    :return: The article, or ``None`` if it is not a published article with
        a dev.to URL.
    """
    if not isinstance(item, dict):
        return None
    if item.get("type_of", "article") != "article" or not item.get("published_at"):
        return None
    url = item.get("url")
    if not isinstance(url, str) or not is_absolute_http_url(url):
        return None
    if (httpx.URL(url).host or "").lower() not in DEV_HOSTS:
        return None
    canonical = item.get("canonical_url")
    if not isinstance(canonical, str) or not is_absolute_http_url(canonical):
        canonical = None
    title = item.get("title")
    return DevArticle(
        url=url, canonical_url=canonical, title=title if isinstance(title, str) else ""
    )


def from_dev_user(fetches: RunFetches, username: str, *, limit: int | None = None) -> Listing:
    """List a DEV user's published articles from DEV's public API.

    :param fetches: The run's fetches.
    :param username: The DEV username.
    :param limit: The most articles listed, or ``None`` for all.
    :return: The listing; ``listed`` holds the article URLs, and the notes
        say which articles are not cross-posted and where reading stopped.
    :raises SourceError: If the username is not a DEV username (letters,
        digits, and underscores).
    """
    if not _USERNAME.fullmatch(username):
        raise SourceError(f"not a DEV username: {username!r}")
    before = set(fetches.receipts)
    page_size = min(DEV_PAGE_SIZE, limit) if limit else DEV_PAGE_SIZE
    articles: list[DevArticle] = []
    notes: list[SourceNote] = []
    seen: set[str] = set()
    for number in range(1, MAX_DEV_PAGES + 1):
        url = f"{DEV_API}?username={quote(username)}&page={number}&per_page={page_size}"
        result = fetches.fetch(url)
        reason = unanswered(result, Actor.UNKNOWN)
        final = result.final
        if reason is not None or final is None or final.status_code != 200 or not result.body:
            why = (
                reason.why
                if reason is not None
                else (f"it answered {final.status_code}" if final is not None else "no response")
            )
            notes.append(SourceNote(url=url, note=f"the listing stops here: {why}"))
            break
        try:
            items = json.loads(result.body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            notes.append(SourceNote(url=url, note="the listing stops here: not valid JSON"))
            break
        if not isinstance(items, list):
            notes.append(SourceNote(url=url, note="the listing stops here: not a JSON array"))
            break
        for item in items:
            article = _article(item)
            if article is None or article.url in seen:
                continue
            if limit is not None and len(articles) >= limit:
                break
            seen.add(article.url)
            articles.append(article)
        if len(items) < page_size or (limit is not None and len(articles) >= limit):
            break
    else:
        notes.append(
            SourceNote(
                url=DEV_API,
                note=f"Cernis stopped after {MAX_DEV_PAGES} pages, its limit",
            )
        )
    for article in articles:
        if article.original is None:
            why = (
                "it has no canonical URL"
                if article.canonical_url is None
                else f"its canonical URL is on DEV ({article.canonical_url})"
            )
            notes.append(SourceNote(url=article.url, note=f"not cross-posted: {why}"))
    return Listing(
        source=RunSource(
            kind="dev-user",
            query=username,
            receipt_ids=_new_receipts(fetches, before),
            listed=tuple(article.url for article in articles),
            notes=tuple(notes),
        ),
        articles=tuple(articles),
    )
