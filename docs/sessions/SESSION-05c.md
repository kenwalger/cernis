# Session 5c: the first site-wide audit

**Date:** 2026-11-02
**Phase:** 4 to 6 (DESIGN.md draft 2.7, sections 2, 3, 4, 7, 8, and 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

The claim numbers fixed, three changes the first full audit needed, and that audit. There was no Decision Engine audit, as the session prompt required. The only real requests were the one command the prompt named. C-1 and C-3 were not evaluated: the Owner reviews every defect by hand first.

## Built

- **Claim numbers fixed before any real run** (DESIGN.md section 8, dated 2026-11-02, replacing "proposed"):
  - C-1 is falsified if fewer than 10% of audited articles have any `AUTHOR` defect.
  - C-2 is 5 back-to-back runs.
  - C-3 is falsified if fewer than 95% of the first full audit's defects are genuine on the Owner's review.
- **`wordpress.entry` version 2.** Share-button containers are left out of the article body, for both the content hash and the links `epi.links.resolve` checks: Jetpack's `.sharedaddy`, `.sd-sharing-enabled`, and sharing block; AddToAny; Sassy Social Share; Shared Counts; Social Warfare; ShareThis; and the Social Sharing block (`WORDPRESS_SHARE_CONTAINERS`). The excluded elements are skipped during the walk (by `mem_id`), not removed from the tree, so the frame hash is computed as before. Snapshots now record `wordpress.entry 2+n1`, which history will classify as a `CHECKER` change.
- **Audit finding D4, decided:** a `[[site]]` prefix covering a whole origin makes the whole site one section for `epi.sitemap.listed`. This is what `section_of` already did; a test pins it and DESIGN.md says so.
- **Site-level findings.** `epi.og.image.shared` (version 1, registered, listed in `SITE_LEVEL`) gives one observed fact, never a defect, when two or more audited articles on one origin share an `og:image` URL (compared after normalization). It lists the articles, with each one's `og:image` tag as evidence. Its subject is the first article in run order and its target is the image URL. Reports show it in a new Site section and not under any page. The JSON report adds `counts.site`, the number of site-level observed findings; `counts.observed` keeps its meaning (every observed finding), so the format version stays 1.
- **The run summary.** Every report now starts with a Summary section: each article's count of `AUTHOR` defects (zero included), then "Articles with at least one AUTHOR defect: N of M". The JSON report has the same in `summary` (`author_defects`, `articles`, `articles_with_author_defects`). These are plain counts, never weighted or turned into a percentage; DESIGN.md principle 2 now says so.
- **Tests:** 1115 in all.
  - Share-button exclusion: links and text for three plugins, and the content hash with and without a widget.
  - The shared `og:image` fact, its absence when images differ, and the Site section.
  - The summary counts, checked against the findings.
  - The whole-origin section.
  - The goldens were regenerated, and the diff was read before accepting it: the extractor version, the summary (2, 2, 0, so 2 of 3; checked by hand: the DEV page's two broken links, and the two-canonicals page's conflicting canonicals plus its dead dev.to canonical), and an empty Site section.
- **`reports/`** holds real audit reports locally. It is in `.gitignore`, so reports of real pages are never committed.
- **Docs:** DESIGN.md draft 2.7, README, CHANGELOG, and CLAUDE.md.

## Decisions

1. **A site-level finding needs a subject**, because a run validates every finding against its subjects. The first article of the set, in run order, is the subject, so the key stays stable while that article leads the set. The Site section keeps it from reading as a fact about that one page.
2. **Shared images are grouped by origin**, not by `[[site]]` prefix. A shared image is a site's default, and a whole site has one, whatever part of it the prefix names.
3. **The JSON format version stays 1.** `summary` and `counts.site` are additions, and no field's meaning changed.
4. **Excluded containers are skipped, not removed**, so the snapshot's frame hash and the page's other findings are unchanged.

## Real request

`cernis pairs --from-dev-user kenwalger --limit 25 --map reports/kenwalger-map.toml`, where the map holds only `[[site]] prefix = "https://www.kenwalger.com/blog/" type = "wordpress"`. Run `20261102T204509Z`, from 20:45:09 to 20:47:59 UTC, exit 0.

**The full report is at `reports/2026-11-02-pairs-kenwalger.md`** (6543 lines).

- **The listing:** 25 published articles. 21 are cross-posted, so there are 21 pairs and 42 articles, all read whole. The other 4 are noted as not cross-posted because their canonical URL is the DEV article itself:
  - Building an Enterprise AI Governance Stack
  - Enterprise MCP Gateway
  - A Wine Cellar That Remembers
  - Why User Provisioning Matters
- **The summary:** every article has 0 `AUTHOR` defects. "Articles with at least one AUTHOR defect: 0 of 42."
- **Site (1):** 15 of the 21 originals share the og:image `https://www.kenwalger.com/blog/wp-content/uploads/2017/01/cropped-logo-3.png`.
- **Observed (1446).** All 21 defects are `PLATFORM` `peri.og.url_matches_canonical` defects on the DEV copies (DEV sets `og:url`), with no recommendation.
- **The pair checks:**
  - All 21 copies name their original exactly.
  - 18 originals have a canonical identical to the URL DEV gave; 3 differ only by a trailing slash, which is equivalent and not a defect.
- **The sitemap check** found the blog's own sitemap (`/blog/sitemap-1.xml`) and lists all 21 originals: 18 identical, 3 equivalent by a trailing slash. This confirms the Session 5b discovery fix.
- **Links:** 84 article-body links answered and were reported.
- **Recommendations (0).**
- **Not determinable (57):**
  - 32 are `LIMIT_REACHED`, from the 5-links-per-external-host budget across the run.
  - 24 are `DISALLOWED_BY_ROBOTS`:
    - 20 are share links on 5 of the 21 WordPress originals (Facebook, X, Reddit, LinkedIn).
    - 4 are `pitching-stats.onrender.com`, which disallows Cernis.
  - 1 is `ACCESS_DENIED`: weareroast.com answered 403.

**Share links that version 2 did not exclude.** On 5 posts (Sixty Feet Six Inches of October, A Message From Our Founder, Four Ways a Test Can Lie, Your Website Changed, Nothing Reported It), share links inside `.entry-content` were still checked. Their container matches none of the selectors added this session. Those pages were not in the cache (their responses carried no validator), so their markup could not be inspected without another request, and none was allowed. The links are reported, correctly, as `DISALLOWED_BY_ROBOTS`, never as defects. Naming their container is deferred; see below.

C-1 and C-3 are not evaluated here, as the prompt required.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (68 files), pydoclint, pytest (1115 passed), and the isolated Python 3.12 pytest (1115 passed).

## For the pre-0.1.0 release audit (additions)

33. **`wordpress.entry` 2**: the share-container list against the plugins in use, and the skip-by-`mem_id` walk.
34. **Site-level findings**: decision 1 (a subject for a set) and whether Phase 5 history should key them differently.
35. **The run summary** against principle 2.

## Deferred

- **The share container on 5 posts**, for the Owner. Look at one of those posts' markup (or name the plugin), and add its container to `WORDPRESS_SHARE_CONTAINERS`; the extractor version becomes 3.
- **The per-host link budget** across a 42-article run left 32 links unchecked (`LIMIT_REACHED`). Raising `--max-links-per-host` is the Owner's choice.
- **C-1 and C-3**: the Owner's review of every defect in the report above.
- **SDK friction:** none this session; the SDK was not used.

## Not touched

- The fetcher, the URL comparison, finding keys, and every check other than those named above.
- No ADR was changed.
