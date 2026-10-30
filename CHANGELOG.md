# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- The finding and receipt model (`cernis.model`): `Status`, `Actor`,
  `ReasonCode`, and `Family` enums, and frozen `Evidence`, `Finding`, and
  `Receipt` dataclasses that enforce the status rules at construction
  (ADR-001).
- The no-promise checker (`cernis.promises`) and a test that fails if any
  recommendation template contains outcome language.
- The check registry (`cernis.checks.registry`) listing every planned check at
  version 1, none implemented yet.
- `cernis checks [--format table|json]`.
- DESIGN.md draft 2 model changes: `would_require` on NOT_DETERMINABLE
  findings with no possible attempt, and required evidence for the rest;
  `ReasonCode.RATE_LIMITED`; `ErrorKind` and `Receipt.error_kind`, with
  `retry-after` in the recorded headers; `Finding.target` and the derived
  cross-run `Finding.key`; `Snapshot`; `ChangeClass`.
- The fetcher (`cernis.fetch`, DESIGN.md Phase 2): robots.txt for Cernis's own
  user agent (RFC 9309 status rules), per-host pacing, manual redirects with
  every hop recorded, retries for 429 and 503 honoring `Retry-After`, a body
  size limit, timeouts, and a conditional-request cache in `.cernis-cache/`.
  Each attempt produces a receipt.
- `Receipt.body_truncated_at`: the limit at which an oversized body was cut
  off, which then has no `body_sha256` (ADR-003).
- A `TIMEOUT`, `CONNECTION`, or `TLS` receipt names the URL that failed in
  `final_url`, and keeps the status and headers when they arrived before the
  body failed (ADR-004).
- `cernis fetch <url> [--format text|json] [--cache-dir PATH]`.
- httpx is the first runtime dependency.
- An address screen (ADR-005): before every hop, Cernis refuses hosts that
  resolve to loopback, private, link-local (cloud metadata), carrier-grade
  NAT, or other non-public addresses, and connects only to the addresses it
  screened. A refusal is an `ADDRESS_REFUSED` receipt with a reason.
  `cernis fetch --allow-loopback` allows loopback only, for testing.
- Cernis's own RFC 9309 matcher (`cernis.fetch.rfc9309`, version 1)
  replaces `urllib.robotparser`: group selection by product token, longest
  match, Allow winning ties, `*` and `$`, and percent-encoding
  normalization, the same on every supported Python. Robots decisions record
  the deciding rule and the matcher version.
- An overall deadline per request (`total_timeout`), headers included.
- A 429 robots.txt disallows everything, a deliberate departure from
  RFC 9309 (ADR-006).
- httpcore is a declared dependency, and httpx is held below 0.29.
- The parser (`cernis.parse`, Phase 3 part one), on selectolax: `parse_page`
  reads titles, `html lang`, every canonical, every `meta` (including
  `og:*`), every JSON-LD block (raw text and parse result), and body links,
  and never raises on malformed HTML; article-body extractors `dev.article`,
  `wordpress.entry`, and `generic`, each versioned; and `build_snapshot`,
  with documented normalization and volatile-token handling.
- `cernis.urls`: the one URL normalization (`normalize_url`,
  `normalize_percent_encoding`, also used by the robots matcher) and
  `compare_urls` (IDENTICAL, EQUIVALENT with the reason, or DIFFERENT).
- Finding keys are final: NFC on every string, and URL targets normalized.
- `ReasonCode.ADDRESS_REFUSED`.
- selectolax and idna are declared dependencies.
- The nine peritext checks (`cernis.checks.peritext`), exactly per DESIGN.md
  section 4, with recommendations for author-actionable defects from six new
  templates.
- Fetch outcomes as `NOT_DETERMINABLE` findings (`cernis.checks.outcomes`):
  robots.txt, refused addresses, rate limiting, access denied, failed and
  truncated fetches; no check runs against a page not seen whole.
- `Run`, validated as a whole at construction, and `cernis.audit.audit`.
- Reports: JSON (`cernis-report`, format version 1) and Markdown.
- `cernis audit <url> ... [--site-type dev|wordpress] [--format md|json]
  [--output FILE]`.
- The pair map format (`docs/PAIR-MAP.md`) and its loader (`cernis.pairs`).
- `Snapshot.extractor_selection`: declared, prefix, host, or generic.
- Path-prefix site types: `[[site]]` entries in the pair map, the longest
  matching prefix winning, and `cernis audit --map FILE`.
- `peri.lang` 2: a missing or empty `lang` is a defect (WCAG 2 SC 3.1.1).
- `peri.og.core` 2: reports `og:type`; on a page that uses Open Graph, a
  missing required property (`og:title`, `og:type`, `og:image`, `og:url`)
  is a defect. Two new recommendation templates.
- The README logo uses absolute PNG URLs, so it renders on PyPI.

## [0.0.1] - 2026-10-28

### Added

- Initial package to reserve the `cernis` name on PyPI.
- `cernis` command that prints a project status message, and `cernis --version`.
