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
