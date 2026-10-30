"""Tests for the finding, receipt, and snapshot model in :mod:`cernis.model`."""

import copy
import dataclasses
import hashlib
import pickle
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from cernis import urls
from cernis.model import (
    NO_ATTEMPT_REASONS,
    Actor,
    ChangeClass,
    ErrorKind,
    Evidence,
    Finding,
    ModelError,
    ReasonCode,
    Receipt,
    Snapshot,
    Status,
    finding_key,
)

EVIDENCE = Evidence(
    receipt_id="r-001",
    location="head > link[rel=canonical]",
    observed="https://example.com/post/",
)
ATTEMPT = Evidence(receipt_id="r-002", location="HTTP status", observed="403")
ATTEMPT_REASONS = sorted(set(ReasonCode) - NO_ATTEMPT_REASONS)


def observed(**overrides: object) -> Finding:
    """Build a valid OBSERVED finding, with optional field overrides."""
    fields: dict[str, Any] = {
        "id": "f-001",
        "check_id": "peri.canonical.present",
        "check_version": "1",
        "status": Status.OBSERVED,
        "actor": Actor.AUTHOR,
        "subject_url": "https://example.com/post/",
        "summary": "The page declares a canonical URL.",
        "evidence": (EVIDENCE,),
    }
    fields.update(overrides)
    return Finding(**fields)


def recommendation(**overrides: object) -> Finding:
    """Build a valid RECOMMENDATION finding, with optional field overrides."""
    fields: dict[str, Any] = {
        "id": "f-002",
        "check_id": "epi.pair.canonical",
        "check_version": "1",
        "status": Status.RECOMMENDATION,
        "actor": Actor.AUTHOR,
        "subject_url": "https://example.com/post/",
        "summary": "Set the copy's canonical URL to the original.",
        "rationale": "The author declared the original; the copy's canonical contradicts it.",
        "based_on": ("f-001",),
    }
    fields.update(overrides)
    return Finding(**fields)


def not_determinable(**overrides: object) -> Finding:
    """Build a valid NOT_DETERMINABLE finding, with optional field overrides."""
    fields: dict[str, Any] = {
        "id": "f-003",
        "check_id": "epi.links.resolve",
        "check_version": "1",
        "status": Status.NOT_DETERMINABLE,
        "actor": Actor.UNKNOWN,
        "subject_url": "https://example.com/post/",
        "summary": "Whether https://example.org/paper resolves.",
        "target": "https://example.org/paper",
        "reason_code": ReasonCode.ACCESS_DENIED,
        "question": "Does https://example.org/paper resolve?",
        "evidence": (ATTEMPT,),
    }
    fields.update(overrides)
    return Finding(**fields)


def receipt(**overrides: object) -> Receipt:
    """Build a valid receipt, with optional field overrides."""
    fields: dict[str, Any] = {
        "id": "r-001",
        "requested_url": "https://example.com/post",
        "final_url": "https://example.com/post/",
        "redirect_chain": ("https://example.com/post",),
        "status_code": 200,
        "error_kind": ErrorKind.NONE,
        "fetched_at": datetime(2026, 10, 28, 18, 0, tzinfo=UTC),
        "body_sha256": "a" * 64,
        "headers": (("content-type", "text/html; charset=utf-8"),),
        "cernis_version": "0.1.0.dev0",
        "user_agent": "Cernis/0.1.0.dev0 (+https://github.com/kenwalger/cernis)",
    }
    fields.update(overrides)
    return Receipt(**fields)


def no_response(**overrides: object) -> Receipt:
    """Build a valid receipt for a request that failed before any response arrived."""
    fields: dict[str, Any] = {
        "final_url": "https://example.com/post",
        "redirect_chain": (),
        "status_code": None,
        "error_kind": ErrorKind.TIMEOUT,
        "body_sha256": None,
        "headers": (),
    }
    fields.update(overrides)
    return receipt(**fields)


def snapshot(**overrides: object) -> Snapshot:
    """Build a valid snapshot, with optional field overrides."""
    fields: dict[str, Any] = {
        "receipt_id": "r-001",
        "extractor_id": "dev.article",
        "extractor_version": "1",
        "content_sha256": "c" * 64,
        "head_sha256": "d" * 64,
        "frame_sha256": "e" * 64,
    }
    fields.update(overrides)
    return Snapshot(**fields)


# OBSERVED


def test_observed_with_evidence_is_valid() -> None:
    """An OBSERVED finding with one piece of evidence constructs."""
    assert observed().evidence == (EVIDENCE,)


def test_observed_without_evidence_is_rejected() -> None:
    """An OBSERVED finding must carry at least one Evidence."""
    with pytest.raises(ModelError, match="at least one Evidence"):
        observed(evidence=())


def test_observed_may_set_defect() -> None:
    """Only an OBSERVED finding may be a defect."""
    assert observed(defect=True).defect is True


@pytest.mark.parametrize("build", [recommendation, not_determinable])
def test_non_observed_defect_is_rejected(build: Callable[..., Finding]) -> None:
    """RECOMMENDATION and NOT_DETERMINABLE findings may not set defect."""
    with pytest.raises(ModelError, match="only an OBSERVED finding may set defect"):
        build(defect=True)


def test_absence_is_evidence() -> None:
    """Evidence may record what was searched for and not found."""
    absent = Evidence(receipt_id="r-001", location="head", searched_for='link[rel="canonical"]')
    assert observed(evidence=(absent,)).evidence[0].observed is None


def test_empty_observed_value_is_still_an_observation() -> None:
    """An empty attribute value is an observed value, not an absence."""
    empty = Evidence(receipt_id="r-001", location="meta[name=description]@content", observed="")
    assert empty.observed == ""


def test_evidence_without_observed_or_searched_for_is_rejected() -> None:
    """Evidence must say what was found or what was searched for."""
    with pytest.raises(ModelError, match="observed value or what was searched for"):
        Evidence(receipt_id="r-001", location="head")


@pytest.mark.parametrize(
    ("field", "value"),
    [("receipt_id", ""), ("location", "  "), ("searched_for", "")],
)
def test_evidence_blank_fields_are_rejected(field: str, value: str) -> None:
    """Evidence identifiers and search terms may not be blank."""
    fields: dict[str, Any] = {"receipt_id": "r-001", "location": "head", "searched_for": "x"}
    fields[field] = value
    with pytest.raises(ModelError, match=field):
        Evidence(**fields)


# RECOMMENDATION


def test_recommendation_with_based_on_and_rationale_is_valid() -> None:
    """A RECOMMENDATION with based_on and a rationale constructs."""
    assert recommendation().based_on == ("f-001",)


def test_recommendation_without_based_on_is_rejected() -> None:
    """A RECOMMENDATION must reference at least one finding."""
    with pytest.raises(ModelError, match="non-empty based_on"):
        recommendation(based_on=())


def test_recommendation_with_blank_based_on_id_is_rejected() -> None:
    """Every based_on reference must be a non-blank finding id."""
    with pytest.raises(ModelError, match="based_on"):
        recommendation(based_on=("f-001", " "))


def test_recommendation_based_on_itself_is_rejected() -> None:
    """A RECOMMENDATION cannot be based on itself."""
    with pytest.raises(ModelError, match="itself"):
        recommendation(based_on=("f-002",))


@pytest.mark.parametrize("rationale", [None, "", "   "])
def test_recommendation_without_rationale_is_rejected(rationale: str | None) -> None:
    """A RECOMMENDATION must carry a non-blank rationale."""
    with pytest.raises(ModelError, match="rationale"):
        recommendation(rationale=rationale)


# NOT_DETERMINABLE


def test_not_determinable_with_reason_question_and_attempt_is_valid() -> None:
    """A NOT_DETERMINABLE finding with a reason code, question, and attempt constructs."""
    assert not_determinable().reason_code is ReasonCode.ACCESS_DENIED


def test_not_determinable_without_reason_code_is_rejected() -> None:
    """A NOT_DETERMINABLE finding must carry a reason code."""
    with pytest.raises(ModelError, match="reason_code"):
        not_determinable(reason_code=None)


@pytest.mark.parametrize("question", [None, "", "  "])
def test_not_determinable_without_question_is_rejected(question: str | None) -> None:
    """A NOT_DETERMINABLE finding must state the question it cannot answer."""
    with pytest.raises(ModelError, match="question"):
        not_determinable(question=question)


def test_no_attempt_reasons_are_external_data_and_platform_opaque() -> None:
    """Exactly two reason codes describe questions no attempt could answer."""
    assert {ReasonCode.REQUIRES_EXTERNAL_DATA, ReasonCode.PLATFORM_OPAQUE} == NO_ATTEMPT_REASONS


@pytest.mark.parametrize("code", ATTEMPT_REASONS)
def test_attempt_reason_with_evidence_is_valid(code: ReasonCode) -> None:
    """An attempt-based reason code is valid with evidence of the attempt."""
    assert not_determinable(reason_code=code).evidence == (ATTEMPT,)


@pytest.mark.parametrize("code", ATTEMPT_REASONS)
def test_attempt_reason_without_evidence_is_rejected(code: ReasonCode) -> None:
    """An attempt-based reason code needs evidence of the attempt."""
    with pytest.raises(ModelError, match="evidence of the attempt"):
        not_determinable(reason_code=code, evidence=())


@pytest.mark.parametrize("code", ATTEMPT_REASONS)
def test_attempt_reason_with_would_require_is_rejected(code: ReasonCode) -> None:
    """would_require is for questions no attempt could answer."""
    with pytest.raises(ModelError, match="would_require"):
        not_determinable(reason_code=code, would_require="Citation logs from AI assistants.")


@pytest.mark.parametrize("code", sorted(NO_ATTEMPT_REASONS))
def test_no_attempt_reason_with_would_require_is_valid(code: ReasonCode) -> None:
    """A no-attempt reason code is valid with would_require and no evidence."""
    finding = not_determinable(
        reason_code=code, evidence=(), would_require="Citation logs from AI assistants."
    )
    assert finding.would_require == "Citation logs from AI assistants."


@pytest.mark.parametrize("code", sorted(NO_ATTEMPT_REASONS))
@pytest.mark.parametrize("would_require", [None, "", "  "])
def test_no_attempt_reason_without_would_require_is_rejected(
    code: ReasonCode, would_require: str | None
) -> None:
    """A no-attempt reason code must say what data would answer the question."""
    with pytest.raises(ModelError, match="would_require"):
        not_determinable(reason_code=code, evidence=(), would_require=would_require)


@pytest.mark.parametrize("code", sorted(NO_ATTEMPT_REASONS))
def test_no_attempt_reason_with_evidence_is_rejected(code: ReasonCode) -> None:
    """Where no attempt was possible, there is no attempt to give evidence of."""
    with pytest.raises(ModelError, match="no attempt"):
        not_determinable(reason_code=code, would_require="Citation logs.")


def test_reason_codes_match_design() -> None:
    """The reason codes are exactly those in DESIGN.md section 3."""
    assert {code.value for code in ReasonCode} == {
        "REQUIRES_EXTERNAL_DATA",
        "PLATFORM_OPAQUE",
        "FETCH_FAILED",
        "ACCESS_DENIED",
        "RATE_LIMITED",
        "DISALLOWED_BY_ROBOTS",
        "ADDRESS_REFUSED",
        "REQUIRES_RENDERING",
        "AMBIGUOUS",
    }


# Fields that belong to one status only


@pytest.mark.parametrize(
    ("build", "field", "value"),
    [
        (observed, "rationale", "Because."),
        (observed, "based_on", ("f-000",)),
        (observed, "reason_code", ReasonCode.AMBIGUOUS),
        (observed, "question", "Why?"),
        (recommendation, "reason_code", ReasonCode.AMBIGUOUS),
        (recommendation, "question", "Why?"),
        (not_determinable, "rationale", "Because."),
        (not_determinable, "based_on", ("f-001",)),
        (observed, "would_require", "Data."),
        (recommendation, "would_require", "Data."),
    ],
)
def test_fields_of_another_status_are_rejected(
    build: Callable[..., Finding], field: str, value: object
) -> None:
    """A finding may not carry fields that belong to a different status."""
    with pytest.raises(ModelError, match=field):
        build(**{field: value})


# Common fields


@pytest.mark.parametrize("field", ["id", "check_id", "check_version", "subject_url", "summary"])
def test_blank_common_fields_are_rejected(field: str) -> None:
    """Identifying fields and the summary may not be blank."""
    with pytest.raises(ModelError, match=field):
        observed(**{field: " "})


def test_status_must_be_a_status_member() -> None:
    """A plain string is not accepted where a Status is required."""
    with pytest.raises(ModelError, match="status"):
        observed(status="OBSERVED")


def test_actor_must_be_an_actor_member() -> None:
    """A plain string is not accepted where an Actor is required."""
    with pytest.raises(ModelError, match="actor"):
        observed(actor="AUTHOR")


def test_evidence_must_be_a_tuple_of_evidence() -> None:
    """Evidence is a tuple of Evidence so the finding stays immutable."""
    with pytest.raises(ModelError, match="evidence"):
        observed(evidence=[EVIDENCE])
    with pytest.raises(ModelError, match="evidence"):
        observed(evidence=("not evidence",))


@pytest.mark.parametrize("value", ["no", 1, None])
def test_defect_must_be_a_bool(value: object) -> None:
    """The defect flag is a bool, so a truthy string cannot mark a defect."""
    with pytest.raises(ModelError, match="defect"):
        observed(defect=value)


# Target and key


def test_target_defaults_to_empty() -> None:
    """A check that covers one thing leaves target empty."""
    assert observed().target == ""


@pytest.mark.parametrize("target", ["  ", 3])
def test_target_must_be_empty_or_non_blank_text(target: object) -> None:
    """The target is a string: empty, or with non-whitespace content."""
    with pytest.raises(ModelError, match="target"):
        observed(target=target)


def test_key_is_pinned_hash_of_check_url_and_target() -> None:
    """The key computation is final (Session 4a); these values are pinned.

    They must not change before Phase 5 without an ADR, because every stored
    key would stop matching.

    Session 4a changed the first value on purpose: the subject URL's trailing
    slash is now normalized away, so the old placeholder key no longer applies.
    """
    finding = observed(check_id="peri.og.core", target="og:image")
    assert finding.key == "c23399e38d29eaa08d08525900de85a98fe5f334d1d15ec5bc0752309a5473f9"
    link = observed(check_id="epi.links.resolve", target="https://Example.org/paper/#s2")
    assert link.key == "a2c4b236490548ccd653dc8db27190623f70c2920b1d8a3fb34327e0823e9502"


def test_key_payload_is_check_normalized_url_and_target() -> None:
    """The key is the SHA-256 of a compact JSON array, spelled out here."""
    payload = '["peri.og.core","https://example.com/post","og:image"]'
    assert finding_key("peri.og.core", "https://example.com/post/", "og:image") == (
        hashlib.sha256(payload.encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://example.com/post/", "https://EXAMPLE.com:443/post#top"),
        ("https://b\u00fccher.de/caf\u00e9", "https://xn--bcher-kva.de/caf%C3%A9"),
        ("https://example.com/cafe\u0301", "https://example.com/caf\u00e9"),
    ],
)
def test_equivalent_subject_urls_share_a_key(a: str, b: str) -> None:
    """Subject URLs go through the shared URL normalization."""
    assert observed(subject_url=a).key == observed(subject_url=b).key


def test_a_different_query_is_a_different_key() -> None:
    """Query strings are compared exactly, in keys as in URL comparison."""
    assert observed(subject_url="https://example.com/post?a=1").key != observed().key


def test_url_targets_are_normalized() -> None:
    """A target that is a URL goes through the same normalization as the subject."""
    a = observed(check_id="epi.links.resolve", target="https://Example.org/paper/#s2")
    b = observed(check_id="epi.links.resolve", target="https://example.org/paper")
    assert a.key == b.key


def test_other_targets_are_only_nfc_normalized() -> None:
    """A vocabulary target is not treated as a URL, but is still NFC."""
    assert finding_key("c", "https://example.com/", "og:image") != finding_key(
        "c", "https://example.com/", "og:Image"
    )
    assert finding_key("c", "https://example.com/", "caf\u00e9") == finding_key(
        "c", "https://example.com/", "cafe\u0301"
    )


def test_check_ids_are_nfc_normalized() -> None:
    """Every string in the key is NFC, the check id included."""
    assert finding_key("caf\u00e9", "https://example.com/", "") == finding_key(
        "cafe\u0301", "https://example.com/", ""
    )


def test_key_ignores_version_status_and_run_fields() -> None:
    """The key leaves out check_version, so a version change shows as a CHECKER change."""
    base = observed(check_id="epi.links.resolve", target="https://example.org/paper")
    others = [
        observed(check_id="epi.links.resolve", target="https://example.org/paper", **change)
        for change in (
            {"check_version": "2"},
            {"id": "f-999"},
            {"summary": "Different words."},
            {"defect": True},
            {"actor": Actor.PLATFORM},
        )
    ]
    others.append(not_determinable(check_id="epi.links.resolve"))
    assert {finding.key for finding in others} == {base.key}


@pytest.mark.parametrize(
    "change",
    [
        {"check_id": "peri.canonical.single"},
        {"subject_url": "https://example.com/other/"},
        {"target": "og:image"},
    ],
)
def test_key_changes_with_check_url_or_target(change: dict[str, str]) -> None:
    """A different check, subject, or target is a different finding."""
    assert observed(**change).key != observed().key


def test_key_uses_the_shared_url_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """finding_key calls cernis.urls.normalize_url, not a copy of it."""
    monkeypatch.setattr(urls, "normalize_url", lambda url: "same")
    assert observed(subject_url="https://a.example/").key == observed(subject_url="x").key


def test_key_cannot_be_passed_in() -> None:
    """The key is derived, never supplied."""
    with pytest.raises(TypeError):
        observed(key="0" * 64)


def test_replace_recomputes_key() -> None:
    """dataclasses.replace derives a fresh key for the new fields."""
    finding = observed()
    moved = dataclasses.replace(finding, target="og:url")
    assert moved.key == observed(target="og:url").key != finding.key


def test_findings_are_frozen() -> None:
    """Findings cannot be changed after construction."""
    finding = observed()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.defect = True  # type: ignore[misc]


# Receipt


def test_valid_receipt_constructs() -> None:
    """A receipt with all required fields constructs."""
    assert receipt().status_code == 200


@pytest.mark.parametrize(
    "kind", sorted(set(ErrorKind) - {ErrorKind.NONE, ErrorKind.TOO_MANY_REDIRECTS})
)
def test_receipt_without_response_is_valid(kind: ErrorKind) -> None:
    """A failed request records why and the URL that failed, with no status or hash."""
    built = no_response(error_kind=kind)
    assert (built.status_code, built.body_sha256) == (None, None)
    assert built.final_url == "https://example.com/post"


@pytest.mark.parametrize(
    "kind", sorted(set(ErrorKind) - {ErrorKind.NONE, ErrorKind.TOO_MANY_REDIRECTS})
)
def test_receipt_failed_request_must_name_the_url_that_failed(kind: ErrorKind) -> None:
    """ADR-004: a timeout, connection, or TLS failure names the URL whose request failed."""
    with pytest.raises(ModelError, match="final_url"):
        no_response(error_kind=kind, final_url=None)


@pytest.mark.parametrize("kind", [ErrorKind.TIMEOUT, ErrorKind.CONNECTION, ErrorKind.TLS])
def test_receipt_keeps_a_response_whose_body_failed(kind: ErrorKind) -> None:
    """ADR-004: a status and headers that arrived before the body failed are kept."""
    built = no_response(error_kind=kind, status_code=200, headers=(("content-type", "text/html"),))
    assert (built.status_code, built.header("content-type")) == (200, "text/html")


def test_receipt_partial_response_has_no_body_hash() -> None:
    """A body that failed to arrive whole has no hash."""
    with pytest.raises(ModelError, match="body_sha256"):
        no_response(status_code=200, body_sha256="a" * 64)


def test_receipt_headers_need_a_status() -> None:
    """Headers come with a status line; without one there are none to record."""
    with pytest.raises(ModelError, match="headers"):
        no_response(headers=(("content-type", "text/html"),))


def test_receipt_too_many_redirects_keeps_its_chain() -> None:
    """A redirect loop has no final response but records the chain it followed."""
    chain = ("https://example.com/post", "https://example.com/post/")
    built = no_response(
        error_kind=ErrorKind.TOO_MANY_REDIRECTS, redirect_chain=chain, final_url=None
    )
    assert built.redirect_chain == chain


def test_receipt_too_many_redirects_without_chain_is_rejected() -> None:
    """Too many redirects means at least one redirect was followed."""
    with pytest.raises(ModelError, match="redirect_chain"):
        no_response(error_kind=ErrorKind.TOO_MANY_REDIRECTS, final_url=None)


def test_receipt_error_kind_none_requires_status_code() -> None:
    """The error_kind NONE means a response arrived, so it needs a status code."""
    with pytest.raises(ModelError, match="error_kind"):
        no_response(error_kind=ErrorKind.NONE)


def test_receipt_too_many_redirects_with_status_code_is_rejected() -> None:
    """TOO_MANY_REDIRECTS has no final response, so no status code."""
    with pytest.raises(ModelError, match="error_kind"):
        receipt(error_kind=ErrorKind.TOO_MANY_REDIRECTS, body_sha256=None, headers=())


def test_receipt_error_kind_must_be_an_error_kind_member() -> None:
    """A plain string is not accepted where an ErrorKind is required."""
    with pytest.raises(ModelError, match="error_kind"):
        receipt(error_kind="NONE")


def test_receipt_body_hash_without_response_is_rejected() -> None:
    """A body hash requires a response."""
    with pytest.raises(ModelError, match="body_sha256"):
        no_response(body_sha256="a" * 64)


def test_receipt_body_truncated_at_defaults_to_none() -> None:
    """A receipt records a body cut off at the limit only when it happened."""
    assert receipt().body_truncated_at is None


def test_receipt_oversized_body_records_the_limit_and_no_hash() -> None:
    """A body cut off at the size limit has no hash, and the receipt names the limit."""
    built = receipt(body_sha256=None, body_truncated_at=5 * 1024 * 1024)
    assert (built.body_sha256, built.body_truncated_at) == (None, 5 * 1024 * 1024)


def test_receipt_oversized_body_with_a_hash_is_rejected() -> None:
    """A hash of part of a body would claim to be the hash of the body."""
    with pytest.raises(ModelError, match="body_sha256"):
        receipt(body_truncated_at=100)


def test_receipt_oversized_body_without_response_is_rejected() -> None:
    """A body can only be cut off if a response arrived."""
    with pytest.raises(ModelError, match="body_truncated_at"):
        no_response(body_truncated_at=100)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "100"])
def test_receipt_body_truncated_at_must_be_a_positive_int(value: object) -> None:
    """The recorded limit is a positive number of bytes."""
    with pytest.raises(ModelError, match="body_truncated_at"):
        receipt(body_sha256=None, body_truncated_at=value)


def test_receipt_too_many_redirects_with_final_url_is_rejected() -> None:
    """Too many redirects has no final response, so there is no final URL."""
    chain = ("https://example.com/post",)
    with pytest.raises(ModelError, match="final_url"):
        no_response(error_kind=ErrorKind.TOO_MANY_REDIRECTS, redirect_chain=chain)


def test_receipt_response_without_final_url_is_rejected() -> None:
    """A response always has a final URL."""
    with pytest.raises(ModelError, match="final_url"):
        receipt(final_url=None)


def test_error_kinds_match_design() -> None:
    """The error kinds are those in DESIGN.md section 3, plus ADDRESS_REFUSED (ADR-005)."""
    assert {kind.value for kind in ErrorKind} == {
        "NONE",
        "TIMEOUT",
        "CONNECTION",
        "TLS",
        "TOO_MANY_REDIRECTS",
        "ADDRESS_REFUSED",
    }


def test_receipt_address_refused_names_the_url_and_has_no_status() -> None:
    """ADR-005: a refused address was never contacted, so there is no status or header."""
    built = no_response(error_kind=ErrorKind.ADDRESS_REFUSED)
    assert (built.final_url, built.status_code, built.headers) == (
        "https://example.com/post",
        None,
        (),
    )


def test_receipt_address_refused_with_a_status_is_rejected() -> None:
    """Nothing was sent to a refused address, so nothing can have answered."""
    with pytest.raises(ModelError, match="error_kind"):
        no_response(error_kind=ErrorKind.ADDRESS_REFUSED, status_code=200)


@pytest.mark.parametrize("code", [99, 600])
def test_receipt_status_code_out_of_range_is_rejected(code: int) -> None:
    """HTTP status codes must be in the range 100 to 599."""
    with pytest.raises(ModelError, match="status_code"):
        receipt(status_code=code)


@pytest.mark.parametrize("digest", ["a" * 63, "A" * 64, "g" * 64])
def test_receipt_malformed_body_hash_is_rejected(digest: str) -> None:
    """The body hash must be 64 lowercase hexadecimal characters."""
    with pytest.raises(ModelError, match="body_sha256"):
        receipt(body_sha256=digest)


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 10, 28, 18, 0),
        datetime(2026, 10, 28, 18, 0, tzinfo=timezone(timedelta(hours=-7))),
    ],
)
def test_receipt_fetched_at_must_be_utc(moment: datetime) -> None:
    """fetched_at must be timezone-aware and in UTC."""
    with pytest.raises(ModelError, match="fetched_at"):
        receipt(fetched_at=moment)


@pytest.mark.parametrize(("field", "value"), [("fetched_at", "2026-10-28"), ("status_code", True)])
def test_receipt_wrong_types_raise_model_error(field: str, value: object) -> None:
    """A wrongly typed field raises ModelError, not an unrelated exception."""
    with pytest.raises(ModelError, match=field):
        receipt(**{field: value})


def test_receipt_header_outside_fixed_subset_is_rejected() -> None:
    """Receipts record only the fixed header subset."""
    with pytest.raises(ModelError, match="set-cookie"):
        receipt(headers=(("set-cookie", "session=1"),))


def test_receipt_records_retry_after() -> None:
    """The retry-after header is in the recorded subset, for 429 and 503 responses."""
    built = receipt(status_code=429, headers=(("retry-after", "120"),))
    assert built.header("retry-after") == "120"


def test_receipt_duplicate_header_is_rejected() -> None:
    """Each recorded header appears at most once."""
    with pytest.raises(ModelError, match="etag"):
        receipt(headers=(("etag", '"a"'), ("etag", '"b"')))


@pytest.mark.parametrize("headers", [{"etag": '"a"'}, (("etag",),), (("etag", 1),)])
def test_receipt_headers_must_be_name_value_pairs(headers: object) -> None:
    """Headers are a tuple of (name, value) string pairs."""
    with pytest.raises(ModelError, match="headers"):
        receipt(headers=headers)


def test_receipt_headers_are_sorted_and_looked_up_by_name() -> None:
    """Header order does not affect equality, and lookup is by name."""
    first = receipt(headers=(("etag", '"a"'), ("content-type", "text/html")))
    second = receipt(headers=(("content-type", "text/html"), ("etag", '"a"')))
    assert first == second
    assert hash(first) == hash(second)
    assert first.header("etag") == '"a"'
    assert first.header("last-modified") is None


def test_model_objects_support_asdict_copy_and_pickle() -> None:
    """Reports and stores can serialize and copy every model object."""
    values = (
        receipt(),
        no_response(),
        observed(),
        recommendation(),
        not_determinable(),
        snapshot(),
    )
    for value in values:
        assert copy.deepcopy(value) == value
        assert pickle.loads(pickle.dumps(value)) == value
        assert dataclasses.asdict(value)


def test_receipt_redirect_chain_must_start_at_requested_url() -> None:
    """A redirect chain begins with the URL that was requested."""
    with pytest.raises(ModelError, match="redirect_chain"):
        receipt(redirect_chain=("https://elsewhere.example/",))


def test_receipt_without_redirects_ends_where_it_started() -> None:
    """With no redirects, final_url equals requested_url."""
    with pytest.raises(ModelError, match="final_url"):
        receipt(redirect_chain=())


# Snapshot


def test_valid_snapshot_constructs() -> None:
    """A snapshot with all three hashes constructs."""
    assert snapshot().extractor_id == "dev.article"


def test_snapshot_without_body_is_valid() -> None:
    """An extractor that finds no article body records content_sha256 as None."""
    assert snapshot(content_sha256=None).content_sha256 is None


@pytest.mark.parametrize("field", ["content_sha256", "head_sha256", "frame_sha256"])
@pytest.mark.parametrize("digest", ["c" * 63, "C" * 64])
def test_snapshot_malformed_hash_is_rejected(field: str, digest: str) -> None:
    """Snapshot hashes are 64 lowercase hexadecimal characters."""
    with pytest.raises(ModelError, match=field):
        snapshot(**{field: digest})


@pytest.mark.parametrize("field", ["head_sha256", "frame_sha256"])
def test_snapshot_head_and_frame_hashes_are_required(field: str) -> None:
    """Only content_sha256 may be missing."""
    with pytest.raises(ModelError, match=field):
        snapshot(**{field: None})


@pytest.mark.parametrize("field", ["receipt_id", "extractor_id", "extractor_version"])
def test_snapshot_blank_identifiers_are_rejected(field: str) -> None:
    """Snapshot identifiers may not be blank."""
    with pytest.raises(ModelError, match=field):
        snapshot(**{field: ""})


# ChangeClass


def test_change_classes_match_design() -> None:
    """The change classes are exactly those in DESIGN.md section 5."""
    assert {cls.value for cls in ChangeClass} == {
        "CHECKER",
        "AUTHOR_CONTENT",
        "AUTHOR_METADATA",
        "PLATFORM_RENDERING",
        "UNCLASSIFIED",
    }
