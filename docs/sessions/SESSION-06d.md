# Session 6d: the Session 6c audit and its fixes

**Date:** 2026-11-05
**Phase:** 5 (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

Session 6c proposed a `standard` Decision Engine audit of its history code (its Deferred section). The Owner approved it ("Yes, run the audit."). This session ran it, adjudicated it, and fixed what it accepted. Session 6c's record is not rewritten; this record supersedes it where they differ, in particular on the classifier version, now `2+h1`. No real network requests were made: the C-2 diffs were remade from the local store.

## Done

- **The audit, `aud_ZoO0lIpLnb`** (mode `standard`). 23 findings: **19 accepted, 4 rejected** (table below).
- **Run selection.** `--from` must name a run stored before `--to`'s. The same run twice, or the reverse order, is a usage error (exit 2) that lists the runs in order.
- **Causes must be shown** (DESIGN.md section 5, draft 2.13):
  - A Cernis version change is a `CHECKER` cause, like a classifier version change. Page evidence with a `CHECKER` page change (the extractor changed) is `CHECKER`, never `PAGE`.
  - A resource is compared on the receipt the finding cites in each run. Where the finding is absent from a run, the run's last receipt of that URL is used.
  - A `304` that validated a cached `200` is compared as that `200`, since the fetcher caches only `200`s and records a `304` with the cached body's hash.
  - A resource fetched in only one run is `UNKNOWN`, not `RESOURCE`, and the detail says so.
  - Two or more shown changes (the page and a resource, or two resources) are `UNKNOWN`, naming each.
  - A recommendation takes its bases' cause only when all its changed bases share one. Otherwise it stays `UNKNOWN`, naming them.
- **Page changes:**
  - No snapshot in either run: still `UNCLASSIFIED`, with the reason naming both runs. It is never a finding's cause.
  - A `CHECKER` change with no hash changed says "no snapshot hash changed".
  - A head hash change with no field change is `UNCLASSIFIED`, not a crash.
- **The diff** names the version of the control file it used. The Markdown escapes page-supplied head field names and the run table's values.
- **The control file loader** refuses a file missing any of the four site types, and a field named twice for one site type.
- **The head hash pin** in `test_the_hashes_of_a_fixture_are_pinned` is a literal again. It is the hash of the exact head fields, so it pins them.
- **`HISTORY_VERSION` is 2**, so the classifier version is `2+h1`. The C-2 runs record `1+h1`.

## Claim C-2, rechecked

The fixes change causes and run selection, not the page classes C-2 saw. The four consecutive diffs of the ten C-2 pages were remade from the store with `2+h1`, with no requests. They give the same 20 events: each WordPress original "PLATFORM_RENDERING", with only `frame_sha256` changed, and no finding change (`reports/2026-11-05-c2-diffs-classifier-2.json`, local). C-2 stays falsified, as recorded.

## Audit

**`aud_ZoO0lIpLnb`**, mode `standard`. The artifact was real code only, 104,202 bytes:

- in full: `src/cernis/history/fields.py`, `classify.py`, and `report.py`; `src/cernis/data/head_fields.toml`; and `tests/test_history_classify.py`, `test_history_fields.py`, and `test_cli_diff.py`;
- as diffs against `e1ac428`: `snapshot.py`, `model.py`, `cli.py`, `store/base.py`, `json_report.py`, and `tests/test_parse_snapshot.py`.

Three voices, all with the verdict `has-serious-issues`:

- gpt-6-sol (G): 4 findings;
- gemini-3.8-flash-high (M): 4 findings;
- claude-sonnet-5-5 (C): 15 findings.

| Finding | Claim | Decision | Evidence or fix |
|---|---|---|---|
| G1, M2, C7 | `--from` and `--to` can name one run twice, or the later run first; one stored run named twice gives an empty diff | Accepted | `_choose` refuses both, as a usage error listing the runs in order |
| G2, C1 | A resource fetched in only one run is reported as `RESOURCE`, so a link the author added is blamed on the link's target | Accepted | Not a shown change: `UNKNOWN`, the detail saying it was fetched in only one run |
| G3, M1, C2 | A finding from the page gets `PAGE` with page class `CHECKER` when only the Cernis or extractor version changed | Accepted | The Cernis version is a `CHECKER` cause; page evidence with a `CHECKER` page change is `CHECKER`. C2's other part, that a `CHECKER` page change with no hash changed is false instability, is by design (`CHECKER` is named first); its reasons now add "no snapshot hash changed" |
| G4 | The resource's last receipt is compared, not the one the finding cites | Accepted | The cited receipt is compared in each run; the URL's last receipt only where the finding is absent |
| M3 | `head_fields` is checked as a `list`, so tuples from in-memory snapshots are missed | Rejected | Records are always JSON-decoded: `MemoryStore.entries` parses each entry's content (`src/cernis/store/memory.py:54`), and `test_a_wordpress_metadata_edit_is_author_metadata` reads the fields through it |
| M4 | A diff with a caller's control file names the shipped file's version | Accepted | The version is built from the control used |
| C3 | DEV's render timestamps make DEV pages unstable, and author edits unclassifiable | Rejected | C-2's five runs found all five DEV copies stable in all four diffs, `head-cached-at` and `last-updated` included. An author edit that comes with a DEV field change is `UNCLASSIFIED` by section 5's "more than one class" rule; see Deferred |
| C4 | Neither run having a snapshot is a page change that names only one run | Accepted | The reason names both runs. It stays `UNCLASSIFIED` (whether the page changed cannot be determined) but is no finding's cause |
| C5 | The head hash pin was replaced by a tautology | Accepted | The literal `head_sha256` is pinned again |
| C6 | A page change and a resource change at once are reported as the resource alone | Accepted | Two or more shown changes are `UNKNOWN`, naming each |
| C8 | `normalize_url` raises `ValueError`, which `cernis diff` does not catch | Rejected | It never raises: anything that is not an absolute http(s) URL comes back NFC-normalized and otherwise unchanged (`src/cernis/urls.py:275`) |
| C9 | Page-supplied head field names reach the Markdown unescaped | Accepted | Escaped, as are the run table's values |
| C10 | Branches are untested: one-sided choices, an appeared finding's `CHECKER`, malformed head fields | Accepted | Tests added for each |
| C11 | A `200` and a `304` of the same body are a `RESOURCE` change | Accepted | Such a `304` is compared as the `200` it validated (`src/cernis/fetch/client.py:1012` records it with the cached body's hash) |
| C12 | WordPress `generator` and plugin fields are the platform's, not the author's | Rejected | DESIGN.md section 3: anything on WordPress is `AUTHOR` (the author runs the site). By section 4, a bodiless owned page is `UNCLASSIFIED` |
| C13 | No class at all crashes the classifier, and `_actor` accepts more than three actors | Accepted | Now `UNCLASSIFIED` with a reason. The second part is moot: `Actor` has exactly three members (`src/cernis/model.py:32`) |
| C14 | A control file that is missing a site type, or names a field twice, loads | Accepted | Both are refused (`fnmatch` has no invalid patterns to refuse) |
| C15 | A recommendation takes its first basis's cause, by list order | Accepted | All changed bases must share one cause; otherwise `UNKNOWN`, naming them |

## Tests seen failing first, on behavior

- **Classifier:** 14 of the 16 new tests failed first. They covered:
  - run order, and one run named twice;
  - the Cernis and extractor `CHECKER` causes;
  - the unfetched resource, the cited receipt, and the `304`;
  - the page-and-resource case, and mixed bases;
  - no snapshot in either run, and no field change;
  - the control's version, and Markdown escaping.

  The other two passed at once, since they cover branches that already existed: the one-sided choices, and the appeared finding's `CHECKER`.
- **Control file:** both new tests failed first (the missing site type, and the field named twice).
- **Passed at once, as guards on existing behavior:** the 4 malformed-head-field model tests and the head hash pin.
- **Existing tests changed with the rules:**
  - `test_an_exact_name_wins_over_a_pattern` now describes all four site types.
  - `test_two_runs_of_an_unchanged_page_say_so_plainly` expects `2+h1`.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict (84 files)
- pydoclint
- pytest: 1368 passed (1346 before)
- the isolated Python 3.12 pytest: 1368 passed

## Deferred

- **A DEV author edit that also moves a field DEV writes** (from finding C3). If DEV rewrites `last-updated` or `head-cached-at` when the author edits, the edit is `UNCLASSIFIED` ("more than one class at once"), by section 5's rule. Whether DEV does this has not been observed, since the C-2 pages were not edited. If a later session observes it, the fix is a recorded decision about those fields, not a quiet exclusion.
- Session 6c's other deferred items stand: C-2b, the DEV actor table, `csrf-param` and `csrf-token`, and the Windows output encoding.

## Not touched

- The checks and their versions; the fetcher; the snapshot normalization (still version 2); the store's entry schema version.
