# CLAUDE.md

Rules for any session working in this repository.

## Authority

- `docs/` is the source of truth. Before changing anything, read `README.md`, then `docs/` and `docs/adr/`, then `fixtures/README.md`.
- Do not contradict an ADR. If a task seems to require it, stop and ask.
- When evidence changes a claim, append a dated entry to `docs/CLAIMS.md`. Never rewrite the original claim.
- Any change to the taxonomy version (`TAXONOMY.md`) or the labeling-guide version (`LABELING-GUIDE.md`) must also review `docs/LABELING-FIELD-GUIDE.md`, update it where it no longer matches, and bump its version.

## Current stage

**Stage 0 is done and Stage 3a decisions are made; preregistration (Stage 3b) is next.** Stage 1 to 3a groundwork (plan approved 2026-10-03, session 4) is built: normalization `norm-v0.1`, pre-check `pc-v0.1`, the priority policy, B1, the synthetic adversarial set, the SQLite store with ingest, lifecycle, purge, and saved-run redaction (ADR-009, ADR-013), the classifier wrapper with its cache, the Ollama and Anthropic providers, and the service functions and CLI commands over them (ADR-012).

- Stage 0: skeleton, read-only DEV probe, capability matrix, volume baseline (C-009), corpus targets (historical `dev`, prospective `test`; ADR-010 amended), timed chronological reviews, and the gate decision (2026-10-04: continue as planned, C-012 added). **`dev` labeling is complete:** 478 of 478 comments from others in run `20261018T173927Z` (2026-10-18), 150 in publication order and 328 shuffled (seed 20261004). Comments that arrive before preregistration also belong to `dev` and are labeled as they come. Analyses report publication-order and shuffled labels separately (`afterword.label_records.split_by_post_order`).
- **Stage 3a decisions (the author, 2026-10-18; `docs/EVALUATION.md` v17):**
  - B2 is Llama, `llama3.1:8b-instruct-q4_K_M` through Ollama, pinned digest, `pr-v0.2`, `num_ctx=4096`. B1 `hb-v0.2` is the baseline.
  - The applied policy is `pp-v0.2`: model-set `NEEDS_THREAD_CONTEXT` and `REFERENCES_SPECIFIC_CLAIM` are informational. `pp-v0.1` stays available for rescoring.
  - The class-based ceiling is accepted for V1; registered thresholds are set against the oracle under `pp-v0.2`. Class-default remaps are rejected; the extension split and a model consequence signal are V2 candidates (`docs/FUTURE-FEATURES.md`).
- **Self-agreement check done (2026-10-23; `docs/EVALUATION.md` v20):** 112 of 112 drawn (pool: labels at least 14 days old; every pooled comment graded 2 or 3 plus 25 at random, seed 20261018). Consequential split 80 of 112 (the first, rushed sitting 53 of 80; the second, unhurried one 27 of 32), class kappa 0.358. Decided the same day:
  - The labeling guide is `lg-v0.7` (named-consequence test for grade 2, reuse test for extension against conversational); `LABELING-FIELD-GUIDE.md` v5.
  - The calibration pass on the 150 publication-order labels under `lg-v0.7` was completed by the author on 2026-10-26. Analysis uses the latest non-self-agreement label per comment.
  - No second self-agreement cycle before preregistration; the C-011 relabel at the end of accrual is the long-term check.
- **`dev` recomputed (session 15, 2026-10-26; `docs/EVALUATION.md` v21):** 494 of 494 in run `20261026T181641Z`, 158 graded 2 or 3. The calibration moved the first 150 from 39 to 58 consequential.
- **Thresholds and frozen versions decided (the author, 2026-10-26; `docs/EVALUATION.md` v22, `docs/proposals/accepted/2026-10-26-registered-thresholds.md`):** relative to the oracle on the test set; application `0.2.0`. **Next: the preparation commit (author), then seal day in early November, by `docs/PREREGISTRATION.md` Step 5, in the author's terminal; Part 1 publishes 2026-11-10, after the seal** (`afterword preregistration write` writes `registry/preregistration.json`; then the corpus export, commit, tag `prereg-v1`, push). Part 1 is published after the seal and excluded by amendment before any of its comments is labeled.

Orientation checks open items at their source, not in earlier session summaries: count the valid timing records under `reports/timing/` (`afterword.timing.load_valid`, aggregates only) and the label records under `fixtures/labels/` (`afterword.label_records`, counts only). Never print record contents. A summary that lists an item as open can be out of date.

Model calls, local or remote, run only on synthetic data. No real comment data goes to any model until the author says so and the model-boundary record for that path is signed off; the author runs real model passes in their own terminal. Claude may ingest saved probe runs into the local store when a session prompt asks for it (from 2026-10-07). Claude never reads real comment text, and reports counts and aggregates only.

The seeded, class-balanced dev subset for model runs (session 8, Part C) is in scope.

Built in session 12 (2026-10-18), on synthetic fixtures only: `--set test` selection, shadow mode and sealing, the corpus export, and the self-agreement tools. Running them on real data is the author's, in their own terminal, by `docs/PREREGISTRATION.md`.

Still out of scope: review state, overrides, dispositions, any UI beyond the labeling tools, and any write call to DEV.

The volume baseline is computed from an explicit probe run ID, recorded in the report. Never compute it from a run that includes test comments.

## Privacy

- No real comment text, commenter names, or handles in any committed file. Committed fixtures are synthetic and listed in a manifest with their provenance.
- Real payloads live only in git-ignored paths: `fixtures/dev-api/source/real/`, `fixtures/corpus/v*/`, `fixtures/labels/`, `reports/`, and the store `data/`.
- Do not open anything under `fixtures/dev-api/source/real/` or `data/`. Work only from `reports/probe/<run>/shapes.json`, `probe-findings.json`, and aggregate reports.
- `afterword label` and `afterword label-ui` are for the author's own machine. Never run either on real data, and never open their outputs (`fixtures/labels/`, `reports/timing/`). Build and test them against synthetic fixtures only.
- Sending real comment data to a model requires the model-boundary record in `docs/PRIVACY-AND-BOUNDARIES.md` first. That happens no earlier than Stage 3.

## Credentials (ADR-006)

- The DEV key is read from the `DEV_API_KEY` environment variable only, and only in `src/afterword/adapters/dev/client.py`.
- The Anthropic key is read from the `ANTHROPIC_API_KEY` environment variable only, and only in `src/afterword/providers/anthropic.py`. It goes in a request header, never in a prompt.
- Never print, log, or persist either key, and never put one in a fixture, report, exception message, or prompt. Credentials never leave the adapter or provider boundary.
- Do not open `.env`.
- The user runs any live command that needs the key, using `! uv run --env-file .env afterword <command>`. Never ask for the key or suggest passing it inline.

## Adapter boundary (ADR-001)

- Every DEV payload detail (`id_code`, `children`, `body_html`, `user`, endpoint paths) stays inside `src/afterword/adapters/dev/`.
- Code outside the adapter consumes `afterword.observations` (or, later, the canonical model) and never refers to DEV field names.
- CLI commands are thin transports over application service functions (ADR-012). Move existing commands behind service functions when they are next changed substantively; no standalone refactor.

## Storage and identity (ADR-013)

- Storage sits behind a repository interface that only `src/afterword/service.py` calls. SQLite-specific SQL stays inside the repository implementation.
- Records use stable string IDs (source IDs, otherwise UUIDs), never auto-increment integers, and UTC RFC 3339 timestamps. Stored rows hold no filesystem paths, hostnames, or OS usernames.
- The content author, credentials, and settings belong to a platform connection, never to a module-level constant.

## Code standards

- All functions, methods, and module-level variables in `src/` and `scripts/` have complete type hints, including return types. `tests/test_code_standards.py` enforces the module-level variables.
- Every public module, class, function, and method in `src/` and `scripts/` has a Sphinx-style (reST field list) docstring: `:param name:` for every parameter, `:type:` only where hints are insufficient, `:returns:`, `:yields:` for generators, no `:rtype:` (hints carry it), and `:raises:` for exceptions the caller should handle. Constructor parameters are documented in `__init__`.
- `tests/` needs neither, but test helpers and fixtures are typed.
- Configuration is in `pyproject.toml`: ruff with ANN and D (pep257 convention; `tests/` excluded from both), mypy strict over `src/` and `scripts/`, pydoclint in Sphinx style.

## Tests

- Tests never make live API calls. `tests/conftest.py` removes `DEV_API_KEY` and installs a respx router that fails any unmocked request. Keep it autouse.
- All of these must pass before any commit:
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run mypy`
  4. `uv run pydoclint src scripts`
  5. `uv run pytest` (the project venv, Python 3.14)
  6. `uv run --isolated --python 3.12 pytest`
- The declared floor is Python 3.12; check 6 is what supports that claim. Keep `--isolated`: without it, `--python 3.12` rebuilds the project venv on 3.12, and later plain `uv run` commands silently test 3.12 again.
- Hooks (`git config core.hooksPath scripts/hooks`, once per clone):
  - `pre-commit` rejects staged files containing em-dashes or bidi control characters (`scripts/check_text.py`; `LICENSE` exempt), then runs the identity scan (`scripts/check_committable.py`) and checks 1 to 4.
  - `commit-msg` rejects em-dashes and bidi control characters in the commit message.
  - Both report counts and `file:line` positions only. Run pytest yourself.

## Friction log

There are two logs with different purposes:

- **Session notes** go in `friction-delight-logs/sessionN.md` (git-ignored), one file per session, numbered sequentially. Record every surprise there at the time it happens, using the entry template from `docs/FRICTION-LOG.md`. End each session with a session summary in the same file, including a "Scope pressure" section for anything that tried to enter scope and the decision made.
- **The public record** is `docs/friction-log/session-N.md`, one file per session, indexed by `docs/FRICTION-LOG.md`. At the end of each session, copy into `docs/friction-log/session-N.md` the entries that matter to the experiment (API behavior, design decisions, claims or ADRs affected) plus a short session summary, then add the session's pointer line to the index in `docs/FRICTION-LOG.md`. These entries must contain no real comment text, names, or handles. Entries already recorded are never reworded; a correction is a new, dated entry.

When unsure whether an entry belongs in the public record, include it.

## Writing

No em-dashes in any prose, docs, code comments, commit messages, or generated reports. Use a colon, comma, parentheses, or a new sentence instead.

## Attribution

Do not add AI attribution anywhere: no `Co-Authored-By` trailers, "Generated with" lines, or similar credits in code comments or commit messages.

## Git Workflow

Never commit. Write the message to `commit-message.txt` and stop.