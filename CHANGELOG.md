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

## [0.0.1] - 2026-10-28

### Added

- Initial package to reserve the `cernis` name on PyPI.
- `cernis` command that prints a project status message, and `cernis --version`.
