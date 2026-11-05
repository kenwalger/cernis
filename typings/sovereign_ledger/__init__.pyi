# Type stub for the public API of sovereign-sdk-ledger 2.x, the names in its
# __all__ that Cernis uses. The package is fully annotated but ships no
# py.typed marker, so mypy cannot read its annotations (docs/SDK-FRICTION.md,
# 2026-11-04). Only public names appear here; tests/test_store_ledger.py checks
# each one against the installed package.

import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any, Self

__all__: list[str]

class SignatureStatus(StrEnum):
    SIGNED = "SIGNED"
    UNSIGNED = "UNSIGNED"

class IntegrityFailureReason(StrEnum):
    BROKEN_LINK = "broken_link"
    SEQUENCE_GAP = "sequence_gap"
    UNSUPPORTED_FORMAT_VERSION = "unsupported_format_version"
    MALFORMED_ENTRY = "malformed_entry"
    TIP_MISMATCH = "tip_mismatch"

@dataclass(frozen=True, slots=True)
class LedgerTip:
    sequence: int
    entry_hash: str

@dataclass(frozen=True, slots=True)
class LedgerEntry:
    sequence: int
    entry_hash: str
    parent_hash: str
    format_version: int
    payload_hash: str
    timestamp: str
    sieved_content: str
    signature_status: SignatureStatus
    signature: str | None
    signer_key_id: str | None
    idempotency_key: str | None
    raw_token_count: int | None
    optimized_token_count: int | None
    tax_savings_percentage: float | None

@dataclass(frozen=True, slots=True)
class LedgerIntegrityReport:
    verified: bool
    entries_checked: int
    failure_sequence: int | None
    failure_reason: IntegrityFailureReason | None
    tip: LedgerTip | None

class SovereignStorageError(RuntimeError): ...
class LedgerMigrationError(SovereignStorageError): ...

class LedgerIntegrityError(RuntimeError):
    sequence: int
    reason: IntegrityFailureReason
    def __init__(self, sequence: int, reason: IntegrityFailureReason) -> None: ...

class IdempotencyKeyConflictError(sqlite3.IntegrityError):
    idempotency_key: str
    def __init__(self, idempotency_key: str) -> None: ...

class SovereignLedger:
    def __init__(self, db_path: str = ".keys/sovereign_audit.db") -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
    def append_entry(
        self,
        receipt: Mapping[str, Any],
        sieved_content: str,
        *,
        idempotency_key: str | None = None,
        signer_key_id: str | None = None,
    ) -> LedgerTip: ...
    def iter_entries(
        self, start_sequence: int = 1, *, verify: bool = True
    ) -> Iterator[LedgerEntry]: ...
    def get_tip(self) -> LedgerTip | None: ...
    def verify_ledger(self, expected_tip: LedgerTip | None = None) -> LedgerIntegrityReport: ...
    def close(self) -> None: ...
