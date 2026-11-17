# Session 7: loose ends, C-2c fixed and started, C-4 over a second full audit

**Date:** 2026-11-17
**Phase:** 6 (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

This session closed three carried-over items, fixed claim C-2c and made its first run, and evaluated claim C-4 over a new full audit. **C-4 holds. C-2c is in progress** (run 1 of 5). The Owner approved a `standard` Decision Engine audit before run 1 (`aud_BzbIG6RavZ`): 12 of its 16 findings were accepted and fixed before run 1, and 4 were rejected (Audit, below). The full audit then exposed a run-assembly bug, fixed with a regression test before the audit was run again. That fix changes no check, extractor, or classifier version, so C-2c's later runs see the versions run 1 saw.

The real network requests were the ones the session prompt named: C-2c run 1, and the full audit, made twice (the first attempt stopped on the bug before anything was recorded).

## Done

### Step 1a: the hidden-value decision

- **Decision 1, recorded in DESIGN.md section 3** (next to Session 6e's trade-off text): every hidden value stays dropped from the frame.
  - Why: narrowing the rule by input name would mean guessing, site by site, which names are tokens, and guessing by name is how version 2 missed WordPress's `ak_js`. A hidden value that matters, such as a post id, rarely changes without the URL, the article text, or the head changing too.
  - When to revisit: only if a real case shows a hidden value changing alone when it mattered.
- **Session 6e's deferred item** "Narrowing the hidden-value rule (audit findings G1 and C2)" is **closed** by this decision. SESSION-06e.md is not edited.

### Step 1b: recommendations on `UNKNOWN` defects

**Every template an `UNKNOWN` defect can reach**, found by rendering them through the real recommendation functions (`tests/test_unknown_recommendations.py`):

| Template | On a page with no site type | On DEV |
|---|---|---|
| `peri.canonical.single.keep-one` | yes | no (canonical is `AUTHOR`) |
| `peri.canonical.absolute.make-absolute` | yes | no |
| `peri.canonical.absolute.add-href` | yes | no |
| `peri.canonical.absolute.fix-url` | yes | no |
| `peri.og.core.add-required` | yes | yes, for `og:image` |
| `peri.lang.add-lang` | yes | no (`PLATFORM`, no recommendation) |
| `peri.og.url_matches_canonical.align` | yes | no (`PLATFORM`) |
| `peri.jsonld.parses.fix-json` | yes | yes |
| `epi.canonical.resolves.fix-canonical` | yes | no |
| `epi.og.image.resolves.fix-image` | yes | yes |
| `epi.links.resolve.fix-link` | at function level only: no run reaches it, since links are found only by an article extractor, on DEV or WordPress, where they are `AUTHOR` | no |
| `epi.sitemap.listed.add-page` | yes | no (not checked on DEV) |

The four `epi.pair.canonical` templates are never reachable: the pair check's findings are always `AUTHOR` (`epitext.py:554, 573, 625, 651`).

**Every one of them assumed control, so every one changed.** Each has a conditional wording, registered in `TEMPLATES` as its own template with `variant_of` naming the base (`src/cernis/checks/recommendations.py`). `template_for` chooses it for an `UNKNOWN` actor, a DEV wording before the wording for any site, and raises rather than fall back to the unconditional text.

- Any site: "If you control the page's canonical link, change {href} to an absolute URL, such as {resolved}; if a theme, plugin, or platform writes it, the change is theirs to make."
- DEV, `og:image` broken: "If this image is the post's cover image, replace cover_image in its DEV front matter with the URL of an image that exists; if DEV generated it, only DEV can change it."
- DEV, `og:image` missing: "If the post has a cover image, check cover_image in its DEV front matter, which DEV uses for og:image; if DEV generates og:image for the post, only DEV can change it." It is used only for `og:image`; any other `og:` property takes the wording for any site.
- DEV, JSON-LD: "If the text that breaks JSON-LD block {number} comes from the post's DEV front matter, such as its title, correct it there; if DEV generates it, only DEV can correct it."

**The recommendation keeps the base template's id in its target, so its key does not change with the wording.** An `AUTHOR` defect keeps the direct instruction.

**The test** renders every reachable template and fails on an unconditional instruction. The pattern list is documented in the test module:
- Text is split into clauses at a sentence end, `;`, or `:`.
- An imperative verb at the start of a clause, or after a comma (optionally followed by "and", "or", or "then"), is unconditional unless "if" comes earlier in the same clause. The verbs: add, change, check, correct, delete, edit, ensure, fix, give, make, remove, replace, set, update, use, verify.
- Every conditional wording must also say whose change it is otherwise ("the change is theirs to make", "only DEV can").
- Every base template's action is flagged by the list, so the test cannot pass vacuously.

**Check versions moved**, since what these checks produce changed: `peri.canonical.single` 2, `peri.canonical.absolute` 2, `peri.og.core` 4, `peri.og.url_matches_canonical` 3, `peri.lang` 3, `peri.jsonld.parses` 3, `epi.canonical.resolves` 2, `epi.og.image.resolves` 3, `epi.sitemap.listed` 2, and `epi.links.resolve` 2 (the last after the audit). The golden reports' diff was read: check versions only.

### Step 1c: Windows output encoding

- `main` reconfigures standard output and standard error to UTF-8 when they are text wrappers, keeping each stream's error handler (`errors=stream.errors`; Python 3.12 resets it to `strict` otherwise, verified in this session).
- `--output <file>` is added to `cernis runs`, `history`, and `diff` (the auditing commands already had it), and to `cernis evaluate c4`. An unwritable file exits 2, as for the auditing commands.
- **Tested with redirected subprocesses** (`tests/test_cli_encoding.py`): `python -m cernis runs` and `history` with `PYTHONIOENCODING` forced to cp1252 and to ASCII, reading the raw bytes. Before the fix, cp1252 wrote the bare byte `B7` and ASCII crashed with `UnicodeEncodeError`; after it, both write `C2 B7`.
- **What was run on Windows**, against the real store:
  - Git Bash, `uv run cernis runs > file`: before the fix, 12 lines with the bare cp1252 byte and none in UTF-8; after it, all 12 in UTF-8.
  - Windows PowerShell 5.1:
    - `--output`: UTF-8.
    - `cmd /c "uv run cernis runs > file"`: UTF-8.
    - PowerShell's own `>`: correct with the console at code page 65001. With `[Console]::OutputEncoding` set to code page 437, PowerShell re-decoded Cernis's UTF-8 bytes and wrote 24 `┬╖` pairs instead of the middle dots.

  The last case is PowerShell's decoding, outside Cernis. The README and CHANGELOG say so, and the C-2c procedure uses `--output` throughout.

### Step 2: C-2c

1. **Fixed in DESIGN.md section 8**, dated 2026-11-17, before run 1, and moved out of Proposed. Its parts:
   - the claim, and C-2's ten pages listed by URL;
   - the method: five runs, each at least 24 hours after the previous counted run, measured between `started_at` times in the store; and, at the Owner's request, each later run at the same time of day (UTC) as run 1 or later;
   - the planned dates (Tuesday November 17, Wednesday 18, Thursday 19, Friday 20, and Monday 23);
   - the exclusion rule for a run started too soon;
   - the falsifier, and the scope note that a `RESOURCE` cause counts;
   - the conditions (no edits, no publishing, incomplete rather than falsified if either happens, reader comments excluded by timestamp only, more than two excluded pages makes it incomplete).
2. **The daily procedure** is `docs/experiments/2026-11-c2c.md`:
   - the schedule, with a line per run;
   - the 24-hour check from `cernis runs --format json --output`;
   - one exact command per day, each refusing to run if its dated cache directory exists;
   - the record step, which reads the report and runs `cernis store verify`;
   - the four diff blocks, with explicit `--from` and `--to` placeholders, and a filter listing every diff that is not "No changes";
   - the reader-comment steps;
   - the full audit's run id, marked as not a C-2c run.

   Its 24-hour check, record step, diff loop, and filter were run in PowerShell 5.1 against C-2b's stored runs before run 1. The day-1 command and record step were then run exactly as written. The Owner corrected the weekdays (November 17, 2026 is a Tuesday).
3. **The Owner confirmed** the ten pages unedited since November 5, no edits before November 23's run, and nothing published on kenwalger.com or DEV before then.
4. **Run 1:** `20261117T154815Z-407563`, started 2026-11-17T15:48:15Z.
   - Tip: 5535 `3c1f2036282551edea6214b2a0993f50e7a58a179fe3de8861508acf65b4a1e5`.
   - Receipts: 73. 71 answered 200, 1 answered 403 (the weareroast.com link C-2b also saw), 1 answered 404 (https://rust-lang.org/robots.txt), none 304.
   - `cernis store verify`: 5535 entries, tip equal to the anchor, `Result: VERIFIED`.
   - **Earliest time for run 2:** 2026-11-18T15:48:15Z.

### Step 3: C-4 over a second full audit

1. **The full audit** used Session 5c's command (`cernis pairs --from-dev-user kenwalger --limit 25 --map reports\kenwalger-map.toml`), a fresh cache, and the normal settings, after C-2c's run 1.
   - The first attempt (`20261117T155012Z-d7bf76`) stopped on `RunError: more than one snapshot of one receipt` and was never recorded (Decision 3).
   - The recorded run is **`20261117T155809Z-2105cd`**: tip 7321; 22 pairs; 44 subjects; 162 receipts (155 answered 200, 1 answered 403, 6 answered 404); 43 snapshots.
   - **It is not a C-2c run.** That is stated in DESIGN.md section 8 and in `docs/experiments/2026-11-c2c.md`.
2. **`src/cernis/evaluate/c4.py`**, with `cernis evaluate c4 --run <id>`. It reads the run's stored finding records back with verification on and checks the four rules. It reads the records themselves, not findings rebuilt through the model, which refuses to build a violating finding. The no-promise patterns are imported from `cernis.promises`.
   - The rules were fixed in DESIGN.md section 8 before the run. Rules 1 and 2 are the stated falsifier; rules 3 and 4 were added before the run, and a violation of any of them falsifies.
   - Tests on synthetic stored runs break each rule. After the audit, they also cover malformed records: non-text, empty, or duplicate ids, `based_on` that is not a list, empty evidence entries, `defect: 0`, and non-text recommendation text.
3. **C-4 holds.** 1580 findings: 1519 `OBSERVED`, 3 `RECOMMENDATION`, 58 `NOT_DETERMINABLE`.

   | Rule | Checked | Violations |
   |---|---|---|
   | `based_on` | 3 | 0 |
   | `no_promise` | 3 | 0 |
   | `not_determinable` | 58 | 0 |
   | `status_fields` | 1580 | 0 |

   No violation, so no sign of a gap in model validation. The three recommendations are all on `AUTHOR` defects, so this run did not exercise the conditional wordings.
4. **For information, not a claim** (DESIGN.md section 8, "The second full audit"):

   | Check | Actor | Session 5c | Session 7 |
   |---|---|---|---|
   | `peri.og.url_matches_canonical` | `PLATFORM` | 21 | 22 |
   | `epi.links.resolve` | `AUTHOR` | 0 | 2 |
   | `epi.sitemap.listed` | `AUTHOR` | 0 | 1 |
   | any | `UNKNOWN` | 0 | 0 |

   - The `PLATFORM` count follows the number of DEV copies.
   - The `AUTHOR` defects are on 3 of 44 articles, all newer than November 2:
     - one outside link that now redirects to a 404, in "Plan Stamping for Software" and its DEV copy;
     - today's post, not yet in the sitemap.
   - Session 6e's actor changes put no defect in `UNKNOWN` here.
   - C-1 and C-3 were not evaluated again, and their results stand.
   - **A false negative, recorded as a fact.** The DEV copy of "A Word List Tied the Model" names https://www.kenwalger.com/blog/developer-relations/a-word-list-tied-the-model/A as its canonical, with a stray `/A`.
     - WordPress redirected that URL to a different article, "A Message From Our Founder" (`.../ai-engineering/a-message-from-our-founder-laasy/`), by guessing a post from the last path segment. The run's own receipt shows the redirect.
     - `epi.pair.canonical` counts a redirect as `EQUIVALENT`, so it reported two facts and no defect.
     - Nothing was reclassified (principle 10).

## Tests seen failing first, on behavior

- **1b, conditional wording:**
  - Failed first: 4 tests, with the selector briefly falling back to the base text so the failure was on the text itself. They were the unconditional-instruction test (generic and DEV), the DEV wording test, and the key-stability test.
  - Failed first on the old versions: the version pins (`test_every_check_is_implemented`, `test_the_new_check_versions_are_recorded`, the report header pin), then the golden reports.
  - Passed at once, as guards: the pattern-list cases and the reachable-set tests.
  - A test bug was fixed on the way: the DEV rendering first forced canonical and link defects to `UNKNOWN`; their actors now come from `epi_actor`.
- **1c, encoding:**
  - Failed first: 4 subprocess tests (runs and history, under cp1252 and ASCII), the six `--output` tests, and the unwritable-file test, since the option did not exist.
  - Passed at once, as a guard: the store verify and diff test, since their output is ASCII.
- **C-4 evaluator:** **the module was written before its tests**, out of order. To make up for it, all 29 tests were run against a copy with every rule's violations and the exit code disabled. 21 failed. The 8 that passed are guards on correct behavior: a well-formed run holds, `would_require` alone holds, a partial run is refused, a real run holds, the patterns are imported, usage errors, and exit codes 0 and 2.
- **Audit fixes:**
  - Failed first, 13: the `epi.links.resolve` version (registry pin and the new rule that a check with a conditional wording is past version 1), the DEV `og:title` wording, 9 evaluator cases (non-text, not-a-list, duplicate, and empty ids; non-text summary and rationale; an empty evidence entry and one with no receipt; `defect: 0`), and the error-handler test.
  - Passed at once, as guards: the clause and hedge tests, and the evaluate `--output`, unwritable-file, and tampered-store tests.
- **Run-assembly bug:** the regression test (a target that redirects to another target) failed first with the same `RunError` as the real run. After the snapshot fix, it failed again on a duplicate key, since both subjects had become the first target's URL, which exposed the second half of the bug.

## Decisions

1. **The prompt's three decisions were carried out as written:** hidden values stay dropped, C-2c is fixed as specified, and C-4 is evaluated over a new full audit.
2. **Conditional wordings are separate registered templates, not a field on the base.** Every text is a whole template that the no-promise and template-registration tests already scan, and the target keeps the base id so keys do not change.
3. **The run-assembly bug was fixed during the session, after run 1, because the full audit could not run without it.**
   - **The two parts:** a run keeps one snapshot per receipt, and each target's subject is its own URL in the form the fetcher records (`request_form`), never the URL of another target whose fetch it reused.
   - **C-2c is unaffected.** No check, extractor, classifier, or Cernis version changed. The golden reports are unchanged, since a fresh fetch's subject is the same as before by construction, and C-2c's pages do not redirect to one another.
   - **Not audited.** The fix came after the audit.
4. **The C-4 rules were stated as falsifiers in DESIGN.md before the run.** That makes the claim harder to pass, not easier.
5. **The Owner's weekday correction and time-of-day rule** were added to DESIGN.md's C-2c method as well as the procedure. Both were added before any run.

## Audit

**`aud_BzbIG6RavZ`**, mode `standard`, approved by the Owner ("Audit first: run the standard audit now, include the tests as proposed").
- **The artifact:** real code only, 100,894 bytes, with the tests. In full: `recommendations.py`, `recommend.py`, and `evaluate/__init__.py` and `c4.py`. As diffs against HEAD: `cli.py`, `registry.py`, `audit.py`, and `sitemap_listed.py`. The three new test files in full.
- **The voices:** gpt-6-sol (G), 3 findings; gemini-3.8-flash-high (M), 5; claude-sonnet-5-5 (C), 8. All three said `has-serious-issues`.

**12 accepted, 4 rejected.**

| Finding | Claim | Decision | Evidence or fix |
|---|---|---|---|
| G1, M1, C1 | `epi.links.resolve` got a conditional wording without a version bump | Accepted | Version 2, plus a test that every check with a conditional wording is past version 1 |
| G2 | An evidence list of empty objects counts as an attempt | Accepted | An attempt needs an entry naming a receipt and a location |
| G3 | A non-text `based_on` id is coerced with `repr` and can resolve | Accepted | Reported as not a finding id |
| M2 | `defect: False` on a non-`OBSERVED` record is a cross-status field | Rejected | Every stored record carries every field (`finding_as_dict`), with `False` and `None` as the empty values, so this would flag every real run. The `0 == False` part (C8) is accepted |
| M3, C3 | The DEV `og.core` wording assumes `og:image` | Accepted | Used only for `og:image`; tested with an `UNKNOWN` `og:title` on DEV |
| M4 | `main` ignores `args.claim` | Rejected | The required subparser allows only `c4`, so the dispatch is complete |
| M5, C7 | Missing tests: evaluate `--output`, JSON with violations, a tampered store, an unwritable file, more verbs, versions | Accepted | All added, and the docstring that said "two" findings fixed |
| C2 | `reconfigure(encoding=...)` resets `errors` to `strict` | Accepted | Verified on Python 3.12. Each stream keeps its handler; tested |
| C4 | A missing wording aborts the run; pair admits `UNKNOWN` | Rejected | Pair findings are hard-coded `AUTHOR` at four sites. Failing loudly is deliberate: a silent fallback would give the unconditional text this session removed |
| C5 | The "if" check is sentence-wide; verbs missing; no positive hedge | Accepted | Checked clause by clause; check, ensure, and verify added; a hedge required |
| C6 | The DEV rationales assert DEV's behavior without a source | Rejected | Both are the sourced entries of `head_fields.toml` (`og:image`, `json-ld`) |
| C8 | Malformed records: duplicate or empty ids, a non-list `based_on`, `0` as absent, non-text text | Accepted | Each now a named violation, and tested |

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict (89 files)
- pydoclint
- pytest: 1510 passed (1432 before the session)
- the isolated Python 3.12 pytest: 1510 passed

## Deferred

- **C-2c runs 2 to 5** (November 18, 19, 20, and 23, at 15:48 UTC or later), its four diffs, the reader-comment check, and its result. The Owner makes them from `docs/experiments/2026-11-c2c.md`.
- **`epi.pair.canonical` and a redirect to another article.** A redirect makes two URLs `EQUIVALENT` (DESIGN.md section 3), even when the redirect lands on a page whose own canonical names a different article. Whether that should stay a fact is the Owner's decision. A change would be a new check version, made for its own reasons and recorded before the run it applies to.
- **Proposed audit:** a `fast` audit of the run-assembly fix (`audit.py`, `request_form` and the snapshot rule, with its test), which no audit has covered. It changes no version, so it can run at any time.
- **Session 6c's other deferred item stands:** `csrf-param` and `csrf-token` in the synthetic DEV fixture. The Windows output encoding item is closed.
- **Crawler-named robots directives on DEV** remain `UNKNOWN` (Session 6e).

## Not touched

- C-1's, C-2's, C-2b's, and C-3's recorded results.
- The frame, content, and head normalization; the classifier (`3+h1`); the fetcher; the store's entry schema.
- Every defect rule.
- No earlier session record.
