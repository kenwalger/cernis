# ADR-003: Oversized bodies are cut off at the limit and not hashed

**Status:** Accepted
**Date:** 2026-10-29

## Context

The fetcher reads at most `max_body_bytes` of a response body (5 MB by default), so a misconfigured or hostile server cannot make a run read without end or hold an unbounded body in memory. A receipt records `body_sha256`, "the SHA-256 of the raw response body" (DESIGN.md section 3), and Phase 5 compares runs by these hashes and by snapshots derived from them.

When a body is longer than the limit, there are three ways to fill in `body_sha256`:

1. Hash the bytes read. The receipt would then claim a hash of the body that is really the hash of a prefix, and two different pages sharing a 5 MB prefix would look identical.
2. Keep reading past the limit, hashing and discarding, to get the true hash. That defeats the limit: the bytes still cross the network and the run still waits for them.
3. Stop at the limit and record no hash, saying why.

## Decision

Option 3. When a body exceeds the limit:

- The fetcher stops reading at `max_body_bytes` and closes the response.
- The receipt's `body_sha256` is `None`, and a new receipt field, `body_truncated_at`, records the limit in bytes. `body_truncated_at` is `None` whenever the body was read whole.
- The model enforces it (`Receipt.__post_init__`): `body_truncated_at` must be a positive int, requires a response (`error_kind` `NONE`), and cannot be set together with `body_sha256`.
- The bytes that were read stay available on the fetch result (`FetchResult.body`), not on the receipt, for uses that can work on a prefix. The robots.txt reader is one: RFC 9309 section 2.5 lets a crawler ignore content past a limit of at least 500 KiB.
- An oversized body is never cached, since there is no whole body to revalidate.

## Consequences

- `body_sha256` always means the hash of a whole body, or of the cached body a `304` validated, never of part of one. A reader can tell "no body" (no response) from "body too large" (`body_truncated_at` set) from the receipt alone.
- Phase 3 must not derive a snapshot from a truncated body as if it were the page. A check that sees `body_truncated_at` reports what it can, or a `NOT_DETERMINABLE` finding with the receipt as evidence.
- Receipt has one field more than the DESIGN.md section 3 sketch. Every report format and the store (Phase 5) must carry it.
- The limit applies to the body after content coding (gzip, deflate) is removed, which is also what is hashed. A compressed response can expand in memory by up to one network chunk's worth of decompression before the limit stops it.

## Amendment 1 (2026-10-29, session 3): what the limit counts, and cached bodies

The Decision Engine audit of Session 3 (`aud_K8j95M7gmH`) showed that the last consequence above was wrong: httpx decodes each network chunk in full, with no output bound, so one compressed chunk could expand by far more than "one chunk's worth" before the limit applied, and stacked codings multiplied that.

- Cernis now offers only `gzip` and `deflate` (`Accept-Encoding: gzip, deflate`) and decodes them itself with bounded output, so no more than the limit plus one byte is ever decoded. A body in more than one coding, or a coding Cernis did not offer, is not decoded; that attempt is `CONNECTION` with its status kept (ADR-004).
- `max_body_bytes` bounds both the bytes received and the bytes after decoding. Either one passing the limit ends the read, with `body_sha256` `None` and `body_truncated_at` set.
- A cached body larger than the current limit is a cache miss, so a `304` can never bring back a body the current run would have cut off.
- When robots.txt is cut off, its last, partial line is dropped before the rules are parsed.
