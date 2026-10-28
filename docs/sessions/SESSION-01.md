# Session 1: Foundation

**Date:** 2026-10-28
**Phase:** 1 (scaffold), DESIGN.md section 10
**Version:** 0.1.0.dev0 (not built, not published)

No fetching, no parsing, and no network access in this session.

## Built

- `CLAUDE.md`: purpose, conventions, the check list, the commit rule, the principles, and the credentials rule.
- `docs/adr/ADR-001-findings-carry-an-epistemic-status.md` and `docs/adr/ADR-002-storage-behind-a-receiptstore-protocol.md`.
- `src/cernis/model.py`: `Status`, `Actor`, `ReasonCode`, and `Family` enums; frozen `Evidence`, `Finding`, and `Receipt` dataclasses that validate at construction and raise `ModelError`.
- `src/cernis/promises.py`: the forbidden-outcome phrase list and `find_outcome_language`.
- `src/cernis/checks/recommendations.py`: `RecommendationTemplate` and `TEMPLATES`, holding one template (for `epi.pair.canonical`) so the no-promise test has something to scan.
- `src/cernis/checks/registry.py`: all 15 checks from DESIGN.md section 4, at version 1, none implemented.
- `cernis checks` and `cernis checks --format json`. `cernis --version` and the no-argument message still work; the message now mentions `cernis checks`.
- `tests/fixtures/README.md`, `docs/SDK-FRICTION.md`, and this file.
- Tests: 94, covering every status rule in its passing and failing case, the receipt rules, the no-promise checker and template scan, the registry, and the CLI.

## Decisions

1. **Evidence records a find or a search.** `Evidence` has `observed` and `searched_for`; at least one must be set. `observed=None` with `searched_for` set is absence evidence (principle 5). An empty string in `observed` is an observation (an empty attribute), not an absence.
2. **Status-specific fields are rejected on other statuses.** DESIGN.md marks `rationale` and `based_on` "RECOMMENDATION only" and `reason_code` and `question` "NOT_DETERMINABLE only". The model treats "only" as a rule, not a hint.
3. **`based_on` is checked for presence, not for what it points at.** One finding cannot see the others, so "references an OBSERVED finding" is left to the code that assembles a run (ADR-001). A recommendation may not reference itself.
4. **NOT_DETERMINABLE does not require evidence.** DESIGN.md says it "must state what was searched," but the `REQUIRES_EXTERNAL_DATA` example has nothing to search. Evidence is allowed, not required.
5. **Receipts can record a fetch with no response.** `status_code` and `body_sha256` are `None` for a timeout or connection error, and a body hash without a status code is rejected. `fetched_at` must be timezone-aware UTC.
6. **Redirect chain meaning.** `redirect_chain` lists every URL that answered with a redirect, starting with `requested_url`, and is empty when there was no redirect (then `final_url` must equal `requested_url`).
7. **Headers are a sorted tuple of `(name, value)` pairs**, lowercase names from the fixed subset, each at most once, with `Receipt.header(name)` for lookup. A read-only mapping was tried first; it broke `dataclasses.asdict`, `copy.deepcopy`, and `pickle`, which reports and the store will need.
8. **The no-promise list** is every predictive modal (will, would, should, could, may, might) followed by an outcome verb, plus fixed phrases ("boost," "rank higher," "more traffic," "more citations," and others). Matching ignores case, accepts any word ending, allows up to two words in between ("will very likely improve"), and reads "'ll" as "will." It is a floor, not a proof.
9. **The rule applies to templates, not filled-in text.** A recommendation may quote page content, and a page may say anything.
10. **All templates live in `cernis.checks.recommendations.TEMPLATES`.** The test walks the package and fails on a template defined anywhere else, so the scan cannot miss one.
11. **`cernis checks --format json`** prints `{"cernis_version": ..., "checks": [...]}` with the description included, so the output says which version's registry it lists. The table omits descriptions to stay narrow.
12. **Tooling.** pydoclint's class-attribute check is off, because dataclass fields are documented as `:param:` in the class docstring. Tests are typed and have docstrings (ruff ANN and D apply, and mypy strict covers `tests/`). The check list adds `uv run --isolated --python 3.12 pytest`, since the project venv runs Python 3.14 and the declared floor is 3.12.
13. **No `store/` code yet.** ADR-002 records the protocol decision; the protocol is written when something needs to store.

## Review

The audit-before-commit gate routed this change to a `standard` audit. The Decision Engine server failed to connect, so the review ran as a local single-model advisory (`local_host_85882e46fcd9df1601f6ba82`, no `audit_id`). It found and this session fixed: the read-only header mapping above; outcome language with an adverb in between slipping past the checker; `defect` accepting non-bool values; and wrongly typed `fetched_at` or `status_code` raising something other than `ModelError`. It is not a cross-vendor audit and does not close the gate. A real panel should rerun before release.

## Deferred

- Checking that `based_on` ids name `OBSERVED` findings in the same run (Phase 3, with run assembly).
- Showing `NOT_DETERMINABLE` as "Not determinable (*non liquet*)" (Phase 3, with reports).
- The `ReceiptStore` protocol and in-memory store (when storage is first needed).
- Synthetic HTML fixtures themselves (Phase 3, with the parser). Only the README exists.
- A repository text check for em-dashes, like Afterword's pre-commit hook. This session checked by hand.
- Phase 0's logo and BRAND.md.
