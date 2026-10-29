"""robots.txt for Cernis's own user agent (DESIGN.md section 6, RFC 9309).

This module decides what a fetched robots.txt means; the fetcher fetches it,
once per origin per run, and the fetch is a receipt like any other.

How the robots.txt response is read (RFC 9309 section 2.3.1):

- ``2xx``, or a ``304`` validating a cached copy: the rules are parsed by
  Cernis's own matcher (:mod:`cernis.fetch.rfc9309`) and applied to
  Cernis's product token.
- ``4xx`` other than ``429``: robots.txt is unavailable, so everything is
  allowed (section 2.3.1.3).
- ``5xx``, ``429``, any fetch with no response, and any other status:
  robots.txt is unreachable, so everything is disallowed (section 2.3.1.4).
  RFC 9309 counts ``429`` as a 4xx; Cernis departs from it here on purpose,
  for politeness (ADR-006).

Rules are matched against the path and query exactly as the request sends
them: the URL in httpx's normalized form, still percent-encoded.
"""

from dataclasses import dataclass
from enum import StrEnum

import httpx

from cernis.fetch.rfc9309 import MATCHER_VERSION, RobotsRules
from cernis.model import ErrorKind, Receipt


class RobotsBasis(StrEnum):
    """What a robots decision rests on."""

    RULES = "RULES"
    """robots.txt was fetched and its rules were applied."""
    UNAVAILABLE = "UNAVAILABLE"
    """robots.txt answered 4xx (not 429), so everything is allowed."""
    UNREACHABLE = "UNREACHABLE"
    """robots.txt answered 5xx or 429, or did not answer, so everything is disallowed."""


@dataclass(frozen=True, kw_only=True)
class RobotsDecision:
    """Whether Cernis may fetch one URL, and why.

    :param url: The URL Cernis wanted to fetch.
    :param robots_url: The robots.txt that governs it.
    :param allowed: Whether Cernis may fetch it.
    :param basis: What the decision rests on.
    :param receipt_id: The receipt of the robots.txt fetch the decision rests
        on (the last attempt, when the fetch was retried).
    :param rule: For ``RULES``, the rule that decided, as written (such as
        ``Disallow: /private/``), or ``None`` if no rule matched.
    :param matcher_version: The :data:`~cernis.fetch.rfc9309.MATCHER_VERSION`
        that made the decision.
    """

    url: str
    robots_url: str
    allowed: bool
    basis: RobotsBasis
    receipt_id: str
    rule: str | None = None
    matcher_version: str = MATCHER_VERSION


def robots_url_for(url: str) -> str:
    """Return the robots.txt URL for the origin (scheme, host, and port) of ``url``.

    :param url: An absolute http or https URL.
    :return: The origin's ``/robots.txt`` URL, with no user information, query,
        or fragment.
    """
    parsed = httpx.URL(url)
    return str(parsed.copy_with(userinfo=b"", path="/robots.txt", query=None, fragment=None))


def product_token(user_agent: str) -> str:
    """Return the product token of a user agent: the part before the first ``/``.

    :param user_agent: The user agent, such as ``Cernis/0.1.0 (+https://...)``.
    :return: The product token, such as ``Cernis``.
    """
    return user_agent.split("/", 1)[0].strip()


class RobotsPolicy:
    """What one origin's robots.txt allows.

    :param robots_url: The robots.txt URL.
    :param receipt: The receipt of the robots.txt fetch (the last attempt).
    :param body: The body that fetch produced, or the cached body a ``304``
        validated; ``None`` if there was none.
    """

    def __init__(self, robots_url: str, receipt: Receipt, body: bytes | None) -> None:
        self.robots_url = robots_url
        self.receipt_id = receipt.id
        self._rules: RobotsRules | None = None
        status = receipt.status_code
        if receipt.error_kind is not ErrorKind.NONE or status is None:
            self.basis = RobotsBasis.UNREACHABLE
        elif 200 <= status <= 299 or (status == 304 and body is not None):
            self.basis = RobotsBasis.RULES
            rules = body or b""
            if receipt.body_truncated_at is not None:
                # The last line was cut off at the limit; a partial rule is not a rule.
                rules = rules[: rules.rfind(b"\n") + 1]
            text = rules.decode("utf-8", errors="replace").removeprefix("﻿")
            self._rules = RobotsRules.parse(text)
        elif 400 <= status <= 499 and status != 429:
            self.basis = RobotsBasis.UNAVAILABLE
        else:
            self.basis = RobotsBasis.UNREACHABLE

    def decide(self, url: str, user_agent: str) -> RobotsDecision:
        """Decide whether ``user_agent`` may fetch ``url``.

        :param url: A URL on this policy's origin, in httpx's normalized form.
        :param user_agent: The full user agent; its product token is matched.
        :return: The decision.
        """
        rule = None
        if self._rules is not None:
            verdict = self._rules.check(product_token(user_agent), _path_as_sent(url))
            allowed, rule = verdict.allowed, verdict.rule
        else:
            allowed = self.basis is RobotsBasis.UNAVAILABLE
        return RobotsDecision(
            url=url,
            robots_url=self.robots_url,
            allowed=allowed,
            basis=self.basis,
            receipt_id=self.receipt_id,
            rule=rule,
        )


def _path_as_sent(url: str) -> str:
    """Return the path and query a request for ``url`` sends.

    :param url: An absolute URL.
    :return: The request target, percent-encoded, without the fragment.
    """
    return httpx.URL(url).raw_path.decode("ascii")
