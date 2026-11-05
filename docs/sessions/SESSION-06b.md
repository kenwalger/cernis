# Session 6b: the receipt store, on sovereign-sdk-ledger 2.0.0

**Date:** 2026-11-04
**Phase:** 5, in part (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

This session resumes Session 6a from item 2, against `sovereign-sdk-ledger` 2.0.0, which fixed the gaps Session 6a found in 1.3.0. Session 6a is recorded and is not rewritten. This session takes the next letter, so the history diff that Session 6a's prompt called "Session 6b" moves to the next session.

## Done

- **C-5 recorded as falsified, and C-5b stated** (DESIGN.md section 8, draft 2.11).
  - C-5 keeps its wording. The results table now gives the evidence: the 1.3.0 API was `append_receipt`, `verify_ledger_integrity` (a boolean), and `close`; there was no read path; `payload_hash` was `UNIQUE`; and an unsigned entry needed an empty-string signature. The outcome: the gaps were fixed in the SDK and released as 2.0.0.
  - C-5b and its three falsifiers were written before the store was built.
  - C-5c, signing, is noted as a possible future claim.
- **The design** (DESIGN.md section 5, "The receipt ledger"):
  - what a run appends;
  - the canonical JSON entry and its schema version;
  - the field-by-field mapping to `append_entry`;
  - the idempotency-key derivation;
  - the two decisions (the tip anchor beside the ledger; unsigned for now);
  - verification;
  - what a failed write does.
- **Dependency:** `sovereign-sdk-ledger>=2.0.0,<3.0.0`. `uv lock` added that one package and nothing else. Session 6a left no placeholder, shim, or partial integration, so there was nothing to replace.
- **The store** (`src/cernis/store/`, ADR-002 amendment 1):
  - `base.py`: the `ReceiptStore` protocol (`writer()`, `entries()`, `verify(expected)`); `run_entries` (one entry per receipt, snapshot, and finding, then the run record last); `plan_appends` (skip a key recorded with the same payload hash, refuse a run whose id is reused with other content); and `parse_entry`.
  - `ledger.py`: `LedgerStore` on the ledger's public API only.
    - It uses `append_entry` (never `append_receipt`), with no signature.
    - The idempotency key is `cernis/<run id>/<kind>/<local id>`.
    - Reads use `iter_entries()` with verification on.
    - The ledger is verified against the anchor before every append, and an `IdempotencyKeyConflictError` is treated as already recorded (logged at debug level).
    - After each run, the tip is written atomically to `ledger.db.tip.json`.
    - An OS file lock (`ledger.db.lock`, `msvcrt` on Windows, `fcntl.flock` elsewhere) admits one writer.
  - `memory.py`: `MemoryStore`, with the same rules, for tests.
  - `read.py`: complete runs only (a run counts once its run record is stored); `cernis runs` and `cernis history` in Markdown and JSON.
- **Typing:** `typings/sovereign_ledger/__init__.pyi`, a stub of the public names Cernis uses, because the package ships no `py.typed`. `mypy_path` points to it. A test checks every class, field, enum member, and method signature in it against the installed package.
- **The command line:**
  - `--store DIR` on `audit`, `pair`, and `pairs`; the default is `.cernis/store/`, and `.cernis/` is git-ignored.
  - The writer is taken before anything is fetched.
  - After each run, the tip is printed on standard error and recorded in the report header: `Ledger:` in Markdown, `run.ledger` in JSON. The JSON field is added only when there is a store, so the golden reports are unchanged.
  - New commands: `cernis runs`, `cernis history <url>` (both `--format md|json`), and `cernis store verify [--expected-tip SEQUENCE:HASH]`, which exits 0 when verified, 1 when verification fails, and 3 when not determinable.
- **Tests:** `tests/test_store.py` (both stores), `tests/test_store_ledger.py`, `tests/test_cli_store.py`, and `tests/store_support.py`. `tests/conftest.py` gains an autouse fixture that points the CLI's default store at a fresh directory for each test.
- **Real requests** (item 7, the only ones made): `cernis pair` on the Views Measure Views pair, twice, with `reports/kenwalger-map.toml`, whose prefix rule declares kenwalger.com/blog/ WordPress. The reports are in `reports/`, which is git-ignored.

  | Run | Tip after it |
  |---|---|
  | `20261104T234017Z` | `100 93e488424e87518cec064139f5cb747400e65d874c267a3e7bbdcad84cd9a9ce` |
  | `20261104T234042Z` | `200 46c4fb0e218b99939e2959aeaa50ba03d01daa1ec7a30ca433a7c13577f6a277` |

  - `cernis runs` listed both, each with observed 73, recommendations 0, and not determinable 4.
  - `cernis history https://dev.to/kenwalger/views-measure-views-4co7` listed both runs, with 37 findings each, by key.
  - `cernis store verify` reported 200 entries checked, the tip equal to the anchor, `Result: VERIFIED`, and exit 0.
- **Records:**
  - `docs/SDK-FRICTION.md` (2026-11-04, Session 6b): six points, each with a suggestion.
  - ADR-002 amendment 1.
  - README: the store and its three commands.
  - CHANGELOG (Unreleased).
  - CLAUDE.md.
  - `docs/RELEASE-AUDIT.md` item 33, now the store's review scope.

## Claim C-5b

**Holds.** Every Session 6a item was built on 2.0.0's public API, with no SDK change.

- `test_cernis_never_imports_a_private_name_from_the_ledger` checks the first falsifier: it scans `src/cernis` for any import from a `sovereign_ledger` submodule, any name not in `__all__`, and any underscore attribute of the package.
- `test_cernis_never_opens_a_sqlite_file_itself` checks the second: no `sqlite3.connect` anywhere in `src/cernis`. Cernis imports `sqlite3` only to catch the ledger's exceptions.
- The third falsifier did not occur: no SDK change was needed.
- The type stub is type information only. It is not an import of private code.

## Tests seen failing first

- **Every new test, in all three new test files, failed before its code existed.** They failed at collection, because `cernis.store` did not exist. That is a failure for want of the module, not each behavior observed failing on its own.
- **The CLI tests** (recording, the tip in both reports, the lock before fetching, the failed write, runs, history, and verify) failed for the same reason, and the conftest fixture made every test error at setup until `cernis.cli.DEFAULT_STORE_DIR` existed.
- **One assertion was corrected before running:** the stub had `SignatureStatus` values in lowercase, and the installed package's are uppercase. The stub-matching test would have caught it, and the stub was fixed when the enum was checked.

## Decisions

1. **The run record is written last** and marks a run complete. A write that stops partway leaves entries a reader ignores, and recording the run again completes it. The keys make the retry add only what is missing (`test_a_failed_write_is_raised_and_a_retry_completes_the_run`).
2. **A reused run id is refused whole.** Before appending, Cernis reads the run's keys already in the ledger. A key recorded with different content refuses the whole run before anything is written, with a message saying why; so does a completed run (its run record present) that this run would add entries to. In the second pass, run ids gained a random suffix (below), so a reuse now means a real collision or a bug.
3. **A failed write fails the command, and the report says so.** The report is still written, with `Ledger: not recorded: <reason>`. The reason is printed, and the exit status is 1. A store held by another writer exits 2 before fetching.
4. **The lock is taken before fetching**, so a second writer learns at once and no fetching is wasted. Reading commands take no lock.
5. **A missing anchor before a run.** The run is still appended, the check before it is reported as not determinable (on standard error, and in the report header), and a new anchor is written after the run. A store whose anchor was lost can keep working. Refusing to append would block every later run until someone repaired the anchor by hand. In the second pass, at the Owner's direction, the gap also goes into the run record (`anchor_status`), so it is permanent evidence in the chain, and `cernis runs` and `cernis store verify` show it.
6. **The ledger's reason codes are shown by name** (`TIP_MISMATCH`), as the SDK's documentation writes them; the enum's values are lowercase.
7. **Raw page bodies stay out of the ledger.** Receipts carry the body's hash (`test_page_bodies_are_never_stored`).

## Second pass: two changes, and the audit

**Two changes, at the Owner's direction, tests first:**

- **The missing anchor goes into the ledger.** Each run record keeps `anchor_status`: `verified`, `missing`, `unreadable`, `behind` (added after the audit, below), or `empty`. A run record already recorded is not compared again on a retry, since its `anchor_status` is the first write's. Tests: `test_a_run_that_starts_with_no_anchor_records_the_gap_in_the_ledger`, `test_a_run_on_an_anchored_store_records_the_anchor_verified`, `test_an_unreadable_anchor_is_recorded_as_such`, `test_a_retry_after_the_anchor_was_written_is_still_one_run`, and `test_runs_shows_each_runs_anchor_status`.
- **Run ids are unique within a second:** `20261104T234017Z-a1b2c3`, six random hex digits from `secrets` (`audit.new_run_suffix`). `audit()` takes `run_suffix`, so tests and the golden reports fix it; the golden diff is the id only. Tests: `test_run_ids_name_the_start_in_utc_and_a_suffix`, `test_run_suffixes_are_short_random_hex`, `test_two_runs_started_in_the_same_second_get_different_ids`, and the CLI test `test_two_runs_started_in_the_same_frozen_second_are_both_recorded`. A duplicate id is still refused loudly (`test_a_reused_run_id_with_different_content_is_refused_whole`).

These failed first: `test_audit.py` could not import `new_run_suffix`; the store tests failed on `run_suffix`; the anchor-status tests failed on the missing field.

**The audit.** `aud_GN220m1Nam`, Decision Engine, mode `standard`, as the Owner asked (the AQG ladder's `deep` floor for this change is policy guidance; the tooling refuses nothing below it).

- **Artifact:** real code only, 70,114 bytes, SHA-256 `c247455c7a1e51a05aae1a315e95597f8bd549d362b8679711747c209f9b15ba`: the five `src/cernis/store/` files in full, and the diffs of `cli.py`, `report/json_report.py`, `report/markdown.py`, and `audit.py` against HEAD `1e624ef`. `audit.py` was added to the scope because the run-id suffix is part of the same pass.
- **Voices:** OpenAI gpt-6-sol (3 findings), Google gemini-3.8-flash-high (6), and Anthropic claude-sonnet-5-5 (12). All completed and were parsed, with no fallbacks. 21 findings in all.

**Adjudication**, each finding checked against the code:

| Finding | Decision | Evidence or action |
|---|---|---|
| O-f1 (critical): a completed run's id reused with new entries contaminates it | accepted | `plan_appends` now refuses any entry a completed run does not already hold. Test: `test_a_completed_run_id_reused_with_new_entries_is_refused`. |
| O-f2: a deleted store, or a missing anchor followed by a run, later verifies | partly accepted | A store deleted whole is indistinguishable from a new one without a tip kept elsewhere (documented limit, decision 1). Re-anchoring after a missing anchor is the Owner's design; the gap is now in the chain and listed by `store verify` (`test_store_verify_lists_runs_that_started_with_no_anchor`). `entries()` checking only the chain is documented (it is `verify()`'s job, and the readers call it first). |
| O-f3 and S-f5: ledger errors outside the append escape as tracebacks, losing the report | accepted | Every ledger call now turns `sqlite3.Error`, `SovereignStorageError`, and `UnicodeError` into a `StoreError`; an unusable store directory is a `StoreError`. Tests: `test_a_backend_failure_while_recording_is_a_store_error`, `test_a_store_directory_that_cannot_be_made_is_a_store_error`, `test_a_backend_failure_still_emits_the_report`. |
| G-f1 (critical): `cernis pairs` crashes on an unbound `source` | rejected | `source` is assigned before the `pairs` branch in `main()`; the diff's context left that line out. The `pairs` CLI tests pass. |
| G-f2 (critical): entries after the anchored tip pass verification | accepted | Against the anchor file, entries after its tip are now not determinable, and the next run records `anchor_status: behind`. An `--expected-tip` from an earlier run still verifies with later runs after it. Tests: `test_entries_after_the_anchored_tip_are_not_determinable`, `test_an_older_expected_tip_with_later_runs_verifies`. |
| G-f3: `history` filters on a field that does not exist | rejected | `finding_as_dict` writes `subject_url` (`report/json_report.py`); the real `cernis history` run listed 37 findings per run. |
| G-f4: findings with the same key overwrite each other | rejected | `Run` validation requires finding keys unique within a run (`model.py`, `Run`). |
| G-f5: the memory store indexes `expected.sequence - 1` for sequence 0 | accepted | A sequence below 1 is now a mismatch. Test: `test_the_memory_store_refuses_an_expected_tip_before_the_first_entry`. |
| G-f6: no tests | rejected | The tests exist; the context said they were not in the artifact. |
| S-f1: a missing anchor does not stop a run | rejected as a design change | The Owner chose to keep recording and put the gap in the chain (decision 5); see O-f2. |
| S-f2: tamper evidence assumes the store directory is not writable by an attacker | accepted, documentation | The threat model is now stated in `store/__init__.py` and `store/ledger.py`, matching DESIGN.md decision 1; signing is C-5c. |
| S-f3: a full append whose anchor write fails is reported as not recorded | accepted | `StoreAnchorError` carries the tip; the report says `Ledger: recorded, tip ...; but the anchor could not be written`, exit 1. Tests: `test_a_failed_anchor_write_is_recorded_but_unanchored`, `test_a_run_whose_anchor_cannot_be_written_says_recorded_and_exits_1`. |
| S-f4: the retry story is unreachable from the CLI, and orphans stay | accepted, documentation | The docstrings and DESIGN.md now say what happens: orphaned entries of a failed write stay, ignored by readers, as a record of the attempt; a retry is the same `Run` through the store's API. The stale "two runs started in the same second" message is gone. |
| S-f6: `--list-only` takes the lock and creates a store | accepted | A listing opens no store. The existing list-only test now asserts no store directory exists. |
| S-f7: no recovery after a failed verification; ledger durability | accepted in part | The recovery procedure and the power-loss case are in DESIGN.md section 5; the durability setting is SDK friction 7. A recovery command is deferred (a decision). |
| S-f8: a key repeated within one run is swallowed | rejected | `Run` validation requires receipt and finding ids unique, and at most one snapshot per receipt, so keys cannot repeat within a run. |
| S-f9: `entries()` claims "verified" but skips the anchor | accepted, documentation | Its docstring now says the anchor is `verify()`'s to check. Reads take no lock; a concurrent append only extends the chain, so the two calls cannot disagree about what was verified. |
| S-f10: the memory store does not model the anchor paths | accepted, documentation | Its docstring no longer claims parity; those paths are tested on the ledger store. |
| S-f11: lax anchor and expected-tip parsing; `cernis store` alone exits 0 | accepted | Anchors must have the right format, an integer sequence of at least 1, and 64 lowercase hex digits; `--expected-tip` needs a SHA-256 and is lowercased; `cernis store` alone exits 2. Tests: `test_a_malformed_anchor_is_unreadable_never_a_tip` (7 cases), `test_an_uppercase_expected_tip_is_read_as_lowercase`, `test_an_expected_tip_must_be_a_sequence_and_a_sha256`, `test_store_with_no_subcommand_is_a_usage_error`. |
| S-f12: two full verification sweeps per record | rejected | Required by the session prompt (`iter_entries()` with verification on); small at current scale. Deferred, above. |

Accepted: 12 (8 with code and tests: O-f1, O-f3, S-f5, G-f2, G-f5, S-f3, S-f6, S-f11; 4 with documentation: S-f2, S-f4, S-f9, S-f10). Partly accepted: 2 (O-f2, S-f7). Rejected: 7 (G-f1, G-f3, G-f4, G-f6, S-f1, S-f8, S-f12). 21 in all. Tests seen failing first: 10, plus `test_store_ledger.py`, which could not import `StoreAnchorError`; one guard test (`test_a_completed_run_retried_unchanged_adds_nothing`) passed before and after, as intended. Under the one-audit rule, the fixes were not audited again.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict (77 files)
- pydoclint
- pytest: 1273 passed (1185 before the session; 1241 before the second pass)
- the isolated Python 3.12 pytest: 1273 passed

## Deferred and uncertain

- **The history diff and change classification** (DESIGN.md section 5), which test C-2: the next session.
- **The POSIX lock** (`fcntl.flock`) did not run here, since this machine is Windows. CI on Linux will run it.
- **Output encoding (deferred by the Owner):** standard output redirected to a file on Windows uses the console code page, so `·` in `cernis runs` and `cernis history` arrives as cp1252. This is true of every command that writes to standard output, `audit` included. `runs` and `history` have no `--output` option yet.
- **A command to recover from a failed verification** (audit S-f7): deferred, because accepting a broken ledger is a decision. DESIGN.md section 5 documents the manual recovery (move the store aside), including after a power loss.
- **One verification sweep per record instead of two** (audit S-f12): rejected for now. `iter_entries()` with verification on is required by the session prompt, and the cost is small at Cernis's scale.
- **No Decision Engine audit.** The project's audit policy is `ask`, and the session ran none. Under the AQG ladder this change would be `deep`: it is tamper-evidence storage, and its appends cannot be undone.
- **SDK issues:** the six points in `docs/SDK-FRICTION.md` (2026-11-04, Session 6b).
- **The AQG construction checker blocks this change**, and the block is accurate. The session's ledger was created at 23:27:26 UTC, after the first edits (DESIGN.md for Step 1, and the dependency for Step 2, from 23:24:29). Its `created_at` was not backdated to pass. Every other ledger check passed.

## Not touched

- The checks, parsers, fetcher, and model.
- The JSON report's format version: `run.ledger` is an added field.
