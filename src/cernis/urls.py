"""The one URL normalization in Cernis, and the shared URL comparison (DESIGN.md section 3).

Three things use this module, so there is one normalization in the
codebase:

- **URL comparison** (:func:`compare_urls`), for checks such as
  ``peri.og.url_matches_canonical`` and ``epi.pair.canonical``.
- **Finding keys** (:func:`normalize_url`, via :func:`cernis.model.finding_key`).
- **The robots.txt matcher** (:mod:`cernis.fetch.rfc9309`), which uses
  :func:`normalize_percent_encoding` for patterns and paths.

:func:`normalize_url` applies, in order:

1. surrounding ASCII whitespace removed (HTML strips it from URL attributes);
2. Unicode NFC;
3. the scheme lowercased;
4. the host lowercased, and an internationalized host converted to its
   ASCII (IDNA, UTS 46) form;
5. a default port (80 for http, 443 for https) removed, and an empty port;
6. an empty path made ``/``;
7. dot segments (``.`` and ``..``) removed (RFC 3986 section 5.2.4);
8. percent-encoding normalized in the path (:func:`normalize_percent_encoding`);
9. one trailing slash on the path ignored, except for the root;
10. the fragment removed.

The query string is kept exactly as written, and so is user information:
Cernis does not guess which parameters are "only tracking". Only absolute
``http`` and ``https`` URLs are normalized; anything else (a relative URL, a
property name such as ``og:image``, a URL that does not parse) is returned
as NFC text and only ever compares ``IDENTICAL`` to itself.

Dot-segment removal (step 7) goes beyond DESIGN.md's list; it is there
because every HTTP client resolves dot segments before sending, so
``/a/../b`` and ``/b`` always name the same resource (SESSION-04a.md).
"""

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit

import idna

if TYPE_CHECKING:
    # cernis.model imports this module for finding keys, so Receipt is
    # imported for type checking only.
    from cernis.model import Receipt

UNRESERVED: frozenset[str] = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
"""RFC 3986 unreserved characters: their percent-encoded and plain forms are the same."""

RESERVED: frozenset[str] = frozenset(":/?#[]@!$&'()*+,;=")
"""RFC 3986 reserved characters: kept as written, plain or encoded."""

_HEX = frozenset("0123456789abcdefABCDEF")
_ASCII_WHITESPACE = "\t\n\x0c\r "
_DEFAULT_PORTS = {"http": 80, "https": 443}

REASON_ORDER: tuple[str, ...] = (
    "surrounding whitespace",
    "Unicode NFC",
    "scheme case",
    "host case",
    "internationalized host",
    "default port",
    "empty path",
    "dot segments",
    "percent-encoding",
    "trailing slash",
    "fragment",
    "redirect",
)
"""Every reason an ``EQUIVALENT`` comparison can give, in the order it lists them."""


def normalize_percent_encoding(text: str, *, literal: Mapping[str, str] | None = None) -> str:
    """Normalize percent-encoding, so equivalent spellings compare equal.

    A ``%XX`` for an unreserved character is decoded; any other ``%XX`` is
    kept with uppercase hex; a ``%`` not followed by two hex digits becomes
    ``%25``; reserved and unreserved characters are kept; anything else is
    encoded as UTF-8 with uppercase hex.

    :param text: A path, a path and query, or a robots.txt pattern.
    :param literal: Replacements for plain (unencoded) characters, applied
        before the rules above. The robots matcher uses it to turn ``*`` into
        a wildcard or ``%2A``, and ``$`` into ``%24``.
    :return: The normalized text.
    """
    replace = literal or {}
    out: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "%":
            digits = text[index + 1 : index + 3]
            if len(digits) == 2 and set(digits) <= _HEX:
                decoded = chr(int(digits, 16))
                out.append(decoded if decoded in UNRESERVED else f"%{digits.upper()}")
                index += 3
                continue
            out.append("%25")
        elif character in replace:
            out.append(replace[character])
        elif character in UNRESERVED or character in RESERVED:
            out.append(character)
        else:
            out.append("".join(f"%{octet:02X}" for octet in character.encode("utf-8")))
        index += 1
    return "".join(out)


def _remove_dot_segments(path: str) -> str:
    """Remove ``.`` and ``..`` segments (RFC 3986 section 5.2.4).

    :param path: An absolute path.
    :return: The path without dot segments.
    """
    output: list[str] = []
    for segment in path.split("/")[1:]:
        if segment == ".":
            continue
        if segment == "..":
            if output:
                output.pop()
            continue
        output.append(segment)
    result = "/" + "/".join(output)
    if path.endswith(("/.", "/..")):
        result += "" if result.endswith("/") else "/"
    return result


@dataclass(frozen=True, kw_only=True)
class _Parts:
    """A URL taken apart, before and after each normalization step.

    :param raw: The components as ``urlsplit`` returns them (after
        whitespace and NFC); it lowercases the scheme.
    :param written_scheme: The scheme exactly as written.
    :param steps: The path after each path step, in order.
    :param scheme: The normalized scheme.
    :param userinfo: User information, exactly as written, with its ``@``.
    :param host: The normalized host.
    :param port: The port, or empty for the default.
    :param path: The normalized path.
    :param query: ``?`` and the query exactly as written, or empty if none.
    :param fragment: The fragment as written, or ``None`` if there was none.
    :param applied: The normalization steps that changed something.
    """

    raw: SplitResult
    written_scheme: str
    steps: tuple[tuple[str, str], ...]
    scheme: str
    userinfo: str
    host: str
    port: str
    path: str
    query: str
    fragment: str | None
    applied: frozenset[str]

    @property
    def normalized(self) -> str:
        """The normalized URL."""
        port = f":{self.port}" if self.port else ""
        return f"{self.scheme}://{self.userinfo}{self.host}{port}{self.path}{self.query}"


def _ascii_host(host: str) -> str | None:
    """Return a host in lowercase ASCII form.

    :param host: The host as ``urlsplit`` returns it (lowercased, no brackets).
    :return: The ASCII host (IPv6 in brackets), or ``None`` if it cannot be
        converted.
    """
    if ":" in host:
        return f"[{host}]"
    if host.isascii():
        return host
    try:
        return idna.encode(host, uts46=True).decode("ascii")
    except idna.IDNAError:
        return None


def _parse(url: str) -> _Parts | None:
    """Take an absolute http(s) URL apart and normalize each component.

    :param url: The URL as written.
    :return: The parts, or ``None`` if it is not an absolute http(s) URL that
        parses.
    """
    applied: set[str] = set()
    stripped = url.strip(_ASCII_WHITESPACE)
    if stripped != url:
        applied.add("surrounding whitespace")
    text = unicodedata.normalize("NFC", stripped)
    if text != stripped:
        applied.add("Unicode NFC")
    try:
        raw = urlsplit(text)
        raw_host = raw.hostname
        port_number = raw.port
    except ValueError:
        return None
    scheme = raw.scheme
    written_scheme = text.split(":", 1)[0]
    if scheme not in _DEFAULT_PORTS or not raw_host:
        return None
    if written_scheme != scheme:
        applied.add("scheme case")
    userinfo = raw.netloc.rpartition("@")[0]
    userinfo = f"{userinfo}@" if "@" in raw.netloc else ""
    written_host = raw.netloc.rpartition("@")[2]
    written_host = (
        written_host.rsplit(":", 1)[0] if not written_host.endswith("]") else written_host
    )
    host = _ascii_host(raw_host)
    if host is None:
        return None
    if not raw_host.isascii():
        applied.add("internationalized host")
    elif written_host.strip("[]") != raw_host:
        applied.add("host case")
    port = "" if port_number in (None, _DEFAULT_PORTS[scheme]) else str(port_number)
    if raw.netloc.endswith(":") or port_number == _DEFAULT_PORTS[scheme]:
        applied.add("default port")
    steps: list[tuple[str, str]] = []
    path = raw.path
    for name, step in (
        ("empty path", lambda p: p or "/"),
        ("dot segments", _remove_dot_segments),
        ("percent-encoding", normalize_percent_encoding),
        ("trailing slash", lambda p: p[:-1] if p != "/" and p.endswith("/") else p),
    ):
        after = step(path)
        if after != path:
            applied.add(name)
        steps.append((name, after))
        path = after
    without_fragment, hash_mark, fragment = text.partition("#")
    if hash_mark:
        applied.add("fragment")
    query = f"?{raw.query}" if "?" in without_fragment else ""
    return _Parts(
        raw=raw,
        written_scheme=written_scheme,
        steps=tuple(steps),
        scheme=scheme,
        userinfo=userinfo,
        host=host,
        port=port,
        path=path,
        query=query,
        fragment=fragment if hash_mark else None,
        applied=frozenset(applied),
    )


def is_absolute_http_url(url: str) -> bool:
    """Tell whether a string is an absolute http or https URL that parses.

    :param url: The string.
    :return: Whether :func:`normalize_url` would normalize it.
    """
    return _parse(url) is not None


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison and for finding keys.

    :param url: The URL as written.
    :return: The normalized URL (the module docstring lists the steps), or,
        for anything that is not an absolute http(s) URL that parses, the
        string in Unicode NFC and otherwise unchanged.
    """
    parts = _parse(url)
    return parts.normalized if parts is not None else unicodedata.normalize("NFC", url)


class UrlMatch(StrEnum):
    """The three outcomes of comparing two URLs."""

    IDENTICAL = "IDENTICAL"
    """The strings match exactly."""
    EQUIVALENT = "EQUIVALENT"
    """They match after normalization, or one redirects to the other."""
    DIFFERENT = "DIFFERENT"
    """Anything else."""


@dataclass(frozen=True, kw_only=True)
class UrlComparison:
    """The outcome of comparing two URLs, and why.

    :param outcome: IDENTICAL, EQUIVALENT, or DIFFERENT.
    :param reasons: For EQUIVALENT, the normalizations that made the two
        match (in :data:`REASON_ORDER`), or ``("redirect",)``; empty otherwise.
    :param receipt_id: For an EQUIVALENT by redirect, the receipt that shows
        it; ``None`` otherwise.
    """

    outcome: UrlMatch
    reasons: tuple[str, ...] = ()
    receipt_id: str | None = None


def _reasons(a: _Parts, b: _Parts) -> tuple[str, ...]:
    """Name the normalizations that made two different strings match.

    A step counts only if it changed something on one side while the two
    still differed at that point, so a normalization both sides share is
    not a reason.

    :param a: The first URL's parts.
    :param b: The second URL's parts.
    :return: The reasons, in :data:`REASON_ORDER`.
    """
    found: set[str] = set()
    shared = a.applied & b.applied
    for name in ("surrounding whitespace", "Unicode NFC"):
        if name in a.applied ^ b.applied:
            found.add(name)
    if a.written_scheme != b.written_scheme:
        found.add("scheme case")
    if a.raw.netloc != b.raw.netloc:
        for name in ("host case", "internationalized host", "default port"):
            if name in a.applied | b.applied and not (
                name in shared and a.raw.netloc.lower() == b.raw.netloc.lower()
            ):
                found.add(name)
    before_a, before_b = a.raw.path, b.raw.path
    for (name, after_a), (_, after_b) in zip(a.steps, b.steps, strict=True):
        if before_a != before_b and (after_a != before_a or after_b != before_b):
            found.add(name)
        before_a, before_b = after_a, after_b
    if a.fragment != b.fragment:
        found.add("fragment")
    return tuple(name for name in REASON_ORDER if name in found)


def _redirect_between(a: str, b: str, redirects: Iterable["Receipt"]) -> str | None:
    """Find a receipt showing that one URL redirected, directly or not, to the other.

    :param a: The first URL, normalized.
    :param b: The second URL, normalized.
    :param redirects: Receipts to search.
    :return: The id of the first receipt whose hops pass through one URL and
        later reach the other, or ``None``.
    """
    for receipt in redirects:
        if not receipt.redirect_chain:
            continue
        hops = [*receipt.redirect_chain]
        if receipt.final_url is not None:
            hops.append(receipt.final_url)
        normalized = [normalize_url(hop) for hop in hops]
        for earlier, later in ((a, b), (b, a)):
            if earlier in normalized and later in normalized[normalized.index(earlier) + 1 :]:
                return receipt.id
    return None


def compare_urls(a: str, b: str, *, redirects: Iterable["Receipt"] = ()) -> UrlComparison:
    """Compare two URLs: IDENTICAL, EQUIVALENT (with the reason), or DIFFERENT.

    :param a: One URL, as written.
    :param b: The other URL, as written.
    :param redirects: Receipts whose redirect chains may show that one URL
        redirects to the other.
    :return: The comparison. It is symmetric: swapping ``a`` and ``b`` gives
        the same result.
    """
    if a == b:
        return UrlComparison(outcome=UrlMatch.IDENTICAL)
    parts_a, parts_b = _parse(a), _parse(b)
    if parts_a is None or parts_b is None:
        return UrlComparison(outcome=UrlMatch.DIFFERENT)
    if parts_a.normalized == parts_b.normalized:
        return UrlComparison(outcome=UrlMatch.EQUIVALENT, reasons=_reasons(parts_a, parts_b))
    receipt_id = _redirect_between(parts_a.normalized, parts_b.normalized, redirects)
    if receipt_id is not None:
        return UrlComparison(
            outcome=UrlMatch.EQUIVALENT, reasons=("redirect",), receipt_id=receipt_id
        )
    return UrlComparison(outcome=UrlMatch.DIFFERENT)
