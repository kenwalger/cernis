# Session 4b: Phase 3, part two (findings and reports)

**Date:** 2026-10-30
**Phase:** 3 (DESIGN.md draft 2.4, sections 2, 3, 4 peritext, and 7)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

Snapshots become findings, findings become a validated run, and the run becomes a report. Epitext checks remain Phase 4. No Decision Engine audit, as the session prompt required. The only real requests were the two audits at the end.

## Built

- **Site types.** `cernis audit --site-type dev|wordpress` declares the site type of every URL given; `docs/PAIR-MAP.md` defines the pair map, a TOML file (`format = 1`, `[[pair]]` with `original` and `copy`, each a `url` and an optional `site`), and `src/cernis/pairs.py` loads it strictly (unknown keys, bad URLs, unknown sites, a copy equal to its original, and conflicting declarations are errors naming the pair). A declaration overrides host detection. `Snapshot.extractor_selection` (`declared`, `host`, or `generic`) records how the extractor was chosen.
- **The nine peritext checks** (`src/cernis/checks/peritext.py`), each following the "Reports" and "Defect when" columns of DESIGN.md section 4: `peri.canonical.present`, `.single`, and `.absolute`; `peri.meta.description`; `peri.og.core` (one finding per property, the property as target); `peri.og.url_matches_canonical` (the shared URL comparison, with the page's redirect chain); `peri.lang`; `peri.jsonld.parses` (one finding per block, targets `block 1`, `block 2`, ...); and `peri.title`. Defects come only from `canonical.single` (more than one canonical, not all IDENTICAL or EQUIVALENT), `canonical.absolute` (relative or malformed), `og.url_matches_canonical` (DIFFERENT), and `jsonld.parses` (a block that does not parse); everything else is an observed fact with `defect` false. Absent elements are evidence of a search. The registry marks the nine implemented, still at version 1.
- **Fetch outcomes as findings** (`src/cernis/checks/outcomes.py`). A page Cernis did not see whole gets one `NOT_DETERMINABLE` finding per peritext question (12, counting each `og:*` property), with the receipts as evidence and no check run: `DISALLOWED_BY_ROBOTS` (with the robots.txt rule), `ADDRESS_REFUSED` (with the refusal reason), `RATE_LIMITED` (every attempt's status and `Retry-After`), `ACCESS_DENIED` (401, 403), and `FETCH_FAILED` (timeout, connection, TLS, too many redirects, a truncated body, any other non-2xx status, or a 304 with no cached copy).
- **Recommendations** (`src/cernis/checks/recommend.py`) from six new templates in `TEMPLATES`: `peri.canonical.single.keep-one`, `peri.canonical.absolute.make-absolute`, `.add-href`, and `.fix-url`, `peri.og.url_matches_canonical.align`, and `peri.jsonld.parses.fix-json`. Each rests on the observed defect it addresses (`based_on`), is phrased as an action, and cites RFC 6596, the Open Graph protocol, W3C JSON-LD 1.1, or the page's own evidence. The no-promise test covers all seven templates.
- **Run assembly** (`src/cernis/audit.py`) and **`Run`** (`src/cernis/model.py`). A run has an id (its start time, `20261030T120000Z`), start and finish times, the Cernis version, its subjects, receipts (robots.txt receipts once each), snapshots, and findings with ids `f-001`, `f-002`, .... It validates at construction and raises `RunError` (a `ModelError`) when receipt or finding ids repeat, keys repeat, a finding is about a URL the run did not audit, evidence names a receipt not in the run, a `based_on` id is missing or not `OBSERVED`, a snapshot names a receipt not in the run, or the times are not UTC and in order. The audit lets that error propagate: a run that fails is never emitted.
- **Reports** (`src/cernis/report/`). JSON (`cernis-report`, format version 1): the run, every check version used, subjects, plain counts per section, and every finding (with its key), receipt, and snapshot, whole. Markdown, after DESIGN.md section 7: a header with the run id, Cernis version, check versions, and how each subject was read; then Observed, Recommendations, and Not determinable (non liquet), each with a count and split by subject when there are several. `based_on` is rendered as check id plus summary; evidence values are shown in code spans, cut at 160 characters (the JSON has them whole); page text is escaped. A page's twelve not-determinable findings, which share one reason and one piece of evidence, are shown as one item listing every question.
- **CLI.** `cernis audit <url> [<url> ...] [--site-type dev|wordpress] [--format md|json] [--output <file>] [--cache-dir PATH] [--allow-loopback]`. Exit 0 whatever was found; 2 for a URL that cannot be fetched at all or an output that cannot be written. `receipt_as_dict` moved from the CLI to the JSON report module, which `cernis fetch` now imports.
- **Tests.** `tests/test_checks_peritext.py` lists every expected finding (check, target, status, defect, actor, summary) and recommendation for all ten fixtures, written by hand from the fixtures and DESIGN.md before the checks existed; it allows long lines (ruff E501) so each finding stays one row. `tests/test_audit.py` covers each fetch outcome end to end through the real fetcher on scripted transports, and a run that breaks a rule raising instead of being emitted. `tests/test_model.py` tests each run rule. `tests/test_reports.py` compares both formats with golden files (`tests/golden/audit.md`, `tests/golden/audit.json`: a DEV page, a declared WordPress page with a defect and its recommendation, and a page that times out; a fixed clock and fixed ids), regenerated only with `CERNIS_UPDATE_GOLDEN=1`. `tests/test_pairs.py` covers the pair map rules and loads the example in `docs/PAIR-MAP.md`.

## Decisions

1. **An unread page gets one non liquet per question, not one in all.** Each carries the key the check's own finding would have, so when a later run reads the page, history (Phase 5) sees each question go from `NOT_DETERMINABLE` to `OBSERVED` instead of a "fetch" finding vanishing and twelve new ones appearing. The Markdown report shows them as one item, so the reader sees one failure.
2. **A 404, 410, or 5xx for the subject page is `FETCH_FAILED`**, with the status as evidence. DESIGN.md lists 5xx under `FETCH_FAILED` and has no code for "the article itself is gone"; the status is on record either way. A truncated body is also `FETCH_FAILED` (with `body_truncated_at` as evidence), because no reason code says "too large".
3. **Recommendations only for defects the author can act on** (`AUTHOR` or `UNKNOWN`). A `PLATFORM` defect is reported as observed with no recommendation.
4. **Actors.** WordPress: `AUTHOR` for everything. DEV: `AUTHOR` for what the front matter sets (canonical, description, and the title, description, and cover image behind `og:title`, `og:description`, and `og:image`); `PLATFORM` for the template (`og:url`, the og:url comparison, `lang`, JSON-LD, and `<title>`, which DEV builds as "title - DEV Community"). No known site type: `UNKNOWN`. robots.txt outcomes follow the same split; other fetch outcomes are `UNKNOWN`.
5. **`peri.canonical.absolute` gives no finding when there is no canonical**, since there is nothing to assess; `peri.canonical.present` and `.single` record the absence. A canonical with no `href` counts for `present`, has no value for `single`, and is malformed for `absolute`.
6. **A relative canonical is resolved against the page's URL** before `og.url_matches_canonical` compares it (and the summary says so), since that is what it means to a browser; `canonical.absolute` still reports it as a defect. `<base href>` is not read.
7. **Two canonicals that disagree make `og.url_matches_canonical` `AMBIGUOUS`** (`NOT_DETERMINABLE`), since which one `og:url` should match cannot be told. DESIGN.md's `AMBIGUOUS` example is exactly this.
8. **Lengths** (description, title) are characters after whitespace is collapsed and NFC applied, the text a reader sees.
9. **Finding targets.** Recommendations take the template id, then `:` and what they are about (`canonical 2`, `block 3`), so every finding in a run has its own key. JSON-LD blocks are `block N` by position, so a block added before others shifts the targets; history will see that as blocks changing.
10. **Findings never quote the JSON decoder.** The isolated Python 3.12 run caught this: Python's `json` module words the same error differently on 3.12 and 3.13 ("Expecting property name enclosed in double quotes" at column 44, against "Illegal trailing comma before end of object" at column 42), so a summary quoting it made the same page give different findings on different Pythons, the problem the RFC 9309 matcher fixed in Session 3b. `JsonLdBlock.error` is now Cernis's own fixed wording (`not valid JSON`, `the block is empty`, `nested too deeply to read`); the decoder's message and position move to `JsonLdBlock.detail` and `ParsedPage.problems`, which no finding uses. `test_json_ld_errors_are_worded_the_same_on_every_python` locks it.

## For the Owner

- **`peri.og.url_matches_canonical` reports a defect on every DEV cross-post.** DEV sets `og:url` to the DEV URL; an author who points the canonical at the original (the point of the pair check) gets `og:url` DIFFERENT from the canonical, which the section 4 table calls a defect. This session implements the table as written, marks the finding `PLATFORM`, and makes no recommendation. The real dev.to audit below shows it. Whether the table should treat this case differently (for example, no defect when the canonical names a declared original) is a DESIGN.md decision.

## Real requests

Two audits, the only real requests of the session, each fetching robots.txt and the page.

**`cernis audit https://kenwalger.com/ --site-type wordpress`** (run `20261030T151931Z`): read whole (receipt `r-002`), extractor `wordpress.entry 1+n1`, declared. Observed (11), no defects: no canonical link; a meta description of 158 characters; no `og:title`, `og:description`, `og:image`, or `og:url`; neither an `og:url` nor a canonical to compare; no `lang` attribute on `<html>`; one JSON-LD block that parses, with `@type` values Person, WebSite, CreativeWork, SoftwareApplication; a title of 19 characters ("Ken W. Alger | Home"). Recommendations (0). Not determinable (0). `peri.canonical.absolute` gave no finding, as there is no canonical.

**`cernis audit https://dev.to/kenwalger/views-measure-views-4co7`** (run `20261030T151942Z`): read whole (receipt `r-002`), extractor `dev.article 1+n1`, host. Observed (12): one absolute canonical, `https://www.kenwalger.com/blog/writing/views-measure-views-nine-years-writing`; a description of 142 characters; all four `og:*` present; **DEFECT · PLATFORM**: `og:url` (the DEV URL) and the canonical are different (see "For the Owner"); `lang` `en`; one JSON-LD block, `@type` Article (44,654 characters); a title of 35 characters. Recommendations (0). Not determinable (0).

Both full Markdown reports were shown to the Owner in the session.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (55 files), pydoclint, pytest (914 passed), and the isolated Python 3.12 pytest (914 passed). An isolated Python 3.13 run also gives 914 passes.

## For the pre-0.1.0 release audit (additions)

To the lists in `SESSION-03b.md` and `SESSION-04a.md`, add:

13. **The peritext checks against DESIGN.md section 4**: every "Defect when" condition, and that nothing else sets `defect`; the edge cases in decisions 5 to 7; and the actor table (decision 4) against what DEV's front matter and template actually control.
14. **Fetch outcomes**: the mapping from fetch results to reason codes (decision 2), that no check can run on a page not seen whole, and the evidence each outcome carries.
15. **Run validation**: that every rule in `Run.__post_init__` holds for every run `audit` can build, and that a failure cannot be swallowed between assembly and a report.
16. **Recommendation templates**: their citations (RFC 6596, Open Graph, JSON-LD 1.1) for accuracy, their phrasing against the no-promise rule beyond the phrase list, and the choice to skip `PLATFORM` defects (decision 3).
17. **The reports**: the JSON format as a contract (field names, version policy), Markdown escaping of page text, and grouping of not-determinable findings.
18. **The pair map loader** (`pairs.py`) as untrusted input.

## Deferred

- **The DEV og:url defect** (For the Owner, above).
- **`cernis pairs --map`**: the format and loader exist; the command and the pair check are Phase 4.
- **The Markdown subject line** does not say whether the extractor found an article body (`content_sha256` is in the JSON report); worth adding with the next report change.
- **Non-HTML responses** (a 200 with a `Content-Type` that is not HTML) are parsed like HTML. No fixture covers it; a `FETCH_FAILED` or a new outcome may suit it better.
- **`<base href>`** is not used to resolve relative canonicals (decision 6).

## Not touched

- `img/` and `BRAND.md` (the Owner's brand work, committed separately).
- The fetcher and the parser, apart from `select_extractor` and `effective_site` in `extractors.py`.
