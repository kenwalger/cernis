"""Tests for claim C-4's mechanical evaluation (``cernis.evaluate.c4``).

Model validation refuses to build a finding that breaks C-4's rules, so the
synthetic runs here are stored records, written as the ledger holds them,
each breaking one rule.
"""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from test_cli_store import _tamper, audit_twice

from cernis import cli, promises
from cernis.cli import main
from cernis.evaluate import C4Error, C4Result, evaluate_c4, evaluate_findings
from cernis.evaluate import c4 as c4_module
from cernis.store import LedgerStore, StoredEntry

RUN = "20261117T120000Z-0a1b2c"


def observed(finding_id: str = "f-001", **fields: object) -> dict[str, object]:
    """Build a well-formed stored OBSERVED finding.

    :param finding_id: Its id.
    :param **fields: Fields to change or add.
    :return: The record.
    """
    record: dict[str, object] = {
        "id": finding_id,
        "key": f"key-{finding_id}",
        "check_id": "peri.lang",
        "check_version": "3",
        "status": "OBSERVED",
        "actor": "AUTHOR",
        "defect": True,
        "subject_url": "https://blog.example.com/a-post/",
        "target": "",
        "summary": "The <html> element has no lang attribute.",
        "evidence": [
            {"receipt_id": "r-001", "location": "html", "observed": None, "searched_for": "lang"}
        ],
        "rationale": None,
        "based_on": [],
        "reason_code": None,
        "question": None,
        "would_require": None,
    }
    record.update(fields)
    return record


def recommendation(finding_id: str = "f-002", **fields: object) -> dict[str, object]:
    """Build a well-formed stored RECOMMENDATION resting on ``f-001``.

    :param finding_id: Its id.
    :param **fields: Fields to change or add.
    :return: The record.
    """
    record = observed(
        finding_id,
        status="RECOMMENDATION",
        defect=False,
        evidence=[],
        summary='Add a lang attribute to the <html> element, such as lang="en".',
        rationale="WCAG 2 success criterion 3.1.1 requires the page's language.",
        based_on=["f-001"],
    )
    record.update(fields)
    return record


def unanswered(finding_id: str = "f-003", **fields: object) -> dict[str, object]:
    """Build a well-formed stored NOT_DETERMINABLE with evidence of an attempt.

    :param finding_id: Its id.
    :param **fields: Fields to change or add.
    :return: The record.
    """
    record = observed(
        finding_id,
        check_id="epi.links.resolve",
        status="NOT_DETERMINABLE",
        actor="AUTHOR",
        defect=False,
        summary="Whether https://example.org/x resolves cannot be determined.",
        evidence=[
            {
                "receipt_id": "r-004",
                "location": "HTTP status",
                "observed": "403",
                "searched_for": None,
            }
        ],
        reason_code="ACCESS_DENIED",
        question="Does https://example.org/x resolve?",
    )
    record.update(fields)
    return record


def stored(*records: Mapping[str, object], run_id: str = RUN) -> list[StoredEntry]:
    """Store records as one complete run's entries, the run record last.

    :param *records: The finding records.
    :param run_id: The run id.
    :return: The entries.
    """
    entries = [
        StoredEntry(
            sequence=n,
            kind="finding",
            run_id=run_id,
            record=record,
            schema_version=1,
            idempotency_key=f"cernis/{run_id}/finding/{record['id']}",
        )
        for n, record in enumerate(records, start=1)
    ]
    entries.append(
        StoredEntry(
            sequence=len(records) + 1,
            kind="run",
            run_id=run_id,
            record={"id": run_id},
            schema_version=1,
            idempotency_key=f"cernis/{run_id}/run/run",
        )
    )
    return entries


def violations(result: C4Result, rule: str) -> list[tuple[str, str, str]]:
    """List one rule's violations as (finding id, key, detail).

    :param result: The result.
    :param rule: The rule's name.
    :return: The violations.
    """
    (found,) = [r for r in result.rules if r.rule == rule]
    return [(v.finding_id, v.key, v.detail) for v in found.violations]


def test_a_well_formed_run_holds_on_every_rule() -> None:
    """One finding of each status, each correct: no violations, and counts per rule."""
    result = evaluate_findings(RUN, [observed(), recommendation(), unanswered()])

    assert result.held
    assert {r.rule: r.checked for r in result.rules} == {
        "based_on": 1,
        "no_promise": 1,
        "not_determinable": 1,
        "status_fields": 3,
    }
    assert result.counts == {"NOT_DETERMINABLE": 1, "OBSERVED": 1, "RECOMMENDATION": 1}


def test_a_would_require_answers_for_a_question_never_attempted() -> None:
    """No evidence is fine when ``would_require`` says what would answer it."""
    record = unanswered(
        evidence=[], reason_code="REQUIRES_EXTERNAL_DATA", would_require="AI assistants' logs"
    )

    assert evaluate_findings(RUN, [record]).held


# Rule 1: based_on


@pytest.mark.parametrize(
    ("based_on", "detail"),
    [
        ([], "based_on is empty or missing."),
        (["f-404"], "based_on names f-404, not in this run."),
        (["f-003"], "based_on names f-003, which is NOT_DETERMINABLE, not OBSERVED."),
        (["f-002"], "based_on names f-002, which is RECOMMENDATION, not OBSERVED."),
    ],
)
def test_a_recommendation_must_rest_on_observed_findings_of_its_run(
    based_on: list[str], detail: str
) -> None:
    """Empty, dangling, or resting on another status: each is a violation, by id and key."""
    result = evaluate_findings(RUN, [observed(), recommendation(based_on=based_on), unanswered()])

    assert violations(result, "based_on") == [("f-002", "key-f-002", detail)]
    assert not result.held


def test_based_on_missing_entirely_is_a_violation() -> None:
    """A record with no based_on field at all is caught, not skipped."""
    record = recommendation()
    del record["based_on"]

    assert violations(evaluate_findings(RUN, [observed(), record]), "based_on") == [
        ("f-002", "key-f-002", "based_on is empty or missing.")
    ]


@pytest.mark.parametrize(
    ("records", "detail"),
    [
        (
            [observed("123"), recommendation(based_on=[123])],
            "based_on names 123, which is not a finding id (not text).",
        ),
        (
            [observed(), recommendation(based_on="f-001")],
            "based_on is not a list.",
        ),
        (
            [observed(), observed("f-001"), recommendation()],
            "based_on names f-001, which more than one finding in this run has.",
        ),
        (
            [observed(""), recommendation(based_on=[""])],
            "based_on names an empty id.",
        ),
    ],
    ids=["number", "not-a-list", "duplicate-id", "empty-id"],
)
def test_malformed_based_on_is_named_for_what_it_is(
    records: list[dict[str, object]], detail: str
) -> None:
    """A stored reference of the wrong type, or to an ambiguous id, never resolves."""
    assert (
        "f-002",
        "key-f-002",
        detail,
    ) in violations(evaluate_findings(RUN, records), "based_on")


def test_based_on_never_reaches_into_another_run() -> None:
    """An id that exists only in another run's findings dangles in this one."""
    entries = stored(recommendation()) + stored(observed(), run_id="20261117T130000Z-ffffff")

    result = evaluate_c4(entries, RUN)

    assert violations(result, "based_on") == [
        ("f-002", "key-f-002", "based_on names f-001, not in this run.")
    ]


# Rule 2: no promise


@pytest.mark.parametrize("field", ["summary", "rationale"])
def test_recommendation_text_must_pass_the_no_promise_test(field: str) -> None:
    """Outcome language in the action or the rationale is a violation."""
    record = recommendation(**{field: "Add a lang attribute; it will improve rankings."})

    assert violations(evaluate_findings(RUN, [observed(), record]), "no_promise") == [
        ("f-002", "key-f-002", f'its {field} contains "will improve".')
    ]


@pytest.mark.parametrize("field", ["summary", "rationale"])
def test_recommendation_text_that_is_not_text_cannot_pass(field: str) -> None:
    """A corrupted summary or rationale is reported, never skipped as empty."""
    record = recommendation()
    record[field] = ["will improve rankings"]

    assert violations(evaluate_findings(RUN, [observed(), record]), "no_promise") == [
        ("f-002", "key-f-002", f"its {field} is not text, so it cannot be checked.")
    ]


def test_the_no_promise_patterns_are_the_test_suites_own() -> None:
    """Imported from cernis.promises, never copied."""
    assert vars(c4_module)["find_outcome_language"] is promises.find_outcome_language


# Rule 3: not determinable


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"reason_code": None}, "reason_code is missing."),
        ({"question": ""}, "question is missing."),
        (
            {"evidence": [], "would_require": None},
            "it has neither evidence of an attempt nor would_require.",
        ),
        (
            {"evidence": [{}], "would_require": None},
            "it has neither evidence of an attempt nor would_require.",
        ),
        (
            {"evidence": [{"receipt_id": "", "location": "HTTP status"}], "would_require": None},
            "it has neither evidence of an attempt nor would_require.",
        ),
    ],
    ids=["no-reason", "no-question", "nothing", "empty-entry", "no-receipt"],
)
def test_an_unanswered_question_says_why_what_and_what_was_tried(
    change: dict[str, object], detail: str
) -> None:
    """A reason code, a question, and evidence or would_require: each missing one is caught."""
    record = unanswered()
    record.update(change)
    result = evaluate_findings(RUN, [record])

    assert violations(result, "not_determinable") == [("f-003", "key-f-003", detail)]


# Rule 4: fields of another status


@pytest.mark.parametrize(
    ("record", "detail"),
    [
        (
            observed(rationale="Because."),
            "a OBSERVED finding carries rationale, which belongs to RECOMMENDATION.",
        ),
        (
            observed(reason_code="AMBIGUOUS"),
            "a OBSERVED finding carries reason_code, which belongs to NOT_DETERMINABLE.",
        ),
        (
            observed(based_on=["f-009"]),
            "a OBSERVED finding carries based_on, which belongs to RECOMMENDATION.",
        ),
        (
            recommendation("f-001", based_on=["f-009"], defect=True),
            "a RECOMMENDATION finding carries defect, which belongs to OBSERVED.",
        ),
        (
            recommendation("f-001", based_on=["f-009"], question="Why?"),
            "a RECOMMENDATION finding carries question, which belongs to NOT_DETERMINABLE.",
        ),
        (
            unanswered("f-001", rationale="Because."),
            "a NOT_DETERMINABLE finding carries rationale, which belongs to RECOMMENDATION.",
        ),
        (
            unanswered("f-001", defect=True),
            "a NOT_DETERMINABLE finding carries defect, which belongs to OBSERVED.",
        ),
        (observed(status="GUESSED"), "its status 'GUESSED' is not one of three."),
        (
            recommendation("f-001", based_on=["f-009"], defect=0),
            "a RECOMMENDATION finding carries defect, which belongs to OBSERVED.",
        ),
    ],
)
def test_no_finding_carries_a_field_of_another_status(
    record: dict[str, object], detail: str
) -> None:
    """Each cross-status field is a violation, and so is a status outside the three."""
    result = evaluate_findings(RUN, [record])

    assert violations(result, "status_fields") == [("f-001", "key-f-001", detail)]


def test_every_violation_is_reported_not_only_the_first() -> None:
    """Three broken findings, four rules: all four violations are listed."""
    result = evaluate_findings(
        RUN,
        [
            observed(rationale="Because."),
            recommendation(based_on=[], summary="It will boost traffic."),
            unanswered(question=None),
        ],
    )

    assert [(r.rule, len(r.violations)) for r in result.rules] == [
        ("based_on", 1),
        ("no_promise", 1),
        ("not_determinable", 1),
        ("status_fields", 1),
    ]


# Reading the run from the store


def test_a_run_without_its_run_record_is_not_evaluated() -> None:
    """A write that stopped partway is ignored by readers, and by C-4."""
    entries = stored(observed())[:-1]

    with pytest.raises(C4Error, match=RUN):
        evaluate_c4(entries, RUN)


def test_a_real_recorded_run_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run Cernis recorded, read back verified, passes every rule."""
    first, _ = audit_twice(monkeypatch, tmp_path, capsys)

    result = evaluate_c4(LedgerStore(tmp_path / "store").entries(), first)

    assert result.held
    assert sum(result.counts.values()) > 0


# cernis evaluate c4


def test_the_command_reports_each_rule_and_exits_0_when_c4_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Markdown and JSON, counts per rule, from the store."""
    first, _ = audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")

    assert main(["evaluate", "c4", "--run", first, "--store", store]) == 0
    markdown = capsys.readouterr().out
    assert main(["evaluate", "c4", "--run", first, "--store", store, "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert "Every rule held: no violations." in markdown
    assert payload["held"] is True
    assert payload["run"] == first
    assert [rule["rule"] for rule in payload["rules"]] == [
        "based_on",
        "no_promise",
        "not_determinable",
        "status_fields",
    ]


def test_the_command_lists_each_violation_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every violation by finding id and key."""
    entries = stored(observed(), recommendation(based_on=["f-404"]))
    monkeypatch.setattr(cli, "_read_store", lambda command, store: entries)

    code = main(["evaluate", "c4", "--run", RUN, "--store", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1
    assert "based_on names f-404, not in this run." in out
    assert "`f-002`" in out
    assert "`key-f-002`" in out


def test_a_run_not_in_the_store_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A usage error: the run named is not a complete run in the store."""
    audit_twice(monkeypatch, tmp_path, capsys)

    code = main(
        ["evaluate", "c4", "--run", "20200101T000000Z-000000", "--store", str(tmp_path / "store")]
    )

    assert code == 2
    assert "no complete run 20200101T000000Z-000000" in capsys.readouterr().err


def test_evaluate_needs_a_claim_and_a_run() -> None:
    """``cernis evaluate`` alone, or ``c4`` without ``--run``, is a usage error."""
    for arguments in (["evaluate"], ["evaluate", "c4"]):
        with pytest.raises(SystemExit) as raised:
            main(arguments)
        assert raised.value.code == 2


def test_the_command_writes_to_a_file_with_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Held or not, --output takes the report and the exit code still says which."""
    first, _ = audit_twice(monkeypatch, tmp_path, capsys)
    store = str(tmp_path / "store")
    held = tmp_path / "held.md"

    assert main(["evaluate", "c4", "--run", first, "--store", store, "--output", str(held)]) == 0
    assert capsys.readouterr().out == ""
    assert "Every rule held: no violations." in held.read_text(encoding="utf-8")

    entries = stored(observed(), recommendation(based_on=["f-404"]))
    monkeypatch.setattr(cli, "_read_store", lambda command, store: entries)
    broken = tmp_path / "broken.json"
    arguments = ["evaluate", "c4", "--run", RUN, "--store", store, "--format", "json"]
    code = main([*arguments, "--output", str(broken)])

    assert code == 1
    assert capsys.readouterr().out == ""
    payload = json.loads(broken.read_text(encoding="utf-8"))
    assert payload["held"] is False
    (rule,) = [r for r in payload["rules"] if r["rule"] == "based_on"]
    assert rule["violations"] == [
        {
            "rule": "based_on",
            "finding_id": "f-002",
            "key": "key-f-002",
            "check_id": "peri.lang",
            "detail": "based_on names f-404, not in this run.",
        }
    ]


def test_an_unwritable_output_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The output file's failure is a usage error, as for every other command."""
    first, _ = audit_twice(monkeypatch, tmp_path, capsys)
    missing = tmp_path / "no-such-directory" / "c4.md"

    arguments = ["evaluate", "c4", "--run", first, "--store", str(tmp_path / "store")]
    code = main([*arguments, "--output", str(missing)])

    assert code == 2
    assert "cannot write" in capsys.readouterr().err


def test_a_store_that_fails_verification_is_not_evaluated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Read with verification on: a tampered ledger exits 1, and nothing is evaluated."""
    first, _ = audit_twice(monkeypatch, tmp_path, capsys)
    _tamper(tmp_path)

    code = main(["evaluate", "c4", "--run", first, "--store", str(tmp_path / "store")])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "cernis evaluate c4:" in captured.err
