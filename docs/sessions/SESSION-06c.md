# Session 6c: change classification, `cernis diff`, and claim C-2

**Date:** 2026-11-05
**Phase:** 5 (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

This session built Phase 5's remaining work from DESIGN.md section 5: snapshot head fields, who controls each field, page and finding change classification with causes, and `cernis diff`. It then ran claim C-2 on a sample fixed before any run. **C-2 is falsified.** The real network requests were the ones the session prompt named: DEV's editor guide, read for the control file's sources, and the five C-2 runs, made after the Owner confirmed the ten pages had not changed and would not be edited. There was no Decision Engine audit; one is proposed under Deferred.

## Done

- **Step 1, head fields.** A snapshot now keeps `head_fields`: sorted `(name, value)` pairs for `lang`, `title`, `canonical`, `meta:<attribute>:<key>`, `meta:charset`, and `json-ld`, which holds each block's hash. `head_sha256` is `head_hash(head_fields)`, and the model refuses a snapshot whose two disagree. A snapshot stored without the field (Session 6b's) is still valid and is read with `head_fields` absent. `cernis_entry` stays at 1, since the field is an addition.
- **Normalization version 2, contrary to the prompt's expectation.** The prompt expected extractor versions not to change, since the same values are extracted. They do change. `head_sha256` used to hash the raw head entries, with JSON-LD inline; it now hashes the pairs, with JSON-LD by its hash. So its value differs for the same page. By the snapshot module's own rule (and its pinned-hash test), that is a normalization change, so `NORMALIZATION_VERSION` is 2 and extractor versions read `+n2`. A 6b run compared with a 6c run is therefore `CHECKER`, which is accurate. The golden reports' diff is the new field, the new head hashes, and `+n2`.
- **Step 2, `src/cernis/data/head_fields.toml`** (version 1, `cernis.history.fields`):
  - `wordpress` and `owned`: every field `AUTHOR`.
  - `generic`: every field `UNKNOWN`.
  - `dev`: an explicit list with sources, and `UNKNOWN` by default.
  - Sources: DEV's editor guide (https://dev.to/p/editor_guide, read 2026-11-05), for the front matter keys; and a real DEV head from the local cache (Views Measure Views, fetched in Session 6b), for the field names and for what DEV generates.
  - The classifier version is `1+h1`. It is recorded in every new run record (`classifier_version`) and in every diff.
- **Step 3, `src/cernis/history/classify.py`:** pure functions over stored records, implementing section 5's rules as written in DESIGN.md (draft 2.12). Two points of interpretation:
  - **Attribution to a page change:** a page finding change with no page change has cause `UNKNOWN`.
  - **Recommendations:** a recommendation, which has no evidence of its own, takes the cause of a finding it is based on.
  - **Evidence for bodiless pages:** a page with no body (owned or generic) is `UNCLASSIFIED` when it changes, but still lists the head fields that changed, as evidence.
- **Step 4, `cernis diff <url> [--from] [--to] [--format md|json] [--store]`** (`src/cernis/history/report.py`).
  - **Default:** the two most recent runs that audited the URL.
  - **Exit codes:** 1 with fewer than two runs or a ledger that fails verification; 2 for a run that did not audit the URL, naming those that did.
  - **Markdown:** the two runs, the page change with its evidence, then finding changes grouped by cause in sentences. "No changes between these runs." when nothing changed.
  - **JSON:** documented in the module's docstring.
- **Records:** DESIGN.md draft 2.12 covers the snapshot sketch, the matching and classification rules, the control file, decision 3 (causes), the CLI sketch, and C-2's sample and result. Also updated: README, CHANGELOG, and CLAUDE.md.

## Tests seen failing first, on behavior

- **Snapshots:** 4 failed on behavior once the model had its field.
  - `test_the_hashes_of_a_fixture_are_pinned` (the version was still 1);
  - `test_the_head_fields_are_kept_by_name_and_sorted`;
  - `test_the_head_hash_is_computed_from_exactly_the_head_fields`;
  - `test_a_missing_lang_and_an_empty_lang_are_different_fields`.

  The model tests (`test_a_snapshot_whose_head_fields_disagree_with_its_hash_is_refused`, and the one for a missing field) failed only at collection, since they were written before `head_hash` existed.
- **Store:** `test_the_run_record_names_the_classifier_version` failed with `KeyError: 'classifier_version'`.
- **Classifier:** 24 of 29 tests failed on behavior against a stub whose classifying functions reported no change. Every page class, every unclassified case, every finding-change kind, and every cause was among them. The 5 that passed were the identical-runs guard and the run-selection tests, which the stub implemented.
- **`cernis diff`:** all 6 CLI tests failed on behavior (argparse rejected the unknown command).
- **The control file:** its tests failed only at collection, since `cernis.history.fields` was a new module.
- **Tests corrected while getting to green, all the tests' own mistakes:**
  - four edits whose text was not unique in the WordPress fixture;
  - an attribution test that edited `og:site_name`, which no check observes (now `og:type`);
  - a CLI test that expected an owned page, which has no body, to be `AUTHOR_METADATA` (it is `UNCLASSIFIED`, by section 5's rule).

  The recommendation rule was added after the canonical-resolves test failed with a second, unattributed change; `test_a_recommendation_follows_the_cause_of_the_finding_it_rests_on` was written then.

## The diff of the two Session 6b runs

`20261104T234017Z` to `20261104T234042Z` (tips 100 and 200):

- https://dev.to/kenwalger/views-measure-views-4co7: "No changes between these runs."
- https://www.kenwalger.com/blog/writing/views-measure-views-nine-years-writing: "Page change: PLATFORM_RENDERING", with only `frame_sha256` changed, and no finding changes.

Those runs had no `anchor_status` and no `classifier_version`, both added after them. Their snapshots have no head fields.

## Claim C-2

**Falsified.** The sample (DESIGN.md section 8) was fixed before any run, and the Owner confirmed the pages had not changed and would not be edited.

- **The runs:**

  | Run | Tip | Receipts |
  |---|---|---|
  | `20261105T150122Z-62d993` | 685 | 73: 72 answered 200, 1 answered 404, 0 answered 304 |
  | `20261105T150247Z-80232d` | 1170 | the same |
  | `20261105T150409Z-34a37c` | 1655 | the same |
  | `20261105T150543Z-7c42ef` | 2140 | the same |
  | `20261105T150709Z-bdca80` | 2625 | the same |

  Each run used a new, empty cache directory (`--cache-dir`, a supported option), so nothing was revalidated.
- **The events:** 20, one per WordPress original per consecutive diff. Each reported, exactly: "Page change: PLATFORM_RENDERING; frame_sha256 changed: the page around the article; Hashes changed: frame_sha256". No finding changed in any diff. The five DEV copies reported "No changes between these runs." in all four diffs.
- `cernis store verify`: 2625 entries checked, the tip equal to the anchor, `Result: VERIFIED`.
- **Notes (principle 10; nothing reclassified):** something in kenwalger.com's frame differs per request. Which token it is cannot be determined from what was kept: those responses carried no `ETag` or `Last-Modified`, so their bodies were not cached, and the ledger keeps hashes only.

## Decisions

1. **The session prompt arrived as pasted text with no other message**, and was carried out as the author's prompt. The Owner confirmed the C-2 pages separately.
2. **Normalization version 2** (Done, above), recorded as a finding contrary to the prompt's expectation.
3. **DEV fields are `UNKNOWN` unless a source settles them.** That includes four fields Session 4b's actor table treats otherwise:
   - `title`: the author's title plus DEV's " - DEV Community" (4b: `PLATFORM`);
   - `og:image` and `twitter:image:src`: the cover image or a generated one, on DEV's image service (4b: `AUTHOR`);
   - `json-ld` (4b: `PLATFORM`).

   The checks' actors were not changed; see Deferred.
4. **The classifier version goes in the run record**, so a change to the classifier between two runs shows as `CHECKER` in their diff, as the prompt's `CHECKER` rule requires. Runs recorded before Session 6c have none, and two such runs compare as equal.
5. **The cache was bypassed for C-2** with a new cache directory per run. It is the supported way, and it makes the test about whole pages, not revalidation.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict (84 files)
- pydoclint
- pytest: 1346 passed (1273 before)
- the isolated Python 3.12 pytest: 1346 passed

## Deferred

- **C-2b** (proposed in DESIGN.md section 8, not fixed). The first step is to identify the per-request part of kenwalger.com's frame. That needs two captured bodies of one original, compared with the frame tokenizer, and those requests must be named in a session prompt. The fix would be a new normalization version (3), made and recorded for its own reasons. Only then would C-2b's sample and falsifier be fixed, with all its runs on the new version.
- **The DEV actor table and the control file disagree** (decision 3). Release-audit item 23 is where to reconcile them. Changing the checks' actors would bump their versions.
- **`csrf-param` and `csrf-token`** appear in the synthetic DEV fixture but not on the real page, so they are not listed and are `UNKNOWN`. They are constant (`~`), so they cannot cause a change.
- **The Windows output encoding** (carried from Session 6b).
- **An audit, not run** (audit policy `ask`). Proposed: a `standard` Decision Engine audit of:
  - `src/cernis/history/` and `src/cernis/data/head_fields.toml`;
  - the `snapshot.py`, `model.py`, `cli.py`, and `store/base.py` diffs;
  - the tests `test_history_classify.py`, `test_history_fields.py`, `test_cli_diff.py`, and the new tests in `test_parse_snapshot.py`.

## Not touched

- The checks and their versions; the fetcher; the store's entry schema version.
