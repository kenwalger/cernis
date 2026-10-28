# ADR-001: Findings carry an epistemic status

**Status:** Accepted
**Date:** 2026-10-28

## Context

Cernis's defining promise is to keep three things apart: what it saw, what it suggests, and what it cannot know (DESIGN.md principle 1). Audit tools usually blur them. A missing tag, a suggestion to add one, and a guess about search ranking all arrive in the same list with the same weight, and a 403 is reported as a broken link.

Who can act on a finding is a separate question from how sure Cernis is. The same robots.txt check concerns the platform on dev.to and the author on a self-hosted blog.

## Decision

Every `Finding` carries a `status`, one of:

- `OBSERVED`: a condition verified directly from fetched content. It must carry at least one `Evidence`, which records either what was found or exactly what was searched for and not found. Only an `OBSERVED` finding may set `defect`, and only for a violation of a published standard or the author's stated intent.
- `RECOMMENDATION`: a suggested change. It must carry a non-empty `based_on` (the ids of the findings it rests on) and a `rationale`. It must not predict an outcome.
- `NOT_DETERMINABLE`: a question Cernis cannot answer from what it can see. It must carry a `reason_code` and the `question`. Reports show it as "Not determinable (*non liquet*)."

Every finding also carries an `actor` (`AUTHOR`, `PLATFORM`, or `UNKNOWN`), independent of its status.

These rules are enforced when a finding is constructed (`src/cernis/model.py`). Fields that belong to one status are rejected on the others. A finding that breaks a rule raises `ModelError` and never exists.

## Consequences

- An invalid finding cannot reach a report or the store, so no later stage needs to re-check the rules.
- A single finding cannot check that its `based_on` ids name `OBSERVED` findings in the same run. That check belongs to the code that assembles a run's findings, and must be written when that code exists (Phase 3).
- The no-promise rule is enforced on recommendation templates by the test suite (`src/cernis/promises.py`), not on filled-in text, because values taken from a page may contain any words.
- There is no field for a score, and adding one would contradict this ADR.
- Adding a status or a reason code is a model change that every report format and the store must handle.

## Amendment 1 (2026-10-28, session 1b): what NOT_DETERMINABLE must record

DESIGN.md draft 2 makes the third status say how Cernis came to not know.

- A `NOT_DETERMINABLE` finding still needs a `reason_code` and a `question`.
- When Cernis attempted something (a fetch, a search of the page), it must carry evidence of the attempt. This applies to every reason code except the two below.
- When no attempt was possible (`REQUIRES_EXTERNAL_DATA`, `PLATFORM_OPAQUE`), it must instead state, in a non-blank `would_require`, what data would answer the question. It carries no evidence, since there was no attempt to give evidence of.
- `would_require` is rejected on the other statuses and on attempt-based codes.
- A new reason code, `RATE_LIMITED`, covers a 429 that is still refused after retrying with backoff. `ACCESS_DENIED` now covers 401 and 403 only.

Every finding also gains a derived `key`, stable across runs: the SHA-256 of the check id, the normalized subject URL, and the `target`, leaving out the check version. It is computed at construction and cannot be passed in.

Consequence: "what cannot be determined" becomes checkable. A reader can tell an unanswered question Cernis tried to answer from one it could never answer, and see what would answer the second kind.
