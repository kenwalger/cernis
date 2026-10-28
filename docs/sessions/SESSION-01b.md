# Session 1b: Model aligned with DESIGN.md draft 2

**Date:** 2026-10-28
**Phase:** 1 (scaffold), follow-up to session 1
**Version:** 0.1.0.dev0 (unchanged; not built, not published)

DESIGN.md draft 2 answered the issues raised at the end of session 1. This session brings the model in line with its sections 3 and 5. No fetching, parsing, or diff logic.

## Built

- **NOT_DETERMINABLE rules.** A `question` and a `reason_code` are still required. For `REQUIRES_EXTERNAL_DATA` and `PLATFORM_OPAQUE` (`NO_ATTEMPT_REASONS`), a non-blank `would_require` is required and evidence is rejected. For every other code, evidence of the attempt is required and `would_require` is rejected. `would_require` is rejected on the other statuses.
- **`ReasonCode.RATE_LIMITED`.** `ACCESS_DENIED` is documented as 401 and 403 only.
- **`ErrorKind`** (`NONE`, `TIMEOUT`, `CONNECTION`, `TLS`, `TOO_MANY_REDIRECTS`) and **`Receipt.error_kind`**, required. `NONE` requires a status code and a final URL. Any other kind requires no status code, no final URL, and no body hash, and `TOO_MANY_REDIRECTS` also requires the redirect chain it followed. `retry-after` joins the recorded headers.
- **`Finding.target`**, default empty, and **`Finding.key`**, derived at construction and never passed in. The key is computed by `finding_key()` from the check id, the normalized subject URL, and the target.
- **`src/cernis/urls.py`** with `normalize_url`, an identity placeholder with a TODO pointing to Phase 3's URL comparison.
- **`Snapshot`**: `receipt_id`, `extractor_id`, `extractor_version`, `content_sha256` (may be `None`), `head_sha256`, and `frame_sha256`, with identifier and hash-format validation only.
- **`ChangeClass`**: `CHECKER`, `AUTHOR_CONTENT`, `AUTHOR_METADATA`, `PLATFORM_RENDERING`, `UNCLASSIFIED`.
- ADR-001 amendment 1. Tests: 166.

## Decisions

1. **No-attempt findings carry no evidence.** DESIGN.md says such a finding states `would_require` "instead"; the model reads that as exclusive, both ways. This supersedes session 1 decision 4 (NOT_DETERMINABLE evidence optional).
2. **`final_url` is `None` exactly when there is no response**, matching DESIGN.md's receipt sketch. This supersedes the receipt rule in session 1 decision 5.
3. **`TOO_MANY_REDIRECTS` requires a non-empty `redirect_chain`**, since at least one redirect was followed. This rule is not in DESIGN.md; the local review raised it.
4. **Key encoding.** `sha256` of the compact JSON array `[check_id, normalize_url(subject_url), target]`, UTF-8. JSON keeps the three parts from running into each other. A test pins one digest, so an accidental change to the encoding fails the build.
5. **`finding_key` is public** so history can look up a key without building a finding.
6. **The key ignores status, defect, actor, id, and summary, as well as check version.** The same thing checked in two runs is one key even if its status changed, which is what "a key that changes status" in DESIGN.md section 5 needs.
7. **`target` is empty or non-blank.** Whitespace-only is rejected.
8. **`Snapshot.head_sha256` and `frame_sha256` are required.** Only `content_sha256` may be `None`, per DESIGN.md.
9. **`ChangeClass` lives in `model.py`** with the other enums. The diff logic will go in `history/`.
10. **Record pattern.** This file is a new session record rather than an edit to SESSION-01, and ADR-001 gains a dated amendment rather than a rewrite, following the never-reword rule in the Afterword model. CLAUDE.md now states both conventions.

## Review

The local single-model advisory ran again (`local_host_fb2d0b3681a564a0079b4871`, no `audit_id`), because the Decision Engine server was unavailable. It does not close the audit-before-commit gate. It raised the `TOO_MANY_REDIRECTS` rule above, now fixed, and the questions below.

## Open questions for DESIGN.md

- **Should `target` be normalized in the key?** DESIGN.md normalizes only `subject_url`. For `epi.links.resolve` and `epi.og.image.resolves` the target is a URL, so a cosmetic change to a link (a trailing slash, an uppercase host) gives a new key, and history would report one finding disappearing and another appearing.
- **Unicode normalization.** The key hashes raw strings, so NFC and NFD forms of the same text give different keys. The Phase 3 normalization should decide this.

## Deferred

- The real `normalize_url` (Phase 3). It must land before any run is stored (Phase 5), because changing it changes every key.
- Cross-object checks: a snapshot's receipt must have a response, and evidence receipt ids must exist in the run (run assembly, Phase 3).
- Snapshot extraction (Phase 3) and change classification (Phase 5).
