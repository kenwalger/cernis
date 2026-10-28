"""Tests for the finding and receipt model in :mod:`cernis.model`."""

import copy
import dataclasses
import pickle
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from cernis.model import (
    Actor,
    Evidence,
    Finding,
    ModelError,
    ReasonCode,
    Receipt,
    Status,
)

EVIDENCE = Evidence(
    receipt_id="r-001",
    location="head > link[rel=canonical]",
    observed="https://example.com/post/",
)


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
        "reason_code": ReasonCode.ACCESS_DENIED,
        "question": "Does https://example.org/paper resolve?",
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
        "fetched_at": datetime(2026, 10, 28, 18, 0, tzinfo=UTC),
        "body_sha256": "a" * 64,
        "headers": (("content-type", "text/html; charset=utf-8"),),
        "cernis_version": "0.1.0.dev0",
        "user_agent": "Cernis/0.1.0.dev0 (+https://github.com/kenwalger/cernis)",
    }
    fields.update(overrides)
    return Receipt(**fields)


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


def test_not_determinable_with_reason_and_question_is_valid() -> None:
    """A NOT_DETERMINABLE finding with a reason code and question constructs."""
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


def test_findings_are_frozen() -> None:
    """Findings cannot be changed after construction."""
    finding = observed()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.defect = True  # type: ignore[misc]


# Receipt


def test_valid_receipt_constructs() -> None:
    """A receipt with all required fields constructs."""
    assert receipt().status_code == 200


def test_receipt_without_response_is_valid() -> None:
    """A fetch that got no response records no status code and no body hash."""
    assert receipt(status_code=None, body_sha256=None).status_code is None


def test_receipt_body_hash_without_response_is_rejected() -> None:
    """A body hash requires a response."""
    with pytest.raises(ModelError, match="body_sha256"):
        receipt(status_code=None)


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
    for value in (receipt(), observed(), recommendation(), not_determinable()):
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
