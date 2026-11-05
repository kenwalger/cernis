# Session 6e: frame normalization version 3, frame ownership, and C-2b

**Date:** 2026-11-05
**Phase:** 5 (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

This session changed the frame normalization and the change classes for their own reasons first, then fixed claim C-2b and ran it. **C-2b holds.** The Owner had captured one WordPress original twice (`a.html` and `b.html`, untracked). They were used only for the one-off check in Step 1, never copied into `tests/`, and deleted at the end. The real network requests were the five C-2b runs the session prompt named, made after the Owner confirmed the ten pages had not changed and would not be edited. Session 6d was not committed when this session began; the Owner chose to build on top and commit both together. After the runs, the Owner approved a `standard` Decision Engine audit (`aud_1vdgpbq7t4`): 9 of its 14 findings were accepted, 5 rejected (Audit, below). The fixes change no class on valid records, so the classifier stays `3+h1` and C-2b's result stands.

## Done

- **Step 1, frame normalization version 3** (`src/cernis/parse/snapshot.py`):
  - Every hidden `input` (`type` `hidden`, in any case) keeps its element and its `name` in the frame, but not its `value`.
  - HTML comments, conditional comments included, are left out wherever they are. This was already true before version 3, so it is not a behavior change; it is now tested and documented.
  - The article body and the head are unchanged.
  - `NORMALIZATION_VERSION` is 3, so every extractor version reads `+n3`: `dev.article 1+n3`, `wordpress.entry 2+n3`, and `generic 1+n3`.
  - The reason is in DESIGN.md section 3, "What the frame leaves out".
- **The one-off check**, `a.html` against `b.html` with the WordPress extractor:

  | Version | `a.html` frame | `b.html` frame |
  |---|---|---|
  | 2 | `7a1517b9d843e958262d0fb5e529835d08fb9ae731c4486036c7b7c8aec983ea` | `523e5565d01c63116556b831ccf6c25eec9a8a93e5853b5e73f6144d58c0effd` |
  | 3 | `df783dc563b7f00381c35cc5ffe4b367bc7281b612237fdd48fae799bae20b32` | `df783dc563b7f00381c35cc5ffe4b367bc7281b612237fdd48fae799bae20b32` |

  Under version 3 the content and head hashes match too: content `f64ee677…`, head `18018802…`. Under version 2, the frame tokens differed in exactly one place: the hidden `ak_js` input's value (229 against 169). The LiteSpeed comment never reached the hash, since comments were already dropped.
- **Step 2, `AUTHOR_FRAME`** (`ChangeClass`, `src/cernis/history/classify.py`). With content unchanged, a frame change is classed by the page's site type:
  - `wordpress` and `owned`: `AUTHOR_FRAME`.
  - `dev`: `PLATFORM_RENDERING`.
  - `generic`: `UNCLASSIFIED`.

  `HISTORY_VERSION` is 3, so the classifier version is `3+h1`.
- **Step 3, one source for DEV head-field actors.** `actor_for` reads `head_fields.toml` through `CHECK_FIELDS`, which names the head field each check reports on (`src/cernis/checks/peritext.py`). The checks' own DEV table is gone. Release-audit item 23 is marked done. The checks whose actor changed are all on DEV:

  | Check | Actor change | Version |
  |---|---|---|
  | `peri.og.core`, target `og:image` | `AUTHOR` to `UNKNOWN` | 2 to 3 |
  | `peri.title` | `PLATFORM` to `UNKNOWN` | 1 to 2 |
  | `peri.jsonld.parses` | `PLATFORM` to `UNKNOWN` | 1 to 2 |
  | `peri.robots.directives` | `PLATFORM` to `UNKNOWN`, only when it reports a directive under a crawler's name (the robots meta alone stays `PLATFORM`) | 1 to 2 |
  | `epi.og.image.resolves` | `PLATFORM` to `UNKNOWN` | 1 to 2 |
  | `epi.og.image.shared` | `PLATFORM` to `UNKNOWN` | 1 to 2 |

  - **Unchanged:** the canonical checks and `peri.meta.description` (`AUTHOR`); `og:title` and `og:description` (`AUTHOR`); `og:type`, `og:url`, `peri.og.url_matches_canonical`, and `peri.lang` (`PLATFORM`); and every WordPress, owned, and generic actor.
  - **No defect rule changed.** An `UNKNOWN` defect is actionable, as before, so a broken DEV `og:image` now gets a recommendation.
- **Step 4, C-2b:**
  - Fixed in DESIGN.md section 8 before any run: the claim, sample, method, falsifier, and the `AUTHOR_FRAME` note.
  - C-2c (across days) is proposed.
  - The Owner confirmed the pages before the runs.
- **Records:** DESIGN.md is at draft 2.14. CHANGELOG, `docs/RELEASE-AUDIT.md` item 23, and CLAUDE.md are updated.

## Claim C-2b

**Holds.**

| Run | Tip | Receipts |
|---|---|---|
| `20261105T170100Z-29c027` | 3110 | 73: 71 answered 200, 1 answered 403, 1 answered 404, 0 answered 304 |
| `20261105T170208Z-06e5c5` | 3595 | the same |
| `20261105T170314Z-f4d6cc` | 4080 | the same |
| `20261105T170428Z-b351c5` | 4565 | the same |
| `20261105T170537Z-c82466` | 5050 | the same |

- **The four diffs** (1 to 2, 2 to 3, 3 to 4, 4 to 5), each over the ten pages under classifier `3+h1`: every one of the 40 page diffs reported "No changes between these runs." There were 0 change events.
- **`cernis store verify`:** 5050 entries checked, the tip equal to the anchor, `Result: VERIFIED`.
- **Notes (principle 10; C-2's result stands):** one outside link in an article, https://weareroast.com/news/google-search-central-live-deep-dive-barcelona-day-3-recap/, answered 403 in all five runs. It answered 200 in C-2's runs. Since it is the same in every C-2b run, it is no change event.

## Tests seen failing first, on behavior

- **Frame (4):** a hidden input's value moving the frame, for the anti-spam field, a post id, and a mixed-case `type`; and the token test (a hidden input keeps its name, not its value).
  - Passed at once, as guards on existing behavior: the WordPress nonce, Django, and Rails token cases (their names already matched version 2's rule), the 3 comment cases, and the 4 "still a frame change" cases.
- **`AUTHOR_FRAME` (4):**
  - WordPress frame only;
  - WordPress metadata and frame together;
  - a generic page's frame;
  - a diff across the classifier change reading `CHECKER`.

  The first two failed first on the missing class, then on behavior once the enum member existed. The DEV frame test and the owned test passed at once, since both behaviors already held.
- **Actors (14):**
  - the DEV fixture tables (3);
  - the control-file mapping for `og:image`, `json-ld`, `title`, and the two `og:image` resource checks (5);
  - the changed actors (4);
  - a crawler-named robots directive (1);
  - the DEV `og:image` defect test (1).
- **Version and class pins:** `test_change_classes_match_design`, `test_every_check_is_implemented`, `test_the_new_check_versions_are_recorded`, the snapshot hash and version pins, and the `+n3` strings in `test_cli.py`.
- **Golden reports** were regenerated with `CERNIS_UPDATE_GOLDEN=1`, and their diff was read. It contains:
  - the check versions;
  - `+n3`;
  - the DEV fixture's frame hash (its hidden search token lost its value);
  - four DEV actors moving to `UNKNOWN`.

  It adds no recommendation.

## Decisions

1. **The prompt's four decisions were carried out as written.**
   - **Frame normalization:** a general rule, naming no site, plugin, or cache.
   - **`AUTHOR_FRAME`:** a frame change on WordPress and owned pages.
   - **Actors:** the control file is the one source.
   - **C-2b:** the same as C-2 except for the versions.
2. **The comment half of decision 1 was already in place.** Version 2 dropped comments wherever they were, including the LiteSpeed timestamp. Version 3's real change is the hidden values. Both are stated in DESIGN.md section 3.
3. **`AUTHOR` head fields and the frame together on WordPress are `AUTHOR_FRAME`,** as the prompt leaned: one actor made both changes, and the fields are listed as evidence. Content changed together with the frame is still more than one class (`UNCLASSIFIED`), so an edit to the article is never hidden inside a frame change.
4. **`AUTHOR_FRAME` cannot occur on an `owned` page in practice.**
   - An owned page has no body (`content_sha256` is None), and DESIGN.md section 4 makes any change involving such a snapshot `UNCLASSIFIED`.
   - Its frame also holds its article text, so calling its changes "frame" would misname content edits.
   - The `owned` test asserts `UNCLASSIFIED`, with the reason.
   - The class rule names `owned`, so the rule stays right if an owned extractor ever finds a body.
5. **Each check maps to the head field it reports on.** `peri.og.url_matches_canonical` reports on `og:url`, measured against the canonical, so it stays `PLATFORM`.
   - Combining `og:url` (`PLATFORM`) with the canonical (`AUTHOR`) would make it `UNKNOWN`.
   - Since `UNKNOWN` defects are actionable, that would give every DEV copy a recommendation to align `og:url`, which DEV authors cannot do.
   - A finding that reports on fields with different controls is `UNKNOWN`. Today that applies only to `peri.robots.directives` with a crawler-named directive on DEV.
6. **The `og:image` resource checks were included in Step 3.** Their old DEV rule ("DEV's generated social image", `PLATFORM`) was a claim about the `og:image` field that the control file contradicts: it lists `og:image` as `UNKNOWN`, since it is the cover image when one is set. `epi.robots.access` is about robots.txt, not a head field, and stays `PLATFORM` on DEV.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict (84 files)
- pydoclint
- pytest: 1432 passed (1368 before the session; 1410 before the audit's fixes)
- the isolated Python 3.12 pytest: 1432 passed

## Deferred

- **C-2c** (proposed in DESIGN.md section 8, not fixed): the same claim with runs at least 24 hours apart, which is what exercises nonce rotation. Its sample and spacing must be fixed before any run.
- **Crawler-named robots directives on DEV** are `UNKNOWN` because the control file does not list them. The real DEV page had only `robots`. Listing them needs a source.
- **Session 6c's other deferred items** stand: the Windows output encoding, and `csrf-param` and `csrf-token` in the synthetic DEV fixture.
- **Narrowing the hidden-value rule** (audit findings G1 and C2): only by the Owner's decision, since decision 1 chose to drop every hidden value. The trade-off is now stated in the snapshot module and DESIGN.md section 3.
- **WordPress frame changes that are not the author's doing** (finding C1): readers' comments and widgets are in the frame. If a later session wants them out of `AUTHOR_FRAME`, the change is to the frame, not to the class name.

## Audit

**`aud_1vdgpbq7t4`**, mode `standard`, approved by the Owner ("Yes, standard audit."). The artifact was real code only, 95,094 bytes:

- in full: `src/cernis/history/classify.py` and `fields.py`, since their diffs against HEAD also hold Session 6d's audited changes;
- as diffs against `68a71f4`:
  - `snapshot.py`, `model.py`, `peritext.py`, `epitext.py`, and `registry.py`;
  - `test_parse_snapshot.py`, `test_history_classify.py` (without Session 6d's already-audited hunk, as the context said), `test_checks_peritext.py`, `test_checks_epitext.py`, `test_registry.py`, and `test_model.py`.

Three voices:

- gpt-6-sol (G): 2 findings, `has-serious-issues`;
- gemini-3.8-flash-high (M): 3 findings, `has-gaps`;
- claude-sonnet-5-5 (C): 9 findings, `has-serious-issues`.

**9 accepted, 5 rejected.**

| Finding | Claim | Decision | Evidence or fix |
|---|---|---|---|
| G1, C2 | Dropping every hidden value hides real changes, such as a comment form's post id | Accepted in part | The rule is the Owner's decision 1, and the tests assert those cases on purpose. The trade-off is now stated in the snapshot module's docstring and DESIGN.md section 3; narrowing is deferred to the Owner |
| G2, C5 | `peri.og.url_matches_canonical` takes its DEV actor from `og:url` alone, though an author's canonical edit can cause the mismatch | Rejected | Unchanged behavior: the actor has been `PLATFORM` on DEV since Session 4b, and C-3's review found all 21 such defects genuine as `PLATFORM`. A broken canonical is caught as `AUTHOR` by the canonical checks. Mapping both fields would make it `UNKNOWN` and give every cross-post a recommendation its author cannot follow (decision 5) |
| M1, C3 | The classifier's module docstring omits `AUTHOR_FRAME` | Accepted | Rewritten: the classes as applied, including the per-site frame rule and the metadata-and-frame merge |
| M2 | A DEV change of `PLATFORM` fields and the frame together names only the head reason | Accepted | Each class keeps every contributing reason |
| M3 | The finding-version test checks only `peri.lang` and `peri.og.core` | Rejected | `test_every_check_is_implemented` pins every check's registry version, and every finding takes its version from the registry (`check(check_id).version` in `_Context.observed`) |
| C1 | Any WordPress frame change, a reader's comment included, is now the author's | Accepted in part | The class follows the Owner's decision 2 and DESIGN.md section 3 (the actor is who controls a thing). The classifier docstring and DESIGN.md section 5 now say plainly that `AUTHOR_FRAME` names who controls the frame, not who made the change |
| C4 | `owned` is in the frame rule but can never reach it, and the version docstring says otherwise | Accepted | The `HISTORY_VERSION` docstring says owned pages stay `UNCLASSIFIED`. The entry is kept for an owned extractor that finds a body (decision 4) |
| C6 | Actors for WordPress, owned, and generic pages may have changed without a version bump | Rejected | They did not: the control file's defaults (`AUTHOR`, `AUTHOR`, `UNKNOWN`) are the old rule's values. The new pinned table (C7) shows it for every check |
| C7 | The DEV actor test is tautological | Accepted | `test_every_actor_is_pinned_for_every_site_type` pins 18 checks and targets by value, for DEV, WordPress, owned, and no site type |
| C8 | A head hash change with no field change is hidden by a frame change; combinations untested | Accepted | It is now `UNCLASSIFIED` whatever else changed. Tests were added for content with the frame (`UNCLASSIFIED`, decision 3) and for an `UNKNOWN` field with the frame |
| C9 | The real capture pair should be a fixture | Rejected | CLAUDE.md requires synthetic fixtures, never captured from real pages, and the session prompt said never to copy `a.html` and `b.html` into `tests/`. C-2b's limits are stated in its notes ("What it shows") |

**No version bump.** The anomaly fix reaches only a stored record whose head hash disagrees with its fields, which the model refuses for every new snapshot; the reasons change only adds text. No class changes for a valid record, so the classifier stays `3+h1`.

**Tests seen failing first, on behavior:** 2, the DEV reasons and the head anomaly with a frame change. Passed at once, as guards: the two combination tests and the 18-row actor table.

## Not touched

- The content and head normalization; the checks' defect rules; the fetcher; the store's entry schema version.
- C-2's recorded result and its row in section 8.
