"""The finding, receipt, and snapshot model (DESIGN.md sections 3 and 5, ADR-001).

Every finding carries two independent fields: a :class:`Status` (how sure
Cernis is) and an :class:`Actor` (whose job it is). The rules that make each
status honest are enforced at construction, so an invalid finding cannot
exist.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from cernis import urls


class ModelError(ValueError):
    """Raised when a model object breaks a model rule."""


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
    """401 or 403."""
    RATE_LIMITED = "RATE_LIMITED"
    """429, still refused after retrying with backoff."""
    DISALLOWED_BY_ROBOTS = "DISALLOWED_BY_ROBOTS"
    ADDRESS_REFUSED = "ADDRESS_REFUSED"
    """The host resolves to a non-public address, so Cernis did not contact it (ADR-005)."""
    REQUIRES_RENDERING = "REQUIRES_RENDERING"
    AMBIGUOUS = "AMBIGUOUS"


NO_ATTEMPT_REASONS: frozenset[ReasonCode] = frozenset(
    {ReasonCode.REQUIRES_EXTERNAL_DATA, ReasonCode.PLATFORM_OPAQUE}
)
"""Reason codes for questions no attempt could answer.

A NOT_DETERMINABLE finding with one of these codes states ``would_require``
instead of carrying evidence. Every other code means Cernis attempted
something, and the finding must carry evidence of the attempt.
"""


class Family(StrEnum):
    """The two families of checks: on the page, or around it."""

    PERITEXT = "peritext"
    EPITEXT = "epitext"


class ErrorKind(StrEnum):
    """Why a fetch got no response, or ``NONE`` if it got one."""

    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    CONNECTION = "CONNECTION"
    TLS = "TLS"
    TOO_MANY_REDIRECTS = "TOO_MANY_REDIRECTS"
    ADDRESS_REFUSED = "ADDRESS_REFUSED"
    """The host resolved to an address that is not public, so nothing was sent (ADR-005)."""


class ChangeClass(StrEnum):
    """Who caused a page change between two runs (DESIGN.md section 5)."""

    CHECKER = "CHECKER"
    AUTHOR_CONTENT = "AUTHOR_CONTENT"
    AUTHOR_METADATA = "AUTHOR_METADATA"
    PLATFORM_RENDERING = "PLATFORM_RENDERING"
    UNCLASSIFIED = "UNCLASSIFIED"


RECORDED_HEADERS: frozenset[str] = frozenset(
    {"content-type", "etag", "last-modified", "retry-after", "x-robots-tag"}
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


def _require_sha256(owner: str, name: str, value: object) -> None:
    """Raise unless ``value`` is a lowercase hex SHA-256 digest.

    :param owner: Description of the object being validated, for the message.
    :param name: The field name, for the message.
    :param value: The value to check.
    :raises ModelError: If ``value`` is not 64 lowercase hex characters.
    """
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise ModelError(f"{owner}: {name} must be 64 lowercase hex characters")


def finding_key(check_id: str, subject_url: str, target: str) -> str:
    """Compute the key that identifies a finding across runs (DESIGN.md section 3).

    The key is the SHA-256 of a compact JSON array (UTF-8, no ASCII escaping)
    of the check id, the subject URL, and the target, each normalized first:

    - every string is put in Unicode NFC;
    - the subject URL goes through :func:`cernis.urls.normalize_url`;
    - a target that is an absolute http(s) URL (a link, an image) goes
      through the same normalization; any other target is an identifier from
      Cernis's own vocabulary (``og:image``, a crawler name) and is only NFC.

    It leaves out ``check_version`` on purpose: the same key with a different
    version is how history recognizes a ``CHECKER`` change.

    **The computation is final as of Session 4a.** Changing it, or the URL
    normalization it uses, changes every key and makes stored history
    unmatchable, so it must not change before Phase 5 without an ADR.

    :param check_id: The registered check id.
    :param subject_url: The article URL, before normalization.
    :param target: What specifically was checked, or an empty string.
    :return: The key, as 64 lowercase hex characters.
    """
    target = unicodedata.normalize("NFC", target)
    if urls.is_absolute_http_url(target):
        target = urls.normalize_url(target)
    payload = json.dumps(
        [unicodedata.normalize("NFC", check_id), urls.normalize_url(subject_url), target],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    - ``NOT_DETERMINABLE`` needs a ``reason_code`` and a ``question``. For a
      code in :data:`NO_ATTEMPT_REASONS` it needs ``would_require`` and no
      evidence; for any other code it needs evidence of the attempt and no
      ``would_require``.

    Fields that belong to one status (``rationale`` and ``based_on`` to
    ``RECOMMENDATION``; ``reason_code``, ``question``, and ``would_require``
    to ``NOT_DETERMINABLE``) must be left empty on the others.

    Whether each ``based_on`` id names an ``OBSERVED`` finding in the same run
    cannot be checked from one finding alone; that is checked at run assembly.

    ``key`` is derived, never passed in: see :func:`finding_key`.

    :param id: Identifier, unique within a run.
    :param check_id: The registered check that produced the finding.
    :param check_version: The version of that check.
    :param status: How sure Cernis is.
    :param actor: Who can change the thing the finding is about.
    :param subject_url: The article URL the finding is about.
    :param summary: One sentence, in plain English.
    :param target: What specifically was checked when a check covers several
        things (such as ``og:image`` or a link URL); empty otherwise.
    :param evidence: What Cernis saw or searched for.
    :param defect: Whether an ``OBSERVED`` condition violates a published
        standard or the author's stated intent (DESIGN.md principle 4).
    :param rationale: ``RECOMMENDATION`` only: why, citing the standard or the
        stated intent.
    :param based_on: ``RECOMMENDATION`` only: ids of the findings it rests on.
    :param reason_code: ``NOT_DETERMINABLE`` only: why it cannot be answered.
    :param question: ``NOT_DETERMINABLE`` only: what could not be answered.
    :param would_require: ``NOT_DETERMINABLE`` only, for a code in
        :data:`NO_ATTEMPT_REASONS`: the data that would answer the question.
    :raises ModelError: If any status rule or field rule is broken.
    """

    id: str
    check_id: str
    check_version: str
    status: Status
    actor: Actor
    subject_url: str
    summary: str
    target: str = ""
    evidence: tuple[Evidence, ...] = ()
    defect: bool = False
    rationale: str | None = None
    based_on: tuple[str, ...] = ()
    reason_code: ReasonCode | None = None
    question: str | None = None
    would_require: str | None = None
    key: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate the common fields and the rules for the status, then derive the key.

        :raises ModelError: If any rule is broken.
        """
        owner = f"Finding {self.id!r}"
        for name in ("id", "check_id", "check_version", "subject_url", "summary"):
            _require_text(owner, name, getattr(self, name))
        if not isinstance(self.target, str) or (self.target and not self.target.strip()):
            raise ModelError(f"{owner}: target must be empty or a non-blank string")
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
            for name in ("reason_code", "question", "would_require"):
                if getattr(self, name) is not None:
                    raise ModelError(f"{owner}: {name} is for NOT_DETERMINABLE findings only")

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
            self._validate_not_determinable(owner)

        object.__setattr__(self, "key", finding_key(self.check_id, self.subject_url, self.target))

    def _validate_not_determinable(self, owner: str) -> None:
        """Apply the NOT_DETERMINABLE rules.

        :param owner: Description of the finding, for messages.
        :raises ModelError: If any NOT_DETERMINABLE rule is broken.
        """
        if not isinstance(self.reason_code, ReasonCode):
            raise ModelError(f"{owner}: needs a reason_code")
        _require_text(owner, "question", self.question)
        if self.reason_code in NO_ATTEMPT_REASONS:
            _require_text(owner, "would_require", self.would_require)
            if self.evidence:
                raise ModelError(
                    f"{owner}: {self.reason_code} means no attempt was possible, "
                    "so it carries would_require, not evidence"
                )
        else:
            if not self.evidence:
                raise ModelError(f"{owner}: {self.reason_code} needs evidence of the attempt")
            if self.would_require is not None:
                raise ModelError(
                    f"{owner}: would_require is only for {', '.join(sorted(NO_ATTEMPT_REASONS))}"
                )


@dataclass(frozen=True, kw_only=True)
class Receipt:
    """A record of the raw facts of one fetch, and nothing parsed.

    ``error_kind`` says how the attempt ended (ADR-004):

    - ``NONE``: a response arrived whole. ``status_code`` and ``final_url``
      are set.
    - ``TIMEOUT``, ``CONNECTION``, ``TLS``: the last request failed.
      ``final_url`` names the URL whose request failed. If the status line
      and headers arrived before the body failed, ``status_code`` and
      ``headers`` keep them; otherwise ``status_code`` is ``None`` and there
      are no headers. ``body_sha256`` is ``None``.
    - ``ADDRESS_REFUSED``: the URL's host resolved to an address that is
      not public, so nothing was sent (ADR-005). ``final_url`` names the
      refused URL; ``status_code`` is ``None``.
    - ``TOO_MANY_REDIRECTS``: the redirect limit was reached, so there is no
      final response. ``status_code``, ``final_url``, and ``body_sha256`` are
      ``None``, and ``redirect_chain`` holds every URL that redirected.

    ``redirect_chain`` lists, in order, every URL whose redirect was
    followed, starting with ``requested_url``; it is empty when no redirect
    was followed, in which case ``final_url`` equals ``requested_url``. A
    redirect that was not followed (an unusable ``Location``, or a target
    robots.txt disallows) is the final response: its URL is ``final_url``
    and its 3xx is ``status_code``.

    ``body_sha256`` is the hash of the whole body or ``None``, never the hash
    of part of one. A body longer than the fetcher's size limit is not read
    past the limit, so its hash is ``None`` and ``body_truncated_at`` records
    the limit (ADR-003). For a ``304 Not Modified``, which has no body,
    ``body_sha256`` is the hash of the cached body the response validated.

    :param id: Identifier, stable within a run.
    :param requested_url: The URL Cernis asked for.
    :param final_url: The URL of the last request, after redirects: the one
        that answered, or the one whose request failed. ``None`` only for
        ``TOO_MANY_REDIRECTS``.
    :param redirect_chain: The URLs whose redirects were followed, in order.
    :param status_code: The last HTTP status received, or ``None`` if none.
    :param error_kind: How the attempt failed, or ``NONE``.
    :param fetched_at: When the fetch happened, timezone-aware, in UTC.
    :param body_sha256: Lowercase hex SHA-256 of the whole response body, for
        ``NONE`` only.
    :param body_truncated_at: The size limit, in bytes, at which Cernis
        stopped reading a body that was longer; ``None`` if the body was read
        whole.
    :param headers: ``(name, value)`` pairs for the response headers in
        :data:`RECORDED_HEADERS`, names in lowercase, each at most once; only
        with a ``status_code``.
        Stored sorted by name, so order does not affect equality.
    :param cernis_version: The Cernis version that made the fetch.
    :param user_agent: The user agent sent with the request.
    :raises ModelError: If any receipt rule is broken.
    """

    id: str
    requested_url: str
    final_url: str | None
    redirect_chain: tuple[str, ...] = ()
    status_code: int | None
    error_kind: ErrorKind
    fetched_at: datetime
    body_sha256: str | None
    body_truncated_at: int | None = None
    headers: tuple[tuple[str, str], ...] = ()
    cernis_version: str
    user_agent: str

    def __post_init__(self) -> None:
        """Validate the receipt and sort its headers.

        :raises ModelError: If any receipt rule is broken.
        """
        owner = f"Receipt {self.id!r}"
        for name in ("id", "requested_url", "cernis_version", "user_agent"):
            _require_text(owner, name, getattr(self, name))

        if not isinstance(self.error_kind, ErrorKind):
            raise ModelError(f"{owner}: error_kind must be an ErrorKind, got {self.error_kind!r}")
        if self.status_code is not None and (
            not isinstance(self.status_code, int) or isinstance(self.status_code, bool)
        ):
            raise ModelError(f"{owner}: status_code must be an int or None")
        succeeded = self.error_kind is ErrorKind.NONE
        too_many = self.error_kind is ErrorKind.TOO_MANY_REDIRECTS
        if succeeded and self.status_code is None:
            raise ModelError(f"{owner}: error_kind NONE requires a status_code")
        refused = self.error_kind is ErrorKind.ADDRESS_REFUSED
        if (too_many or refused) and self.status_code is not None:
            raise ModelError(f"{owner}: error_kind {self.error_kind} requires no status_code")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ModelError(f"{owner}: status_code {self.status_code} is not 100 to 599")

        if not isinstance(self.redirect_chain, tuple):
            raise ModelError(f"{owner}: redirect_chain must be a tuple of URLs")
        if self.redirect_chain and self.redirect_chain[0] != self.requested_url:
            raise ModelError(f"{owner}: redirect_chain must start with requested_url")
        if too_many and not self.redirect_chain:
            raise ModelError(f"{owner}: TOO_MANY_REDIRECTS needs the redirect_chain it followed")

        if too_many:
            if self.final_url is not None:
                raise ModelError(f"{owner}: final_url must be None for TOO_MANY_REDIRECTS")
        else:
            _require_text(owner, "final_url", self.final_url)
            if not self.redirect_chain and self.final_url != self.requested_url:
                raise ModelError(
                    f"{owner}: final_url must equal requested_url when there is no redirect"
                )

        if self.body_sha256 is not None:
            if not succeeded:
                raise ModelError(f"{owner}: body_sha256 requires a successful response")
            _require_sha256(owner, "body_sha256", self.body_sha256)
        if self.body_truncated_at is not None:
            if (
                not isinstance(self.body_truncated_at, int)
                or isinstance(self.body_truncated_at, bool)
                or self.body_truncated_at <= 0
            ):
                raise ModelError(f"{owner}: body_truncated_at must be a positive int or None")
            if not succeeded:
                raise ModelError(f"{owner}: body_truncated_at requires a successful response")
            if self.body_sha256 is not None:
                raise ModelError(
                    f"{owner}: body_sha256 must be None when the body was cut off "
                    "at body_truncated_at"
                )

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
        if self.headers and self.status_code is None:
            raise ModelError(f"{owner}: headers require a status_code")
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


@dataclass(frozen=True, kw_only=True)
class Snapshot:
    """What the parser derived from one receipt, for comparing runs.

    History compares snapshots, not raw bodies, because a raw body changes
    whenever a platform rotates an asset hash or a token. Each hash is over
    normalized text. If the extractor finds no article body,
    ``content_sha256`` is ``None``, and any change involving the snapshot is
    ``UNCLASSIFIED``.

    :param receipt_id: The receipt the snapshot was derived from.
    :param extractor_id: The site-aware extractor used, such as
        ``dev.article`` or ``wordpress.entry``.
    :param extractor_version: The version of that extractor.
    :param content_sha256: SHA-256 of the normalized article body text, or
        ``None`` if no body was found.
    :param head_sha256: SHA-256 of the normalized, sorted ``<head>`` metadata
        (canonical, meta, og:*, JSON-LD, lang, title).
    :param frame_sha256: SHA-256 of the rest of the page, normalized
        (navigation, footer, template).
    :raises ModelError: If an identifier is blank or a hash is malformed.
    """

    receipt_id: str
    extractor_id: str
    extractor_version: str
    content_sha256: str | None
    head_sha256: str
    frame_sha256: str

    def __post_init__(self) -> None:
        """Validate the snapshot; the class docstring lists what raises ModelError."""
        owner = f"Snapshot for receipt {self.receipt_id!r}"
        for name in ("receipt_id", "extractor_id", "extractor_version"):
            _require_text(owner, name, getattr(self, name))
        if self.content_sha256 is not None:
            _require_sha256(owner, "content_sha256", self.content_sha256)
        _require_sha256(owner, "head_sha256", self.head_sha256)
        _require_sha256(owner, "frame_sha256", self.frame_sha256)
