# ADR-002: Storage behind a ReceiptStore protocol

**Status:** Accepted
**Date:** 2026-10-28

## Context

Every audit run must be kept so later runs can be compared and changes classified (DESIGN.md section 5), and "findings are receipts" asks for a history that cannot be quietly rewritten. sovereign-ledger provides append-only, hash-chained storage in which truncation is detectable, and Cernis is meant to be its first real consumer outside the SDK's own repositories.

sovereign-ledger is experimental, and so is Cernis. If the audit engine called the ledger directly, a ledger limitation would block audits, and each project would inherit the other's failures.

## Decision

Cernis defines its own small `ReceiptStore` protocol in `src/cernis/store/base.py`. The rest of Cernis talks only to that protocol.

- sovereign-ledger is the intended production implementation (`store/ledger.py`), adapted to the protocol.
- An in-memory implementation (`store/memory.py`) serves tests.
- sovereign-ledger is **not a dependency yet**. It is added when the ledger store is built (Phase 5), not before.

## Consequences

- The audit engine, reports, and history work against the protocol and can be built and tested before the ledger store exists.
- A ledger limitation is handled in the adapter or logged, and never blocks an audit.
- Every rough edge found while adapting the ledger goes in `docs/SDK-FRICTION.md`. Claim C-5 (DESIGN.md section 8) is falsified only if Cernis needs a change to the ledger's public API to work.
- The protocol has to be designed from what Cernis needs, not from what the ledger offers, or the boundary protects nothing.

## Amendment 1 (2026-11-04, Session 6b): the stores are built

- **sovereign-sdk-ledger is a dependency** (`>=2.0.0,<3.0.0`), now that the ledger store is built. Session 6a found that 1.3.0 could not serve it: it had no way to read entries back (claim C-5, falsified). The gaps were fixed in the SDK as 2.0.0, not worked around in Cernis. The package ships no `py.typed`, so `typings/sovereign_ledger/__init__.pyi` types the public names Cernis uses; a test checks the stub against the installed package.
- **The protocol, as built** (`src/cernis/store/base.py`), is three operations Cernis needs:
  - `writer()`: take the single writer, whose `record(run)` appends a completed run;
  - `entries()`: read every entry back, verified;
  - `verify(expected)`: check the store against its anchor, or an expected tip.

  `LedgerStore` (`store/ledger.py`) and `MemoryStore` (`store/memory.py`) implement it. The read side (`store/read.py`, for `cernis runs` and `cernis history`) works on entries, not on either store.
- **What a run appends, the field mapping, the idempotency keys, the tip anchor, and failure behavior** are in DESIGN.md section 5, "The receipt ledger". Claim C-5b (section 8) holds Cernis to the ledger's public API, and two tests enforce its first two falsifiers.
- **A ledger limitation still never blocks an audit.** A run that cannot be recorded is still reported. Its report says it was not recorded and why, and the command exits with status 1.
