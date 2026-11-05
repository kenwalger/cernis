"""The receipt store: every completed run, kept tamper-evident (ADR-002, DESIGN.md section 5).

Tamper-evident means: a change to a stored entry, a removed entry, or a ledger
cut short is detected, as long as the anchor (or a tip kept elsewhere) was not
rewritten to match. Entries are unsigned, so someone who can rewrite both the
ledger and its anchor can rebuild a consistent chain; only a tip copied out of
the store directory (every report carries one) defends against that
(DESIGN.md section 5, decision 1).
"""

from cernis.store.base import (
    ENTRY_SCHEMA_VERSION,
    LedgerStatus,
    PreparedEntry,
    ReceiptStore,
    Recorded,
    RunWriter,
    StoreAnchorError,
    StoredEntry,
    StoreError,
    StoreIntegrityError,
    StoreLockedError,
    StoreTip,
    Verification,
    VerificationStatus,
    canonical_json,
    idempotency_key,
    run_entries,
)
from cernis.store.ledger import DEFAULT_STORE_DIR, LedgerStore
from cernis.store.memory import MemoryStore
from cernis.store.read import StoredRun, run_history, stored_runs

__all__ = [
    "DEFAULT_STORE_DIR",
    "ENTRY_SCHEMA_VERSION",
    "LedgerStatus",
    "LedgerStore",
    "MemoryStore",
    "PreparedEntry",
    "ReceiptStore",
    "Recorded",
    "RunWriter",
    "StoreAnchorError",
    "StoreError",
    "StoreIntegrityError",
    "StoreLockedError",
    "StoreTip",
    "StoredEntry",
    "StoredRun",
    "Verification",
    "VerificationStatus",
    "canonical_json",
    "idempotency_key",
    "run_entries",
    "run_history",
    "stored_runs",
]
