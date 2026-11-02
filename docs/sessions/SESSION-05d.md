# Session 5d: documentation and records

**Date:** 2026-11-02
**Phase:** 6, in part (DESIGN.md draft 2.8, sections 2, 8, and 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

Documentation and records only. There were no behavior changes, no real network requests, and no Decision Engine audit, as the session prompt required. The one change to a source file is a docstring.

## Done

- **Claim results** (DESIGN.md section 8, a new "Results (2026-11-02)" table). No claim's wording or number changed.
  - **C-1: falsified.** 0 of 42 audited articles (21 cross-post pairs from the 25 most recent DEV articles, run `20261102T204509Z`) had any `AUTHOR` defect, against a threshold of 10%. The interpretation is recorded with the result: the author's cross-posting was correct throughout; the defect rule is strict by design (principle 4); and the actionable findings appeared as facts, which C-1 does not count (for example, 15 of the 21 originals share one `og:image`). The record says explicitly that no fact was reclassified as a defect after the result.
  - **C-3: holds, weakly.** 21 of 21 defects are genuine on the Owner's review, all one type (DEV's `og:url`, `PLATFORM`). It needs a run with more varied defects to mean much.
  - **C-2:** not yet tested; Phase 5 tests it.
  - **C-4:** not yet tested as a claim; it is enforced at every run by `Run` validation and the no-promise test, and Phase 6 evaluates it.
  - **C-5:** not yet tested; Phase 5 tests it.
  - **C-1b, proposed and not fixed:** on a sample of other developer-writers' public cross-posts, at least 10% of audited articles have an `AUTHOR` defect. Its sample size, selection rule, and threshold must be fixed and dated before any run.
- **Principles** (DESIGN.md section 2):
  - 9, "Audit content you are authorized to audit": your own content, or a client's with permission. Someone else's public pages only in a small, polite sample, such as one to test C-1b.
  - 10, "Facts are not defects after the fact".
  - Principle 8 now points to 9 instead of saying "your own content only", since C-1b would audit others' public pages.
  - CLAUDE.md's principle list matches.
- **CLAUDE.md** gains a "Decision Engine audits" section: an artifact contains real code only, never summaries or pseudocode (Session 5b: six of one voice's findings came from reviewing summarized code). Its current-stage text records this session.
- **Share widgets:** the `wordpress.entry` docstring (`src/cernis/parse/extractors.py`) records the known gap: five newer kenwalger.com posts use a share container the extractor does not yet exclude, pending its class name. Adding it will make the extractor version 3.
- **README:** a `copies = [...]` example, and how a report reads: the Summary (plain counts), the Site section, then the page sections. `pairs --from-dev-user` and `--list-only` were already documented there (Session 5b), and were checked.
- **PAIR-MAP.md:** the Summary and Site sections, and how an original with several copies is shown. `copies`, `--from-dev-user`, and `--list-only` were already documented (Session 5b), and were checked.
- **CHANGELOG:** everything since 0.0.1 is under Unreleased. Added: CI, Trusted Publishing and `docs/RELEASING.md`, and the brand files (they were missing). A Changed section covers the robots matcher, the version from metadata, and the DESIGN.md drafts. A Security section covers the address screen, bounded decoding, the expat sitemap parser and caps, the loopback refusal, and username validation.
- **`docs/RELEASE-AUDIT.md`:** the pre-0.1.0 audit lists from `SESSION-03b.md` through `SESSION-05c.md`, 35 items, consolidated into 31. Each item names its source items. The groups, highest risk first: network safety, untrusted input, robots.txt, the model, URLs and extractors, defect rules, reports, and release machinery. The session records' own lists are left as they were.
- **DESIGN.md plan table:** Phases 2, 3, and 4 are marked done, with session references (2: Sessions 3 and 3b; 3: 4a, 4b, and 4d; 4: 5a, 5b, and 5c). Phase 6 notes this session's results. Draft 2.8.

## Decisions

1. **Principle 8 was reworded to point to principle 9** rather than keep "your own content only", which C-1b's sample would contradict.
2. **C-4 is "not yet tested as a claim."** It is enforced on every run, but the claim is about honest use across a real audit, which Phase 6 evaluates.
3. **The CHANGELOG lists only what is true now.** A bullet saying the bare `cernis` command describes the commands was drafted and removed: its status message still says "nothing is usable yet" (see Deferred).

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (68 files), pydoclint, pytest (1115 passed), and the isolated Python 3.12 pytest (1115 passed).

## Deferred

- **The share container on five posts:** its class name, then `wordpress.entry` 3.
- **The bare `cernis` command's status message** (`STATUS_MESSAGE` in `src/cernis/cli.py`) still says Cernis is in early development and nothing is usable yet. Changing it is a behavior change, so it was left for a later session.
- **C-1b's sample size, selection rule, and threshold**, to be fixed and dated before any run.
- **SDK friction:** none this session; the SDK was not used.

## Not touched

- All behavior: no source change other than the extractor docstring.
- No ADR was changed.
