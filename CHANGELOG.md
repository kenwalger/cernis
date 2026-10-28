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

## [0.0.1] - 2026-10-28

### Added

- Initial package to reserve the `cernis` name on PyPI.
- `cernis` command that prints a project status message, and `cernis --version`.
