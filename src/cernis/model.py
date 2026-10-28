"""The finding and receipt model (DESIGN.md section 3, ADR-001).

Every finding carries two independent fields: a :class:`Status` (how sure
Cernis is) and an :class:`Actor` (whose job it is). The rules that make each
status honest are enforced at construction, so an invalid finding cannot
exist.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class ModelError(ValueError):
    """Raised when a finding, evidence, or receipt breaks a model rule."""


class Status(StrEnum):
    """How sure Cernis is about a finding."""

    OBSERVED = "OBSERVED"
    RECOMMENDATION = "RECOMMENDATION"
    NOT_DETERMINABLE = "NOT_DETERMINABLE"


class Actor(StrEnum):
    """Who can change the thing a finding is about."""

    AUTHOR = "AUTHOR"
    PLATFORM = "PLATFORM"
    UNKNOWN = "UNKNOWN"


class ReasonCode(StrEnum):
    """Why a NOT_DETERMINABLE finding could not be answered."""

    REQUIRES_EXTERNAL_DATA = "REQUIRES_EXTERNAL_DATA"
    PLATFORM_OPAQUE = "PLATFORM_OPAQUE"
    FETCH_FAILED = "FETCH_FAILED"
    ACCESS_DENIED = "ACCESS_DENIED"
    DISALLOWED_BY_ROBOTS = "DISALLOWED_BY_ROBOTS"
    REQUIRES_RENDERING = "REQUIRES_RENDERING"
    AMBIGUOUS = "AMBIGUOUS"


class Family(StrEnum):
    """The two families of checks: on the page, or around it."""

    PERITEXT = "peritext"
    EPITEXT = "epitext"


RECORDED_HEADERS: frozenset[str] = frozenset(
    {"content-type", "etag", "last-modified", "x-robots-tag"}
)
"""The fixed subset of response headers a receipt records, in lowercase."""

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _require_text(owner: str, name: str, value: object) -> None:
    """Raise unless ``value`` is a string with non-whitespace content.

    :param owner: Description of the object being validated, for the message.
    :param name: The field name, for the message.
    :param value: The value to check.
    :raises ModelError: If ``value`` is not a non-blank string.
    """
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{owner}: {name} must be a non-blank string")


@dataclass(frozen=True, kw_only=True)
class Evidence:
    """What Cernis saw, or what it looked for and did not find.

    Absence is evidence (DESIGN.md principle 5): evidence with ``observed``
    set to ``None`` and ``searched_for`` set records a search that came up
    empty. An empty string in ``observed`` is an observed value (for example,
    an empty ``content`` attribute), not an absence.

    :param receipt_id: The receipt for the response this evidence came from.
    :param location: Where Cernis looked, such as a selector or a header name.
    :param observed: The value found there, or ``None`` if nothing was found.
    :param searched_for: What Cernis searched for, required when nothing was
        found.
    :raises ModelError: If an identifier is blank, ``searched_for`` is blank,
        or neither ``observed`` nor ``searched_for`` is given.
    """

    receipt_id: str
    location: str
    observed: str | None = None
    searched_for: str | None = None

    def __post_init__(self) -> None:
        """Validate the evidence.

        :raises ModelError: If any evidence rule is broken.
        """
        _require_text("Evidence", "receipt_id", self.receipt_id)
        _require_text("Evidence", "location", self.location)
        if self.searched_for is not None:
            _require_text("Evidence", "searched_for", self.searched_for)
        if self.observed is None and self.searched_for is None:
            raise ModelError("Evidence: must record an observed value or what was searched for")


@dataclass(frozen=True, kw_only=True)
class Finding:
    """One result of one check, with its epistemic status (ADR-001).

    Status rules, enforced at construction:

    - ``OBSERVED`` needs at least one :class:`Evidence`. Only ``OBSERVED``
      may set ``defect``.
    - ``RECOMMENDATION`` needs a non-empty ``based_on`` and a ``rationale``.
    - ``NOT_DETERMINABLE`` needs a ``reason_code`` and a ``question``.

    Fields that belong to one status (``rationale`` and ``based_on`` to
    ``RECOMMENDATION``; ``reason_code`` and ``question`` to
    ``NOT_DETERMINABLE``) must be left empty on the others.

    Whether each ``based_on`` id names an ``OBSERVED`` finding in the same run
    cannot be checked from one finding alone; that is checked where a run's
    findings are assembled.

    :param id: Identifier, stable within a run.
    :param check_id: The registered check that produced the finding.
    :param check_version: The version of that check.
    :param status: How sure Cernis is.
    :param actor: Who can change the thing the finding is about.
    :param subject_url: The article URL the finding is about.
    :param summary: One sentence, in plain English.
    :param evidence: What Cernis saw or searched for.
    :param defect: Whether an ``OBSERVED`` condition violates a published
        standard or the author's stated intent (DESIGN.md principle 4).
    :param rationale: ``RECOMMENDATION`` only: why, citing the standard or the
        stated intent.
    :param based_on: ``RECOMMENDATION`` only: ids of the findings it rests on.
    :param reason_code: ``NOT_DETERMINABLE`` only: why it cannot be answered.
    :param question: ``NOT_DETERMINABLE`` only: what could not be answered.
    :raises ModelError: If any status rule or field rule is broken.
    """

    id: str
    check_id: str
    check_version: str
    status: Status
    actor: Actor
    subject_url: str
    summary: str
    evidence: tuple[Evidence, ...] = ()
    defect: bool = False
    rationale: str | None = None
    based_on: tuple[str, ...] = ()
    reason_code: ReasonCode | None = None
    question: str | None = None

    def __post_init__(self) -> None:
        """Validate the common fields, then the rules for the status.

        :raises ModelError: If any rule is broken.
        """
        owner = f"Finding {self.id!r}"
        for name in ("id", "check_id", "check_version", "subject_url", "summary"):
            _require_text(owner, name, getattr(self, name))
        if not isinstance(self.status, Status):
            raise ModelError(f"{owner}: status must be a Status, got {self.status!r}")
        if not isinstance(self.actor, Actor):
            raise ModelError(f"{owner}: actor must be an Actor, got {self.actor!r}")
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(item, Evidence) for item in self.evidence
        ):
            raise ModelError(f"{owner}: evidence must be a tuple of Evidence")
        if not isinstance(self.based_on, tuple):
            raise ModelError(f"{owner}: based_on must be a tuple of finding ids")
        if not isinstance(self.defect, bool):
            raise ModelError(f"{owner}: defect must be a bool, got {self.defect!r}")

        owner = f"{self.status} finding {self.id!r}"
        if self.defect and self.status is not Status.OBSERVED:
            raise ModelError(f"{owner}: only an OBSERVED finding may set defect")
        if self.status is not Status.RECOMMENDATION:
            if self.rationale is not None:
                raise ModelError(f"{owner}: rationale is for RECOMMENDATION findings only")
            if self.based_on:
                raise ModelError(f"{owner}: based_on is for RECOMMENDATION findings only")
        if self.status is not Status.NOT_DETERMINABLE:
            if self.reason_code is not None:
                raise ModelError(f"{owner}: reason_code is for NOT_DETERMINABLE findings only")
            if self.question is not None:
                raise ModelError(f"{owner}: question is for NOT_DETERMINABLE findings only")

        if self.status is Status.OBSERVED:
            if not self.evidence:
                raise ModelError(f"{owner}: must carry at least one Evidence")
        elif self.status is Status.RECOMMENDATION:
            if not self.based_on:
                raise ModelError(f"{owner}: needs a non-empty based_on")
            for ref in self.based_on:
                _require_text(owner, "based_on entry", ref)
            if self.id in self.based_on:
                raise ModelError(f"{owner}: based_on may not reference the finding itself")
            _require_text(owner, "rationale", self.rationale)
        else:
            if not isinstance(self.reason_code, ReasonCode):
                raise ModelError(f"{owner}: needs a reason_code")
            _require_text(owner, "question", self.question)


@dataclass(frozen=True, kw_only=True)
class Receipt:
    """A record of one fetch: what was asked for and exactly what came back.

    ``redirect_chain`` lists, in order, every URL that answered with a
    redirect, starting with ``requested_url``; it is empty when there was no
    redirect, in which case ``final_url`` equals ``requested_url``. A fetch
    that got no response at all (a timeout or connection error) has
    ``status_code`` and ``body_sha256`` set to ``None``.

    :param id: Identifier, stable within a run.
    :param requested_url: The URL Cernis asked for.
    :param final_url: The URL that answered, after redirects.
    :param redirect_chain: The URLs that redirected, in order.
    :param status_code: The final HTTP status, or ``None`` if no response.
    :param fetched_at: When the fetch happened, timezone-aware, in UTC.
    :param body_sha256: Lowercase hex SHA-256 of the response body, if any.
    :param headers: ``(name, value)`` pairs for the response headers in
        :data:`RECORDED_HEADERS`, names in lowercase, each at most once.
        Stored sorted by name, so order does not affect equality.
    :param cernis_version: The Cernis version that made the fetch.
    :param user_agent: The user agent sent with the request.
    :raises ModelError: If any receipt rule is broken.
    """

    id: str
    requested_url: str
    final_url: str
    redirect_chain: tuple[str, ...] = ()
    status_code: int | None
    fetched_at: datetime
    body_sha256: str | None
    headers: tuple[tuple[str, str], ...] = ()
    cernis_version: str
    user_agent: str

    def __post_init__(self) -> None:
        """Validate the receipt and sort its headers.

        :raises ModelError: If any receipt rule is broken.
        """
        owner = f"Receipt {self.id!r}"
        for name in ("id", "requested_url", "final_url", "cernis_version", "user_agent"):
            _require_text(owner, name, getattr(self, name))

        if not isinstance(self.redirect_chain, tuple):
            raise ModelError(f"{owner}: redirect_chain must be a tuple of URLs")
        if self.redirect_chain:
            if self.redirect_chain[0] != self.requested_url:
                raise ModelError(f"{owner}: redirect_chain must start with requested_url")
        elif self.final_url != self.requested_url:
            raise ModelError(
                f"{owner}: final_url must equal requested_url when there is no redirect"
            )

        if self.status_code is not None and (
            not isinstance(self.status_code, int) or isinstance(self.status_code, bool)
        ):
            raise ModelError(f"{owner}: status_code must be an int or None")
        if self.status_code is None:
            if self.body_sha256 is not None:
                raise ModelError(f"{owner}: body_sha256 requires a response (status_code)")
        elif not 100 <= self.status_code <= 599:
            raise ModelError(f"{owner}: status_code {self.status_code} is not 100 to 599")
        if self.body_sha256 is not None and not _SHA256_HEX.fullmatch(self.body_sha256):
            raise ModelError(f"{owner}: body_sha256 must be 64 lowercase hex characters")

        if not isinstance(self.fetched_at, datetime) or self.fetched_at.utcoffset() != timedelta(0):
            raise ModelError(f"{owner}: fetched_at must be timezone-aware and in UTC")

        if not isinstance(self.headers, tuple) or not all(
            isinstance(pair, tuple)
            and len(pair) == 2
            and all(isinstance(part, str) for part in pair)
            for pair in self.headers
        ):
            raise ModelError(f"{owner}: headers must be a tuple of (name, value) string pairs")
        names = [name for name, _ in self.headers]
        unexpected = sorted(set(names) - RECORDED_HEADERS)
        if unexpected:
            raise ModelError(
                f"{owner}: headers outside the recorded subset: {', '.join(unexpected)}"
            )
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ModelError(f"{owner}: headers repeated: {', '.join(repeated)}")
        object.__setattr__(self, "headers", tuple(sorted(self.headers)))

    def header(self, name: str) -> str | None:
        """Return a recorded header's value.

        :param name: The lowercase header name.
        :return: The value, or ``None`` if the header was not recorded.
        """
        return dict(self.headers).get(name)
