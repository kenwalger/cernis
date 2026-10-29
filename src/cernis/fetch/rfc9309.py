"""Cernis's own RFC 9309 robots.txt matcher (DESIGN.md section 6).

It replaces :mod:`urllib.robotparser`, whose matching changed in Python
3.14 (first match before, longest match after) and which matches user
agents by substring. The same robots.txt now gets the same answer on every
supported Python.

What it implements:

- **Lines** end in LF, CR, or CRLF. ``#`` starts a comment. Records are
  ``key: value``, keys case-insensitive. Only ``user-agent``, ``allow``, and
  ``disallow`` are read; others (``sitemap``, ``crawl-delay``) and lines
  without a colon are ignored.
- **Groups** (section 2.2.1): one or more ``user-agent`` lines, then rules.
  A ``user-agent`` line after a rule starts a new group. Rules before any
  ``user-agent`` belong to no group. The product token is the leading run
  of letters, ``_``, and ``-`` in the value, compared case-insensitively
  with the crawler's whole token, never as a substring. Every group naming
  the crawler is combined; if none does, every ``*`` group is combined; if
  there is no ``*`` group either, nothing is disallowed. A matching group
  with no rules allows everything.
- **Rules** (section 2.2.2): an empty value is no rule, and a value that
  does not start with ``/`` or ``*`` is not a path pattern and is ignored.
  The rule with the longest pattern, in octets after normalization, wins;
  between an ``allow`` and a ``disallow`` of the same length, ``allow``
  wins. No matching rule means allowed. ``/robots.txt`` is always allowed.
- **Special characters** (section 2.2.3): ``*`` matches any run of
  characters, and ``$`` ends the pattern when it is the last character.
  Anywhere else, ``$`` is literal. ``%2A`` and ``%24`` are a literal ``*``
  and ``$``.
- **Percent-encoding**: pattern and path are normalized the same way before
  comparison. An encoded unreserved character (``A-Z a-z 0-9 - . _ ~``) is
  decoded, any other encoding keeps its octet with uppercase hex, a
  character outside the URI character set is encoded as UTF-8, and a ``%``
  not followed by two hex digits becomes ``%25``.

Matching is linear passes over the path, with no regular expressions, so a
hostile pattern full of ``*`` cannot make it backtrack.
"""

import re
from dataclasses import dataclass

MATCHER_VERSION = "1"
"""The matcher's version. Any change to how rules are matched bumps it."""

_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_RESERVED = frozenset(":/?#[]@!$&'()*+,;=")
_HEX = frozenset("0123456789abcdefABCDEF")
_LINE_END = re.compile(r"\r\n|\r|\n")
_PRODUCT_TOKEN = re.compile(r"[A-Za-z_-]+")
_WILDCARD = "\x00"
"""Stands for a pattern's ``*`` after normalization; it cannot occur in a path."""


def _encode(character: str) -> str:
    """Percent-encode one character as UTF-8, with uppercase hex.

    :param character: The character.
    :return: Its encoding.
    """
    return "".join(f"%{octet:02X}" for octet in character.encode("utf-8"))


def _normalize(text: str, *, pattern: bool) -> str:
    """Normalize a pattern or a path for comparison.

    :param text: The pattern, or the path and query as sent.
    :param pattern: Whether ``text`` is a pattern, in which a ``*`` is a
        wildcard. In a path, ``*`` and ``$`` are literal.
    :return: The normalized text; a pattern's wildcards are ``_WILDCARD``.
    """
    out: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "%":
            digits = text[index + 1 : index + 3]
            if len(digits) == 2 and set(digits) <= _HEX:
                decoded = chr(int(digits, 16))
                out.append(decoded if decoded in _UNRESERVED else f"%{digits.upper()}")
                index += 3
                continue
            out.append("%25")
        elif character == "*":
            out.append(_WILDCARD if pattern else "%2A")
        elif character == "$":
            out.append("%24")
        elif character in _UNRESERVED or character in _RESERVED:
            out.append(character)
        else:
            out.append(_encode(character))
        index += 1
    return "".join(out)


@dataclass(frozen=True, kw_only=True)
class _Rule:
    """One allow or disallow rule, normalized for matching.

    :param allow: Whether the rule allows.
    :param parts: The pattern split at its wildcards.
    :param anchored: Whether the pattern ended in ``$``.
    :param length: The pattern's length in octets, for precedence.
    :param line: The rule as written, for evidence.
    """

    allow: bool
    parts: tuple[str, ...]
    anchored: bool
    length: int
    line: str

    def matches(self, path: str) -> bool:
        """Tell whether the rule's pattern matches a normalized path.

        :param path: The normalized path and query.
        :return: Whether it matches from the start of the path.
        """
        first, *rest = self.parts
        if not path.startswith(first):
            return False
        position = len(first)
        if not rest:
            return position == len(path) if self.anchored else True
        *middle, last = rest
        for part in middle:
            found = path.find(part, position)
            if found < 0:
                return False
            position = found + len(part)
        if self.anchored:
            return len(path) - len(last) >= position and path.endswith(last)
        return path.find(last, position) >= 0


def _rule(allow: bool, value: str, line: str) -> _Rule | None:
    """Build a rule from a record's value.

    :param allow: Whether it is an ``allow`` record.
    :param value: The record's value, trimmed.
    :param line: The record as written, for evidence.
    :return: The rule, or ``None`` if the value is empty or not a path pattern.
    """
    if not value or value[0] not in "/*":
        return None
    anchored = value.endswith("$")
    body = value[:-1] if anchored else value
    normalized = _normalize(body, pattern=True)
    return _Rule(
        allow=allow,
        parts=tuple(normalized.split(_WILDCARD)),
        anchored=anchored,
        length=len(normalized) + (1 if anchored else 0),
        line=line,
    )


@dataclass(frozen=True, kw_only=True)
class Verdict:
    """The matcher's answer for one path.

    :param allowed: Whether the path may be fetched.
    :param rule: The rule that decided, as written (for example
        ``Disallow: /private/``), or ``None`` if no rule matched.
    """

    allowed: bool
    rule: str | None


@dataclass(frozen=True, kw_only=True)
class _Group:
    """One group: the product tokens it names, and its rules.

    :param tokens: The product tokens, lowercased; ``*`` for every crawler.
    :param rules: The group's rules, in file order.
    """

    tokens: tuple[str, ...]
    rules: tuple[_Rule, ...]


class RobotsRules:
    """A parsed robots.txt.

    :param groups: The groups, in file order.
    """

    def __init__(self, groups: tuple[_Group, ...]) -> None:
        self._groups = groups

    @classmethod
    def parse(cls, text: str) -> "RobotsRules":
        """Parse robots.txt text.

        :param text: The decoded robots.txt.
        :return: The rules.
        """
        groups: list[_Group] = []
        tokens: list[str] = []
        rules: list[_Rule] = []
        in_agents = False
        for raw in _LINE_END.split(text):
            line = raw.split("#", 1)[0].strip()
            key, colon, value = line.partition(":")
            if not colon:
                continue
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if not in_agents:
                    if tokens:
                        groups.append(_Group(tokens=tuple(tokens), rules=tuple(rules)))
                    tokens, rules = [], []
                    in_agents = True
                if value == "*":
                    tokens.append("*")
                elif (token := _PRODUCT_TOKEN.match(value)) is not None:
                    tokens.append(token.group(0).lower())
            elif key in ("allow", "disallow"):
                in_agents = False
                if not tokens:
                    continue
                written = f"{'Allow' if key == 'allow' else 'Disallow'}: {value}"
                parsed = _rule(key == "allow", value, written)
                if parsed is not None:
                    rules.append(parsed)
        if tokens:
            groups.append(_Group(tokens=tuple(tokens), rules=tuple(rules)))
        return cls(tuple(groups))

    def check(self, product_token: str, path: str) -> Verdict:
        """Decide whether a crawler may fetch a path.

        :param product_token: The crawler's product token, such as ``Cernis``.
        :param path: The path and query exactly as they will be sent.
        :return: The verdict and the rule that decided.
        """
        if path.split("?", 1)[0] == "/robots.txt":
            return Verdict(allowed=True, rule=None)
        token = product_token.lower()
        chosen = [group for group in self._groups if token in group.tokens]
        if not chosen:
            chosen = [group for group in self._groups if "*" in group.tokens]
        normalized = _normalize(path, pattern=False)
        best: _Rule | None = None
        for group in chosen:
            for rule in group.rules:
                if not rule.matches(normalized):
                    continue
                if (
                    best is None
                    or rule.length > best.length
                    or (rule.length == best.length and rule.allow and not best.allow)
                ):
                    best = rule
        if best is None:
            return Verdict(allowed=True, rule=None)
        return Verdict(allowed=best.allow, rule=best.line)
