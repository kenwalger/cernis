"""Snapshots: three hashes that let history tell who changed a page (DESIGN.md sections 3, 5).

A snapshot splits a page into three parts and hashes each after
normalization, so that a change in one part is not mistaken for a change in
another, and a change in nothing is not mistaken for a change at all.

**content_sha256**: the article body's visible text (:func:`visible_text`):
script, style, noscript, and template contents left out, every run of
whitespace collapsed to one space, Unicode NFC. ``None`` if the extractor
found no body. Text only: markup, attributes, and link targets inside the
body are not part of it.

**head_sha256**: the page's metadata, as a sorted list, so element order and
attribute order do not matter:

- ``lang`` of ``<html>``, and each ``<title>`` in ``<head>`` (normalized text);
- each ``rel="canonical"`` link's ``href``;
- each ``meta`` with ``name``, ``property``, ``http-equiv``, or ``charset``:
  the attribute, the key lowercased, and the content normalized;
- each JSON-LD block, re-serialized with sorted keys if it parses, or as its
  normalized raw text if it does not.

Canonical, ``meta``, and JSON-LD elements count wherever they are in the
document, ``<body>`` included, so a metadata change is never lost to the
frame, whose scripts are not hashed.

**frame_sha256**: the rest of the document, ``<head>`` included, minus the
metadata above, with the article body replaced by a placeholder (so moving
it is a frame change, editing it is not). It is a list of open tags (name
and sorted attributes), close tags, and text, after these steps:

- ``<html lang>`` left out (it is metadata);
- comments dropped; the contents of ``script``, ``style``, ``noscript``, and
  ``template`` dropped (the elements and their attributes kept);
- text and attribute values normalized like text;
- **volatile tokens** replaced, because they change on every request:

  - ``nonce`` and ``integrity`` attributes, and any attribute whose name
    contains ``csrf``, are dropped;
  - the ``value`` of a hidden ``input`` whose name contains ``csrf``,
    ``token``, or ``nonce`` (Rails' ``authenticity_token``, WordPress's
    ``_wpnonce``), and the ``content`` of a ``meta`` whose name contains
    ``csrf``, become ``~``;
  - in URL attributes (``href``, ``src``, ``srcset``, ``action``,
    ``poster``, ``data-src``, ``data-srcset``), a run of 8 or more hex
    digits between ``-``, ``.``, or ``_`` and a delimiter (an asset
    fingerprint, as in ``base-4f2a...e1.js``) becomes ``~``, and so does
    the value of a cache-busting query parameter (``v``, ``ver``,
    ``version``, ``hash``, ``h``, ``cb``, ``t``, ``ts``, ``_``, ``rev``,
    ``build``).

The CSRF ``meta`` is metadata, so in ``head_sha256`` its content is ``~``
too.

These rules are part of every extractor's recorded version: a snapshot's
``extractor_version`` is ``<extractor version>+n<NORMALIZATION_VERSION>``,
so changing a rule here shows in history as a ``CHECKER`` change.
"""

import hashlib
import json
import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

from cernis.model import ErrorKind, Receipt, Snapshot
from cernis.parse.extractors import SiteType, choose_extractor, find_body
from cernis.parse.html import (
    NON_TEXT_ELEMENTS,
    is_json_ld,
    normalize_text,
    parse_tree,
    rel_tokens,
    visible_text,
)

NORMALIZATION_VERSION = "1"
"""The version of the normalization rules in this module."""

_URL_ATTRIBUTES = frozenset(
    {"href", "src", "srcset", "action", "poster", "data-src", "data-srcset"}
)
_DROPPED_ATTRIBUTES = frozenset({"nonce", "integrity"})
_FINGERPRINT = re.compile(r"(?<=[-._])[0-9A-Fa-f]{8,}(?=[-._/?#,\s]|$)")
_CACHE_BUSTER = re.compile(
    r"([?&](?:v|ver|version|hash|h|cb|t|ts|_|rev|build)=)[^&#,\s]*", re.IGNORECASE
)
_VOLATILE_INPUT = re.compile(r"csrf|token|nonce", re.IGNORECASE)
_TOKEN = "~"


class SnapshotError(ValueError):
    """Raised when a snapshot is asked for a receipt that has no whole body."""


def _sha256(value: object) -> str:
    """Hash a JSON-serializable value deterministically.

    :param value: The value.
    :return: The SHA-256 of its compact JSON (UTF-8, no ASCII escaping), hex.
    """
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def defingerprint(url: str) -> str:
    """Replace asset fingerprints and cache-busting values in a URL attribute.

    :param url: The attribute value (a URL, or a ``srcset`` list).
    :return: The value with each volatile part replaced by ``~``.
    """
    return _CACHE_BUSTER.sub(rf"\1{_TOKEN}", _FINGERPRINT.sub(_TOKEN, url))


def _is_metadata(node: LexborNode) -> bool:
    """Tell whether an element belongs to the head hash rather than the frame.

    :param node: An element.
    :return: Whether it is a canonical link, a ``meta``, a JSON-LD script, or
        a ``title`` in ``<head>``.
    """
    tag = node.tag
    if tag == "link":
        return "canonical" in rel_tokens(node)
    if tag == "meta":
        return True
    if tag == "script":
        return is_json_ld(node)
    if tag == "title":
        parent = node.parent
        return parent is not None and parent.tag == "head"
    return False


def _head_entries(tree: LexborHTMLParser) -> list[list[str]]:
    """List the page's metadata for ``head_sha256``.

    :param tree: The parsed document.
    :return: The entries, sorted.
    """
    entries: list[list[str]] = []
    root = tree.css_first("html")
    lang = root.attributes.get("lang") if root is not None else None
    entries.append(["lang", "" if lang is None else normalize_text(lang), str(lang is None)])
    for node in tree.css("title, link, meta, script"):
        if not _is_metadata(node):
            continue
        attributes = node.attributes
        if node.tag == "title":
            entries.append(["title", normalize_text(node.text(deep=True))])
        elif node.tag == "link":
            entries.append(["canonical", normalize_text(attributes.get("href") or "")])
        elif node.tag == "script":
            raw = node.text(deep=True)
            try:
                value = json.loads(raw)
            except (ValueError, RecursionError):
                entries.append(["json-ld", "unparsed", normalize_text(raw)])
            else:
                serialized = json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
                entries.append(["json-ld", "parsed", serialized])
        else:
            for attribute in ("name", "property", "http-equiv", "charset"):
                if attribute in attributes:
                    key = normalize_text(attributes.get(attribute) or "").lower()
                    content = normalize_text(attributes.get("content") or "")
                    if attribute == "charset":
                        key, content = "", key
                    elif "csrf" in key:
                        content = _TOKEN
                    entries.append(["meta", attribute, key, content])
                    break
    return sorted(entries)


def _attributes(node: LexborNode) -> list[list[str]]:
    """Normalize an element's attributes for ``frame_sha256``.

    :param node: An element.
    :return: ``[name, value]`` pairs, sorted, with volatile tokens replaced.
    """
    attributes = node.attributes
    hidden_token = (
        node.tag == "input"
        and (attributes.get("type") or "").strip().lower() == "hidden"
        and bool(_VOLATILE_INPUT.search(attributes.get("name") or ""))
    )
    pairs: list[list[str]] = []
    for name, value in attributes.items():
        name = name.lower()
        if name in _DROPPED_ATTRIBUTES or "csrf" in name:
            continue
        if node.tag == "html" and name == "lang":
            continue  # metadata: counted in head_sha256
        text = value or ""
        if hidden_token and name == "value":
            text = _TOKEN
        elif name in _URL_ATTRIBUTES:
            text = defingerprint(text)
        pairs.append([name, normalize_text(text)])
    return sorted(pairs)


def _frame_tokens(tree: LexborHTMLParser, body: LexborNode | None) -> list[list[object]]:
    """Serialize the frame: the document minus metadata, with the body as a placeholder.

    :param tree: The parsed document.
    :param body: The article body element, or ``None``.
    :return: The tokens, in document order.
    """
    tokens: list[list[object]] = []
    root = tree.root
    if root is None:
        return tokens
    skip_body = body.mem_id if body is not None else None
    stack: list[tuple[LexborNode, bool]] = [(root, False)]
    while stack:
        node, closing = stack.pop()
        tag = node.tag
        if closing:
            tokens.append(["close", tag])
            continue
        if tag == "-text":
            text = normalize_text(node.text_content or "")
            if text:
                tokens.append(["text", text])
            continue
        if tag is None or tag.startswith("-") or _is_metadata(node):
            continue
        if node.mem_id == skip_body:
            tokens.append(["article-body"])
            continue
        tokens.append(["open", tag, _attributes(node)])
        stack.append((node, True))
        if tag not in NON_TEXT_ELEMENTS:
            children = list(node.iter(include_text=True))
            stack.extend((child, False) for child in reversed(children))
    return tokens


def build_snapshot(receipt: Receipt, body: bytes, *, site: SiteType | None = None) -> Snapshot:
    """Build the snapshot of a receipt's whole body.

    :param receipt: A receipt with a whole body: ``error_kind`` ``NONE`` and a
        ``body_sha256`` (a ``200``, or a ``304`` with its cached body).
    :param body: The body, which must hash to ``receipt.body_sha256``.
    :param site: The site type the author declared, if any.
    :return: The snapshot.
    :raises SnapshotError: If the receipt has no whole body (it failed, was
        cut off at the size limit, or had no body) or ``body`` is not that
        body. ADR-003: a snapshot is never made from part of a page.
    """
    if receipt.error_kind is not ErrorKind.NONE or receipt.body_sha256 is None:
        raise SnapshotError(f"receipt {receipt.id} has no whole body to snapshot")
    if hashlib.sha256(body).hexdigest() != receipt.body_sha256:
        raise SnapshotError(f"the body given is not the body of receipt {receipt.id}")
    tree, _ = parse_tree(body, receipt.header("content-type"))
    extractor = choose_extractor(receipt.final_url or receipt.requested_url, site)
    match = find_body(tree, extractor)
    content = None if match.node is None else _sha256(visible_text(match.node))
    return Snapshot(
        receipt_id=receipt.id,
        extractor_id=extractor.id,
        extractor_version=f"{extractor.version}+n{NORMALIZATION_VERSION}",
        content_sha256=content,
        head_sha256=_sha256(_head_entries(tree)),
        frame_sha256=_sha256(_frame_tokens(tree, match.node)),
    )
