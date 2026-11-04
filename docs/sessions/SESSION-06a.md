# Session 6a: Phase 5, part one, stopped at the store

**Date:** 2026-11-04
**Phase:** 5, in part (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

The session prompt asked for item 0 (D33), item 1 (the bare `cernis` message), then the receipt store on sovereign-ledger (items 2 to 5), friction notes (item 6), and real `cernis pair` runs (item 7). Items 0 and 1 are done. The session stopped at item 2, as the prompt directs when Cernis cannot work without a change to the ledger's public API: sovereign-sdk-ledger 1.3.0 has no public way to read entries back. Items 2 to 5 and 7 were not started. There was no Decision Engine audit, and the only real network requests were the PyPI and SDK documentation lookups that item 2 asks for. `cernis pair` was not run.

The prompt said DESIGN.md was at draft 2.8. It was at 2.9 (Session 5e), so this session's bump is to 2.10.

## Done

- **D33: a time budget for a whole fetch** (ADR-005 amendment 2).
  - `FetchConfig.fetch_timeout`, default 120 seconds, bounds every attempt, retry wait, pacing wait, and redirect hop of the requested URL.
  - Each request's deadline is the sooner of `total_timeout` and the budget's end.
  - A retry whose wait would end past the budget is not made.
  - A request with no time left is `TIMEOUT`, with no status, and is not sent.
  - Each robots.txt fetch has a budget of its own, and the time it takes is added back to the page's budget, so a slow page cannot get an origin disallowed.
  - Tests, written first:
    - retries stop at the budget;
    - a redirect chain is cut at the budget;
    - a request after a long pacing wait is never sent;
    - robots.txt has its own budget;
    - a slow page's redirect target still has its robots.txt read;
    - `fetch_timeout` must be positive.

    All six failed first, because the setting did not exist.
  - `test_backoff_is_capped` now passes `fetch_timeout=300`. Its waits (40, 60, 60 s) outlast the default budget, and the test is about the cap.
  - Records: the client docstrings, DESIGN.md section 6, the experiment document's D33 status, `docs/RELEASE-AUDIT.md` item 4, and the CHANGELOG.
- **The bare `cernis` command** now says what Cernis does, points to `cernis --help`, and gives the repository URL. Its test asserts the pointer and the absence of "nothing is usable" and "early development", and it failed first. Section 12 of DESIGN.md, the historical v0.0.1 prompt, still quotes the old wording, and was left as history.
- **The ledger, examined** (item 2): the published package, its README and changelog, its public API, and a throwaway run of that API. Recorded in `docs/SDK-FRICTION.md` (2026-11-04), five points, each with a suggestion:
  1. No way to read entries back (blocking).
  2. The package name moved again.
  3. The API is shaped for `ForensicReceipt`.
  4. Identical content cannot be appended twice.
  5. No single-writer guard across processes.
- **`docs/RELEASE-AUDIT.md`**: items 32 (the bare message) and 33 (the store, when built), and a note under item 4 for the budget.

## The stop: claim C-5

**What was checked:**

- `sovereign-ledger` on PyPI is 1.1.1, an empty package that points to `sovereign-sdk-ledger`. That package is 1.3.0, MIT, Python 3.12+, and has no dependencies.
- Its public API (`__all__`, the README's API reference, and `inspect` on the installed package agree) is `SovereignLedger.append_receipt`, `verify_ledger_integrity`, and `close`, plus `SovereignStorageError`.
- In a throwaway environment, with a temporary database:
  - appending a Cernis-shaped entry with an empty signature works;
  - the same content twice raises `sqlite3.IntegrityError`;
  - a missing `signature` raises `KeyError`;
  - `verify_ledger_integrity(expected_tip_hash=...)` returns `True`;
  - no public member returns stored entries or the current tip.

**Why that stops the store:** `cernis runs` and `cernis history <url>` must read stored runs, and history is the reason for the store (DESIGN.md section 5). Through the public API, entries can be written and verified, but never read. C-5 is falsified if "Cernis needs a ledger API change to function", and the prompt says to stop and say so.

**The two workarounds, and why neither was taken:**

- **Read the SQLite file directly.** No private Python name would be imported, and the README documents the `forensic_ledger` table. But it bypasses the public API the prompt requires, and depends on an on-disk schema the SDK does not promise to keep.
- **Keep a Cernis-owned copy of every entry and read that.** The ledger could not vouch for the copy, since nothing can be read back to compare, so the history Cernis showed would not be the tamper-evident one.

**For the Owner to decide:**

- Whether C-5 is recorded as falsified.
- Which path the store takes:
  - a read API in the SDK (friction 1's suggestion: `iter_entries()` and `tip()`);
  - reading the documented SQLite table, as an exception to the public-API rule;
  - a different store behind `ReceiptStore`, as ADR-002 allows.

DESIGN.md section 8 is unchanged: C-5 still reads "Not yet tested".

## Decisions

1. **The session prompt arrived as pasted text with no other message**, and was carried out as the author's prompt.
2. **Items 0 and 1 were done before stopping**, because the prompt orders them first and neither depends on the store.
3. **The budget's robots.txt rule.** robots.txt keeps a budget of its own, and its time is added back to the page's. If robots.txt were charged to the page, a slow page could make a redirect target's robots.txt time out, which disallows that origin for the rest of the run.
4. **A request with no time left is a receipt, not a silent stop**, so the run records why the fetch ended. It is `TIMEOUT` with no status, like an address refusal, which also sends nothing.
5. **`fetch_timeout` is not a CLI option**, like the other timeouts.
6. **C-5's result is left to the Owner.** The evidence is recorded, but whether reading a documented table counts as the public API is the Owner's call.
7. **No ledger dependency was added**, and no store module exists. ADR-002's protocol and memory store were not built ahead of the decision, since the decision may change what the protocol needs.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict
- pydoclint
- pytest: 1185 passed
- the isolated Python 3.12 pytest: 1185 passed

## Deferred

- Items 2 to 5 and 7 of the session prompt: the store (memory and ledger), its location and single-writer lock, tip hashes in reports and `cernis store verify`, `cernis runs` and `cernis history`, and the two real `cernis pair` runs. All wait on the C-5 decision.
- The SDK issues from `docs/SDK-FRICTION.md` (2026-11-04).

## Not touched

- The checks, parsers, reports, and the model.
- No ADR other than ADR-005 (amendment 2).
