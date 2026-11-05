# CLAUDE.md

Rules for any session working in this repository.

## Purpose

Cernis is a content discoverability auditor for published articles. Given an article URL, it fetches the page and the things around it, runs deterministic checks, and reports findings backed by evidence. Every finding says whether it was observed, is a recommendation, or cannot be determined, and Cernis never scores a page or predicts an outcome.

## Authority

- `docs/DESIGN.md` is the source of truth. Before changing anything, read `README.md`, then `docs/DESIGN.md` and `docs/adr/`, then `tests/fixtures/README.md`.
- Do not contradict an ADR. If a task seems to require it, stop and ask.
- Record each session in `docs/sessions/SESSION-NN.md` (a follow-up session adds a letter, as in `SESSION-01b.md`): what was built, decisions made, and anything deferred. Session records are not rewritten; a later session supersedes an earlier decision in its own record.
- ADRs are amended with a dated amendment section, never rewritten.

## Current stage

**Phase 1 (scaffold) is built (session 1, 2026-10-28).** The finding and receipt model with its status rules (`src/cernis/model.py`, ADR-001), the no-promise checker (`src/cernis/promises.py`), the check registry with every planned check at version 1 and none implemented (`src/cernis/checks/registry.py`), and `cernis checks`. Session 1b aligned the model with DESIGN.md draft 2: `would_require` for no-attempt questions, `RATE_LIMITED`, receipt `error_kind`, finding `target` and derived `key`, `Snapshot`, and `ChangeClass` (ADR-001 amendment 1).

**Phase 2 (the fetcher) is built (session 3, 2026-10-29).** `src/cernis/fetch/`: robots.txt for Cernis's own user agent, per-host pacing, manual redirects, 429 and 503 retries, a body limit (ADR-003), a conditional-request cache, and one receipt per attempt (ADR-004); `cernis fetch`. Session 3b added the address screen (ADR-005), Cernis's own RFC 9309 matcher (`src/cernis/fetch/rfc9309.py`, replacing `urllib.robotparser`), the overall request deadline, and ADR-006 (429 on robots.txt). Runtime dependencies: httpx (below 0.29) and httpcore.

**Phase 3, part one (foundations) is built (session 4a, 2026-10-30).** `src/cernis/parse/` (parser, extractors, snapshots, on selectolax), `src/cernis/urls.py` (the one URL normalization and `compare_urls`), and final finding keys, which must not change before Phase 5 without an ADR.

**Phase 3 is built (session 4b, 2026-10-30).** The nine peritext checks, fetch outcomes as `NOT_DETERMINABLE` findings, recommendations, a self-validating `Run`, JSON and Markdown reports, `cernis audit`, and the pair map format (`docs/PAIR-MAP.md`). Golden report files are in `tests/golden/`; regenerate them only with `CERNIS_UPDATE_GOLDEN=1`, and read the diff. Session 4d finished Phase 3: path-prefix site types (`[[site]]`, `cernis audit --map`) and standards defects in `peri.lang` and `peri.og.core` (both at version 2).

**Phase 4, part one (the pair check) is built (session 5a, 2026-11-02).** `src/cernis/checks/epitext.py`: `epi.pair.canonical`, `epi.canonical.resolves`, and `epi.og.image.resolves`; the `owned` site type; `cernis pair` and `cernis pairs --map`; one fetch per distinct URL per run (`RunFetches` in `src/cernis/audit.py`); `Run.pairs`. DESIGN.md is at draft 2.5.

**Phase 4 is built (session 5b, 2026-11-02).** `peri.robots.directives`; `epi.robots.access` (`src/cernis/checks/robots_access.py`, crawler list `src/cernis/data/ai_crawlers.toml`); `epi.sitemap.listed` (`src/cernis/sitemaps.py`, `src/cernis/checks/sitemap_listed.py`); `epi.links.resolve` (`src/cernis/checks/links.py`); `ReasonCode.LIMIT_REACHED` (ADR-001 amendment 2); URL sources (`src/cernis/sources.py`: `--from-sitemap`, `--from-dev-user`); `copies` in the pair map; `cernis pairs --from-dev-user`. DESIGN.md is at draft 2.6.

**The first site-wide audit ran (session 5c, 2026-11-02).** Claim numbers fixed (DESIGN.md section 8); `wordpress.entry` 2 (share widgets excluded); site-level findings (`epi.og.image.shared`, `SITE_LEVEL` in the registry) and the report's Summary and Site sections. Real reports go in `reports/`, which is git-ignored. DESIGN.md is at draft 2.7.

**Claim results recorded (session 5d, 2026-11-02).** C-1 falsified (0 of 42 articles with an `AUTHOR` defect), C-3 holds weakly (21 of 21 defects genuine, one type), C-1b proposed; DESIGN.md section 8. The consolidated pre-0.1.0 audit list is `docs/RELEASE-AUDIT.md`. DESIGN.md is at draft 2.8.

**Network-safety fixes (session 5e, 2026-11-02).** 24 of the 28 real findings from the tier comparison (`docs/experiments/2026-11-tier-comparison.md`) are fixed, 4 deferred: more refused ranges and IPv6 translation forms (ADR-005 amendment 1), a bounded DNS lookup, complete-stream and multi-member decoding (ADR-003 amendment 2), robots.txt reading version 2 (`MATCHER_VERSION` 2: a 500 KiB parsing limit), fragments never requested, and tests for the network layer's deadline and TLS paths. DESIGN.md is at draft 2.9.

**Session 6a stopped at the store (2026-11-04).** A whole-fetch time budget (`fetch_timeout`, ADR-005 amendment 2) and an accurate bare `cernis` message are built. The receipt store is not: sovereign-sdk-ledger 1.3.0 has no public way to read entries back (`docs/SDK-FRICTION.md`, 2026-11-04), so C-5 awaits the Owner's decision. DESIGN.md is at draft 2.10.

**The receipt store is built (session 6b, 2026-11-04).** C-5 falsified; the gaps were fixed in the SDK as sovereign-sdk-ledger 2.0.0. `src/cernis/store/` (ADR-002 amendment 1): the ledger store and an in-memory store behind `ReceiptStore`, `cernis runs`, `cernis history`, and `cernis store verify`; DESIGN.md section 5, "The receipt ledger". Claim C-5b holds. DESIGN.md is at draft 2.11.

**Change classification and `cernis diff` are built (session 6c, 2026-11-05).** Snapshots keep their head fields (normalization version 2); `src/cernis/data/head_fields.toml` says who controls each; `src/cernis/history/` classifies page and finding changes with causes. Claim C-2 is falsified: the five WordPress originals' frames differ per request (20 `PLATFORM_RENDERING` events); C-2b is proposed. DESIGN.md is at draft 2.12.

**Next:** identify the per-request part of kenwalger.com's frame, then fix C-2b's sample and falsifier before any run (DESIGN.md section 8). No real network requests beyond what a session prompt names. Tests never touch the network; `tests/conftest.py` enforces it.

## Principles (DESIGN.md section 2)

1. Keep what was observed, what is recommended, and what cannot be determined apart. Every finding has a status (`OBSERVED`, `RECOMMENDATION`, `NOT_DETERMINABLE`) and, separately, an actor (`AUTHOR`, `PLATFORM`, `UNKNOWN`).
2. No scores, grades, or summary numbers. The run summary gives plain counts only (each article's `AUTHOR` defects, and how many articles have any), never weighted or turned into a percentage.
3. No predicted outcomes. A recommendation says what to change and why, never what will happen. The no-promise test makes this a build failure.
4. A defect violates a published standard or the author's stated intent, never a style convention. Lengths are facts, not defects.
5. Absence is evidence. A check records what it searched for, not only what it found.
6. Findings are receipts: URL, time, response hash, evidence, and check version.
7. Deterministic first. No model or LLM in the loop.
8. Polite by default: only content principle 9 allows, an honest user agent, robots.txt respected, paced requests, a cache.
9. Audit content you are authorized to audit: your own, or a client's with their permission. Someone else's public pages only in a small, polite sample (robots.txt respected, normal pacing), for example to test claim C-1b.
10. Facts are not defects after the fact: a claim's result never reclassifies findings to rescue the claim.

## Code standards

- Python 3.12+, managed with uv, src layout. American English.
- All functions, methods, and module-level variables have complete type hints, including return types, in `src/` and `tests/`.
- Every public module, class, function, and method has a Sphinx-style (reST field list) docstring: `:param name:` for every parameter, `:return:`, `:raises:` for exceptions the caller should handle, no `:rtype:` (hints carry it). Dataclass fields are documented as `:param:` in the class docstring.
- Configuration is in `pyproject.toml`: ruff (including ANN and D), mypy strict over `src/` and `tests/`, pydoclint in Sphinx style.
- Model types are frozen dataclasses that validate in `__post_init__` and raise `ModelError` with a message naming the field and the rule.
- Every recommendation template goes in `cernis.checks.recommendations.TEMPLATES`. The test suite fails on a template defined anywhere else, and on any template that contains outcome language.
- Bump a check's `version` in the registry whenever its behavior changes.

## Tests

- Tests never touch the network.
- Fixtures are synthetic and hand-written, never captured from real pages (`tests/fixtures/README.md`).
- The suite must pass from plain PowerShell as well as from Claude Code's shell. On Windows, `bash` on `PATH` may be the System32 WSL launcher; the release gate tests find Git for Windows' bash themselves, skip with a reason when no usable bash exists, and fail instead of skipping in CI.
- All of these must pass before finishing:
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run mypy --strict`
  4. `uv run pydoclint src tests`
  5. `uv run pytest`
  6. `uv run --isolated --python 3.12 pytest` (the declared floor; the project venv may run a newer Python)

## Decision Engine audits

An audit artifact contains real code only: the diff or the files themselves, never summaries or pseudocode. In Session 5b, six of one voice's nine findings described code that did not exist, because parts of the artifact were summarized; each had to be rejected against the real source. If an artifact is too large, audit fewer files in full rather than more files in summary.

## SDK friction

Cernis is a real-world test of the Sovereign Systems SDK. Record every rough edge in the SDK in `docs/SDK-FRICTION.md` when it happens.

## Credentials

Never read or print `.env` files or tokens. Cernis needs no credentials in the MVP.

## Writing

No em-dashes in any prose, docs, code comments, commit messages, or generated reports. Use a colon, comma, parentheses, or a new sentence instead.

## Attribution

Do not add AI attribution anywhere: no `Co-Authored-By` trailers, "Generated with" lines, session links, or similar credits in code comments or commit messages.

## Git workflow

Never commit. The author commits. Write the message to `commit-message.txt` and stop.

## Audit Policy

Audit policy: ask.