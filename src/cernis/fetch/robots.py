"""robots.txt for Cernis's own user agent (DESIGN.md section 6, RFC 9309).

This module decides what a fetched robots.txt means; the fetcher fetches it,
once per origin per run, and the fetch is a receipt like any other.

How the robots.txt response is read (RFC 9309 section 2.3.1):

- ``2xx``, or a ``304`` validating a cached copy: the rules are parsed with
  :mod:`urllib.robotparser` and applied to Cernis's user agent.
- ``4xx`` other than ``429``: robots.txt is unavailable, so everything is
  allowed (section 2.3.1.3).
- ``5xx``, ``429``, any fetch with no response, and any other status:
  robots.txt is unreachable, so everything is disallowed (section 2.3.1.4).
  RFC 9309 counts ``429`` as a 4xx, but a server that is rate limiting
  Cernis has not said it may crawl; treating it as unreachable is the polite
  reading (SESSION-03.md decision 4).

Rule matching is :mod:`urllib.robotparser`'s, as DESIGN.md section 6
specifies, and it depends on the Python version. On 3.14 the most specific
rule wins and ``*`` and ``$`` are honored, as RFC 9309 section 2.2 requires;
on 3.12 and 3.13 the first matching rule in file order wins and ``*`` and
``$`` are literal characters. The same robots.txt can therefore get a
different decision on a different Python. SESSION-03.md decision 5 records
this for an Owner decision before Phase 4.
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.robotparser import RobotFileParser

import httpx

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
    """

    url: str
    robots_url: str
    allowed: bool
    basis: RobotsBasis
    receipt_id: str


def robots_url_for(url: str) -> str:
    """Return the robots.txt URL for the origin (scheme, host, and port) of ``url``.

    :param url: An absolute http or https URL.
    :return: The origin's ``/robots.txt`` URL, with no user information, query,
        or fragment.
    """
    parsed = httpx.URL(url)
    return str(parsed.copy_with(userinfo=b"", path="/robots.txt", query=None, fragment=None))


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
        self._parser: RobotFileParser | None = None
        status = receipt.status_code
        if receipt.error_kind is not ErrorKind.NONE or status is None:
            self.basis = RobotsBasis.UNREACHABLE
        elif 200 <= status <= 299 or (status == 304 and body is not None):
            self.basis = RobotsBasis.RULES
            rules = body or b""
            if receipt.body_truncated_at is not None:
                # The last line was cut off at the limit; a partial rule is not a rule.
                rules = rules[: rules.rfind(b"\n") + 1]
            text = rules.decode("utf-8", errors="replace").removeprefix("\ufeff")
            self._parser = RobotFileParser()
            self._parser.parse(text.splitlines())
        elif 400 <= status <= 499 and status != 429:
            self.basis = RobotsBasis.UNAVAILABLE
        else:
            self.basis = RobotsBasis.UNREACHABLE

    def decide(self, url: str, user_agent: str) -> RobotsDecision:
        """Decide whether ``user_agent`` may fetch ``url``.

        :param url: A URL on this policy's origin.
        :param user_agent: The full user agent; :mod:`urllib.robotparser`
            matches its product token (the part before the first ``/``).
        :return: The decision.
        """
        if self._parser is not None:
            allowed = self._parser.can_fetch(user_agent, url)
        else:
            allowed = self.basis is RobotsBasis.UNAVAILABLE
        return RobotsDecision(
            url=url,
            robots_url=self.robots_url,
            allowed=allowed,
            basis=self.basis,
            receipt_id=self.receipt_id,
        )
