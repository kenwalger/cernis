"""Decoding a receipt's body and extracting what the checks read (DESIGN.md section 4).

:func:`parse_page` never raises on malformed HTML. The HTML parser (selectolax's
Lexbor backend, which follows the WHATWG parsing algorithm) repairs any
markup the way a browser would, and everything Cernis could not read (bytes
that do not decode, a canonical with no ``href``, a JSON-LD block that is
not JSON) is recorded in :attr:`ParsedPage.problems` and on the element it
concerns, never thrown away.

Values are recorded exactly as the parser saw them (entities decoded, but
whitespace and case kept), because a finding's evidence must show what was
there. Normalization is for hashing (:mod:`cernis.parse.snapshot`) and URL
comparison (:mod:`cernis.urls`), not for evidence.
"""

import codecs
import json
import re
import unicodedata
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

from cernis.model import Receipt

_ASCII_WHITESPACE = "\t\n\x0c\r "
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""", re.IGNORECASE)
_CONTENT_TYPE_CHARSET = re.compile(r"""charset\s*=\s*["']?([^"';\s]+)""", re.IGNORECASE)
# WHATWG Encoding: these labels mean windows-1252 in a browser.
_WINDOWS_1252_LABELS = frozenset(
    {"iso-8859-1", "iso8859-1", "latin1", "latin-1", "us-ascii", "ascii"}
)


def normalize_text(text: str) -> str:
    """Put text in Unicode NFC and collapse every run of whitespace to one space.

    :param text: The text.
    :return: The normalized text, with no leading or trailing whitespace.
    """
    return " ".join(unicodedata.normalize("NFC", text).split())


def rel_tokens(node: LexborNode) -> tuple[str, ...]:
    """Return a link's ``rel`` keywords, lowercased.

    :param node: A ``link`` or ``a`` element.
    :return: The keywords, split on ASCII whitespace, in order.
    """
    return tuple(token.lower() for token in (node.attributes.get("rel") or "").split())


def is_json_ld(node: LexborNode) -> bool:
    """Tell whether a ``script`` element holds JSON-LD.

    :param node: A ``script`` element.
    :return: Whether its ``type`` is ``application/ld+json``, ignoring case and
        surrounding whitespace.
    """
    kind = (node.attributes.get("type") or "").strip(_ASCII_WHITESPACE).lower()
    return kind == "application/ld+json"


@dataclass(frozen=True, kw_only=True)
class Decoded:
    """A body decoded to text.

    :param text: The text.
    :param encoding: The codec used, as Python names it.
    :param source: Where the encoding came from: ``BOM``, ``content-type``,
        ``meta``, or ``default`` (UTF-8).
    :param problems: What went wrong, if anything.
    """

    text: str
    encoding: str
    source: str
    problems: tuple[str, ...]


def _codec(label: str) -> str | None:
    """Turn a charset label into a Python codec name.

    :param label: The label from a header or a ``meta`` element.
    :return: The codec name, or ``None`` if Python has no such codec.
    """
    label = label.strip().lower()
    if label in _WINDOWS_1252_LABELS:
        return "cp1252"
    try:
        return codecs.lookup(label).name
    except LookupError:
        return None


def decode_body(body: bytes, content_type: str | None) -> Decoded:
    """Decode a body the way a browser would choose its encoding, never failing.

    The order is a byte-order mark, then the ``Content-Type`` charset, then a
    ``<meta charset>`` (or ``http-equiv``) in the first 1024 bytes, then UTF-8.
    Bytes that do not decode become U+FFFD, and that is recorded.

    :param body: The body.
    :param content_type: The response's ``Content-Type``, if recorded.
    :return: The text, the encoding, where it came from, and any problems.
    """
    problems: list[str] = []
    encoding, source = "utf-8", "default"
    for bom, name in (
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if body.startswith(bom):
            body, encoding, source = body[len(bom) :], name, "BOM"
            break
    else:
        candidates: list[tuple[str, str]] = []
        if content_type and (match := _CONTENT_TYPE_CHARSET.search(content_type)):
            candidates.append((match.group(1), "content-type"))
        if match_meta := _CHARSET.search(body[:1024]):
            candidates.append((match_meta.group(1).decode("ascii", errors="replace"), "meta"))
        for label, where in candidates:
            codec = _codec(label)
            if codec is not None:
                encoding, source = codec, where
                break
            problems.append(f"unknown charset {label!r} in {where}; tried the next source")
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError:
        text = body.decode(encoding, errors="replace")
        problems.append(f"the body is not valid {encoding}; undecodable bytes became U+FFFD")
    return Decoded(text=text, encoding=encoding, source=source, problems=tuple(problems))


@dataclass(frozen=True, kw_only=True)
class Canonical:
    """One ``<link rel="canonical">``.

    :param href: The ``href`` exactly as written, or ``None`` if it has none.
    :param in_head: Whether the element is in ``<head>`` after parsing.
    """

    href: str | None
    in_head: bool


@dataclass(frozen=True, kw_only=True)
class MetaTag:
    """One ``<meta>`` element with a ``name`` or ``property``.

    :param attribute: Which attribute names it: ``name`` or ``property``.
    :param key: That attribute's value, exactly as written.
    :param content: The ``content`` attribute, or ``None`` if it has none.
        An empty string is a value.
    :param in_head: Whether the element is in ``<head>`` after parsing.
    """

    attribute: str
    key: str
    content: str | None
    in_head: bool


@dataclass(frozen=True, kw_only=True)
class JsonLdBlock:
    """One ``<script type="application/ld+json">`` block.

    :param index: Its position among the page's JSON-LD blocks, from 0.
    :param raw: The script's text, exactly as written.
    :param parsed: Whether ``raw`` parsed as JSON.
    :param value: The parsed value, or ``None`` if it did not parse.
    :param error: Why it did not parse, or ``None``.
    :param types: Every ``@type`` found at the top level, in a top-level
        array, or in an ``@graph``, in order, without repeats.
    """

    index: int
    raw: str
    parsed: bool
    value: object
    error: str | None
    types: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Link:
    """One ``<a href>`` element.

    :param href: The ``href`` exactly as written.
    :param text: The link text, normalized (:func:`normalize_text`).
    """

    href: str
    text: str


@dataclass(frozen=True, kw_only=True)
class ParsedPage:
    """What Cernis read from one receipt's body.

    :param receipt_id: The receipt the body came from.
    :param encoding: The codec the body was decoded with.
    :param encoding_source: Where the encoding came from.
    :param titles: The text of every ``<title>`` in ``<head>``, in order, as
        written.
    :param lang: The ``<html lang>`` value as written, or ``None`` if absent.
    :param canonicals: Every ``rel="canonical"`` link, in order.
    :param meta: Every ``meta`` with a ``name`` or ``property``, in order.
    :param json_ld: Every JSON-LD block, in order.
    :param links: Every ``<a href>`` in ``<body>``, in order.
    :param problems: Everything Cernis could not read, in plain English.
    """

    receipt_id: str
    encoding: str
    encoding_source: str
    titles: tuple[str, ...]
    lang: str | None
    canonicals: tuple[Canonical, ...]
    meta: tuple[MetaTag, ...]
    json_ld: tuple[JsonLdBlock, ...]
    links: tuple[Link, ...]
    problems: tuple[str, ...]

    @property
    def descriptions(self) -> tuple[str | None, ...]:
        """The ``content`` of every ``<meta name="description">``, in order."""
        return tuple(
            tag.content
            for tag in self.meta
            if tag.attribute == "name" and tag.key.strip().lower() == "description"
        )

    def og(self, prop: str) -> tuple[MetaTag, ...]:
        """Every ``meta`` naming an Open Graph property, in either attribute.

        :param prop: The property, such as ``og:image``; matched ignoring case.
        :return: The matching tags, in order. A tag's ``attribute`` says
            whether it used ``property`` (the standard) or ``name``.
        """
        return tuple(tag for tag in self.meta if tag.key.strip().lower() == prop.lower())


def _types(value: object) -> tuple[str, ...]:
    """Collect ``@type`` values from a JSON-LD document.

    :param value: The parsed JSON.
    :return: The types, in order, without repeats.
    """
    found: list[str] = []
    items: list[object] = list(value) if isinstance(value, list) else [value]
    for item in list(items):
        if isinstance(item, dict) and isinstance(item.get("@graph"), list):
            items.extend(item["@graph"])
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("@type")
        for name in kind if isinstance(kind, list) else [kind]:
            if isinstance(name, str) and name not in found:
                found.append(name)
    return tuple(found)


def _json_ld(index: int, raw: str) -> JsonLdBlock:
    """Parse one JSON-LD block, recording rather than raising.

    :param index: The block's position.
    :param raw: The script's text.
    :return: The block.
    """
    if not raw.strip():
        return JsonLdBlock(
            index=index, raw=raw, parsed=False, value=None, error="the block is empty", types=()
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        error = f"not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
    except RecursionError:
        error = "not valid JSON: nested too deeply to read"
    else:
        return JsonLdBlock(
            index=index, raw=raw, parsed=True, value=value, error=None, types=_types(value)
        )
    return JsonLdBlock(index=index, raw=raw, parsed=False, value=None, error=error, types=())


def is_in_head(node: LexborNode) -> bool:
    """Tell whether an element is inside ``<head>``.

    :param node: The element.
    :return: Whether an ancestor is ``head``.
    """
    parent = node.parent
    while parent is not None:
        if parent.tag == "head":
            return True
        parent = parent.parent
    return False


def parse_tree(body: bytes, content_type: str | None) -> tuple[LexborHTMLParser, Decoded]:
    """Decode a body and parse it into a document tree.

    :param body: The body.
    :param content_type: The response's ``Content-Type``, if recorded.
    :return: The tree and the decoding.
    """
    decoded = decode_body(body, content_type)
    return LexborHTMLParser(decoded.text), decoded


def parse_page(receipt: Receipt, body: bytes) -> ParsedPage:
    """Extract what the checks read from a receipt's body. Never raises on bad HTML.

    :param receipt: The receipt the body belongs to.
    :param body: The body, as the fetcher returned it.
    :return: What was found, and what could not be read.
    """
    tree, decoded = parse_tree(body, receipt.header("content-type"))
    problems = list(decoded.problems)
    if receipt.body_truncated_at is not None:
        problems.append(
            f"the body was cut off at {receipt.body_truncated_at} bytes; only that much was read"
        )
    root = tree.css_first("html")
    lang = root.attributes.get("lang") if root is not None else None
    canonicals: list[Canonical] = []
    for node in tree.css("link"):
        if "canonical" not in rel_tokens(node):
            continue
        href = node.attributes.get("href")
        in_head = is_in_head(node)
        canonicals.append(Canonical(href=href, in_head=in_head))
        if href is None:
            problems.append("a canonical link has no href")
        if not in_head:
            problems.append("a canonical link is outside <head>")
    meta: list[MetaTag] = []
    for node in tree.css("meta"):
        for attribute in ("property", "name"):
            key = node.attributes.get(attribute)
            if key is not None:
                meta.append(
                    MetaTag(
                        attribute=attribute,
                        key=key,
                        content=node.attributes.get("content"),
                        in_head=is_in_head(node),
                    )
                )
                break
    blocks = [node for node in tree.css("script") if is_json_ld(node)]
    json_ld = tuple(_json_ld(index, node.text(deep=True)) for index, node in enumerate(blocks))
    problems.extend(
        f"JSON-LD block {block.index}: {block.error}" for block in json_ld if block.error
    )
    # Only <head> titles: an SVG in the body may carry its own <title>.
    head_titles = tree.head.css("title") if tree.head is not None else []
    body_node = tree.body
    links = links_in(body_node) if body_node is not None else ()
    return ParsedPage(
        receipt_id=receipt.id,
        encoding=decoded.encoding,
        encoding_source=decoded.source,
        titles=tuple(node.text(deep=True) for node in head_titles),
        lang=lang,
        canonicals=tuple(canonicals),
        meta=tuple(meta),
        json_ld=json_ld,
        links=links,
        problems=tuple(problems),
    )


NON_TEXT_ELEMENTS: frozenset[str] = frozenset({"script", "style", "noscript", "template"})
"""Elements whose contents are not text a reader sees."""


def visible_text(node: LexborNode) -> str:
    """Return the text a reader sees in an element, normalized.

    Text inside ``script``, ``style``, ``noscript``, and ``template`` is left
    out, and comments are ignored. Text nodes are joined with a space, so
    words in neighboring blocks never run together, then normalized
    (:func:`normalize_text`). The walk is iterative, so a deeply nested
    malformed page cannot exhaust the stack.

    :param node: The element.
    :return: The text.
    """
    parts: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        tag = current.tag
        if tag == "-text":
            parts.append(current.text_content or "")
        elif tag is not None and not tag.startswith("-") and tag not in NON_TEXT_ELEMENTS:
            stack.extend(reversed(list(current.iter(include_text=True))))
    return normalize_text(" ".join(parts))


def links_in(node: LexborNode) -> tuple[Link, ...]:
    """Collect the ``<a href>`` links inside an element.

    :param node: The element.
    :return: The links, in document order.
    """
    return tuple(
        Link(href=link.attributes.get("href") or "", text=normalize_text(link.text(deep=True)))
        for link in node.css("a[href]")
    )
