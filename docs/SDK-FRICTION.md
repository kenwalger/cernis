# SDK friction log

Cernis is the first consumer of the Sovereign Systems SDK outside the SDK's own repositories. This log records every rough edge met while using it (sovereign-ledger as the receipt store, and sovereign-sieve if it is adopted for extraction): what was tried, what happened, what was expected, and the workaround. Each entry is dated and becomes an issue on the SDK. Entries are never reworded; a correction is a new, dated entry.

## 2026-10-30: sovereign-sieve evaluated for HTML and metadata extraction (Session 4a)

**Tried.** DESIGN.md section 13, open question 1: does sovereign-sieve fit Cernis's extraction step (Session 4a items 1 and 2: reading `<title>`, `<html lang>`, canonical links, meta description, `og:*`, JSON-LD, and body links, and finding the article body)? Evaluated in a throwaway environment (`uv run --isolated --no-project --with sovereign-sdk-sieve==1.3.0`), never added to Cernis's dependencies, against the synthetic fixtures in `tests/fixtures/`.

**Friction 1: the package name moved.** `pip install sovereign-sieve` installs `sovereign-sieve` 1.1.1, an empty package whose summary says "This package has transitioned. Please install sovereign-sdk-sieve instead" and which depends on `sovereign-sdk-sieve>=1.3.0`. The import name stayed `sovereign_sieve`, so `pip install sovereign-sdk-sieve` then `import sovereign_sieve` is the working spelling. DESIGN.md and this log still say "sovereign-sieve". Expected: one name, or the old name's README saying which import to use. Workaround: install `sovereign-sdk-sieve`.

**Friction 2: no metadata.** On PyPI, `sovereign-sdk-sieve` 1.3.0 declares no `requires_python` in the stub (`sovereign-sieve` 1.1.1) and no license on the stub; the real package says Python 3.12+ and MIT. Minor, but a consumer checking licenses sees the stub's blank.

**What it is.** A "Prose Tax" token optimizer: `pure_sieve(payload: str) -> str` and `sieve_with_metrics(payload: str) -> SieveOutput` strip greetings, hedges ("please", "just"), filler ("of course"), preamble phrases ("I hope this"), degenerate markdown, and repeated headings from LLM prompts, and estimate token savings. It has no HTML parsing, no selectors, and no notion of elements, attributes, or document structure.

**Against item 1 (metadata extraction): does not fit.** There is nothing to call: it cannot find a `<link rel="canonical">`, read an attribute, or tell `<head>` from `<body>`. Run on raw fixture HTML it returns rewritten HTML: on `dev-article.html` it changed 3464 characters to 3274 (indentation collapsed), and on `malformed.html` it changed the JSON-LD text (`"Caféé" , }` became `"Caféé", }`). Evidence must record what the page said, so any rewrite of the source before extraction is disqualifying.

**Against item 2 (article body): does not fit, and would be harmful.** Given the article text "This page is written by hand. It links to a paper. Please just read it. I hope this helps.", it returned "This page is written by hand. It links to a paper. read it. helps." It deletes the author's own words. Used before `content_sha256`, an author adding or removing "please" would not be seen as a content change, and any finding quoting the text would misquote it.

**Against snapshot normalization (item 3): does not fit.** It does not remove volatile tokens: the two volatile-token fixtures, which differ only in CSRF values, nonces, and asset hashes, are still different after `pure_sieve`. It is deterministic (the same input gives the same output), which is the one property Cernis would need.

**Conclusion, for the Owner's decision.** sovereign-sieve solves a different problem (shrinking prompts for an LLM) from Cernis's (reading HTML exactly). Session 4a uses selectolax, as DESIGN.md section 6 names. Nothing here is a defect in sovereign-sieve; it is a fit question. Possible SDK issues: unify the package name; and, if the SDK means to offer HTML extraction, that would be a separate module, since prose sieving must never run on evidence. Claim C-5 concerns sovereign-ledger only and is not affected.

## 2026-11-04: sovereign-ledger as Cernis's receipt store (Session 6a)

**Tried.** ADR-002: put sovereign-ledger behind Cernis's `ReceiptStore` protocol, append each completed run (the run record, its receipts, snapshots, and findings, as canonical JSON with a schema version), and read the runs back for `cernis runs` and `cernis history <url>`. Using only the public API, as the session prompt required. Evaluated with the published package in a throwaway environment (`uv run --isolated --no-project --with sovereign-sdk-ledger==1.3.0`). It was not added to Cernis's dependencies, because of friction 1.

**Friction 1, blocking: no public way to read entries back.** The public API of `sovereign_ledger` 1.3.0 is `SovereignLedger.append_receipt`, `verify_ledger_integrity`, and `close`, plus `SovereignStorageError` (`__all__`, the README's API reference, and `inspect` all agree). No method returns a stored entry, iterates the chain, or reports the current tip, and the changelog announces none. `verify_ledger_integrity` reads every row but returns only a bool. A store that can be written and verified but not read cannot serve history (DESIGN.md section 5), so Cernis cannot use it as its store through the public API alone.
- **Workarounds, each rejected for now:**
  - Reading the SQLite file directly. The README documents the `forensic_ledger` table and the `sieved_content` column, so no private Python name would be imported. But it bypasses the public API and depends on the on-disk schema, which the SDK does not promise to keep.
  - A Cernis-owned copy of every entry. That copy would be what Cernis reads, and the ledger could not vouch for it, since nothing can be read back to compare.
- **Suggestion:** a read-only iterator, for example `iter_entries() -> Iterator[Entry]` in chain order, where `Entry` carries `payload_hash`, `parent_hash`, `timestamp`, and the stored content. Also `tip() -> str | None`, so a consumer can record the tip without having to remember the last append.

**Friction 2: the package name moved, again.** `pip install sovereign-ledger` installs 1.1.1, an empty package whose summary says "This package has transitioned. Please install sovereign-sdk-ledger instead". The import name stays `sovereign_ledger`. The same happened to sovereign-sieve (2026-10-30 entry); the SDK changelog for 1.3.0 lists the renames. **Suggestion:** say which import name to use in the stub's README.

**Friction 3: the API is shaped for `ForensicReceipt`.** `append_receipt(receipt, sieved_content)` requires `receipt["payload_hash"]`, `receipt["timestamp"]`, and `receipt["signature"]` (a missing key raises a bare `KeyError`), and reads token telemetry from `receipt["metadata"]["prose_tax_summary"]`. A consumer with no signing step must pass an empty `signature`, which the ledger accepts; the stored row then reads like an unsigned ForensicReceipt. **Suggestion:** a generic `append(content: str, *, timestamp: str) -> str` that derives `payload_hash` itself, with `append_receipt` kept for the signed path.

**Friction 4: identical content cannot be appended twice.** `payload_hash` is `UNIQUE`, so appending the same content again raises `sqlite3.IntegrityError`. Unchanged snapshots across runs are exactly what history needs to store, so a consumer must salt each entry (for example with its run id) to make it unique. **Suggestion:** document the uniqueness rule next to `append_receipt`, or key rows by position and allow repeated content.

**Friction 5: no single-writer guard across processes.** Writes are serialized by `BEGIN IMMEDIATE` and a 5-second `busy_timeout`, so a second writer waits, then fails with `sqlite3.OperationalError`. A consumer that wants "one writer at a time, a clear error for the second" needs its own lock. **Suggestion:** an optional exclusive-open mode, or a documented error type for a held lock.

**What worked.** Appending with an empty signature, the returned tip, and `verify_ledger_integrity(expected_tip_hash=...)` behaved as documented. Zero runtime dependencies and Python 3.12+ match Cernis.

**Effect on claim C-5** (DESIGN.md section 8): Cernis cannot store and read its history through the ledger's public API without an addition to that API (friction 1), which is C-5's falsifier. Session 6a stopped before building the store and left the result for the Owner to record.
