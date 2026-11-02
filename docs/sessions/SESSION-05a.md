# Session 5a: Phase 4, part one: the cross-post pair check

**Date:** 2026-11-02
**Phase:** 4 (DESIGN.md draft 2.5, sections 3, 4, 6, 7, and 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

The flagship check, the two resolution checks around a page, the `owned` site type, and the pair commands. No Decision Engine audit, as the session prompt required; this session's scope is added to the pre-0.1.0 audit list below. The only real requests were the one `cernis pair` run at the end.

## Built

- **The `owned` site type** (`SiteType.OWNED`): for pages the author fully controls that have no specific extractor. It uses the generic extractor, and every finding's actor is `AUTHOR`, including fetch outcomes (robots.txt, refusals, failures), which are `UNKNOWN` for an undeclared generic page. It works in the pair map (`site = "owned"`), in `[[site]]` prefix rules, and in `--site-type`. `docs/PAIR-MAP.md` documents it.
- **`peri.og.url_matches_canonical` version 2.** A `DIFFERENT` defect's summary now cites the Open Graph protocol, which defines `og:url` as the object's canonical URL, the same way `peri.lang` cites WCAG. DESIGN.md's row says so, and notes that DEV cross-posts always show this defect as `PLATFORM` with no recommendation, because DEV controls `og:url` (the Session 4b Owner item).
- **Pairs.** The map's `[[pair]]` entries become runs: `cernis pair --original URL --copy URL [--original-site TYPE] [--copy-site TYPE] [--map FILE]` and `cernis pairs --map FILE`, both with `--format`, `--output`, `--cache-dir`, and `--allow-loopback`. A pair run audits both pages with every peritext check, runs `epi.canonical.resolves` and `epi.og.image.resolves` for each page, then `epi.pair.canonical`. `Run.pairs` (`RunPair`, validated: both URLs are subjects, different, and no pair repeats) and the JSON report's `pairs` field record them. The Markdown report presents each pair as one subject: `### Pair: <copy> (copy of <original>)`, then `#### Original`, `#### Copy`, and `#### The pair`; a single-pair report's header names the copy and the original, and its title is the original's.
- **`epi.pair.canonical`** (`src/cernis/checks/epitext.py`): two findings, targets `copy` and `original`. The copy's canonical is compared with the original's URL, and the original's canonical with its own URL, by `compare_urls`, with every receipt of the run available as redirect evidence. `DIFFERENT`, or a copy with no canonical, is a defect, actor `AUTHOR`; `EQUIVALENT` is a fact naming each normalization that mattered, or the redirect and its receipt. An original with no canonical is a fact. Canonicals that disagree on one page make that side `AMBIGUOUS`. When the original cannot be read whole, both findings are `NOT_DETERMINABLE` with the original's reason code (`FETCH_FAILED`, `ACCESS_DENIED`, `RATE_LIMITED`, `DISALLOWED_BY_ROBOTS`, `ADDRESS_REFUSED`, and so on); when only the copy cannot, the copy's finding is.
- **Recommendations.** `epi.pair.canonical.set-dev-canonical-url` (set `canonical_url` in the DEV front matter), `epi.pair.canonical.add-copy-canonical`, the existing `epi.pair.canonical.set-copy-canonical` (for a copy off DEV), `epi.pair.canonical.set-original-canonical`, `epi.canonical.resolves.fix-canonical`, and `epi.og.image.resolves.fix-image`, all in `TEMPLATES` and covered by the no-promise test.
- **`epi.canonical.resolves`**: each distinct canonical (resolved, deduplicated by normalization) is fetched through the normal fetcher: robots.txt, the address screen, pacing, retries, the deadline. The finding reports the status and the full redirect chain (as evidence, hop by hop); a redirect is a fact naming the final URL. A defect only for 404 or 410. 401 and 403 are `ACCESS_DENIED`, 429 is `RATE_LIMITED`, and a failed fetch or a 5xx is `FETCH_FAILED`.
- **`epi.og.image.resolves`**: the `og:image` (the first with a value, `property=` before `name=`) is fetched with the normal size limit and `store_body=False`, so the image is never decoded, kept, or cached; only the receipts are. A defect for 404, 410, or a 2xx whose Content-Type is not `image/*` (or is missing).
- **One fetch per distinct URL** (`RunFetches` in `src/cernis/audit.py`): results are memoized by the URL as sent, and a successful fetch is also registered under its final URL, so a canonical that is the page itself, a page that redirected to its canonical, or an original shared by two pairs costs one request. Every receipt is collected once. `chain_from` reports only the part of a reused fetch's redirect chain from the URL in question on.
- **`Fetcher.fetch(url, store_body=False)`**: neither reads nor writes the cache, and returns no body.
- **Tests** (`tests/test_checks_epitext.py` and additions to `test_cli.py`, `test_model.py`, `test_pairs.py`), all on MockTransport: a matching pair; a copy with no canonical; a copy pointing elsewhere; an owned copy's plain recommendations; trailing-slash and redirect equivalence; an original whose canonical names another page; an unreachable original, and 403 and 429 originals; an unreachable copy; disagreeing canonicals; a 404, 410, 200, redirect, 401, 403, 429, and 500 canonical; a redirect chain; a canonical on a private address; an og:image that returns HTML, no Content-Type, 404, or 410; a DEV og:image defect as `PLATFORM` with no recommendation; an image redirect; the image never cached; fetch reuse; owned actors; the CLI's `pair` (Markdown, JSON, a map's prefix rules, a copy equal to the original) and `pairs` (two pairs sharing an original, a map with no pairs); `RunPair` rules; and the pair report layout. The older audit, CLI, and report tests now route their canonicals and images, and their counts were updated. The goldens were regenerated and the diff read before accepting: the two new check rows per page, `peri.og.url_matches_canonical 2` with the Open Graph citation on the DEV page's defect, and one deliberate `epi.canonical.resolves` defect (the two-canonicals page's dev.to canonical, unrouted, answers 404) with its recommendation. Observed 26 to 30, recommendations 1 to 2.
- **Docs.** DESIGN.md draft 2.5 (status line; the actor table; section 3's site types; section 4's `peri.og.url_matches_canonical` and three epitext rows; section 6's one fetch per URL and unstored images; section 7's CLI; section 10's Phase 4 row). `docs/PAIR-MAP.md` (the `owned` type and the pair commands, replacing "Phase 4 will"). README (usage and the epitext table). CHANGELOG. CLAUDE.md's current stage.

## Decisions

1. **The pair's subject is the copy's URL.** Both pair findings, including the original's side, are about the copy's URL, so a pair has one subject in the report and in history; the targets `copy` and `original` keep the two keys apart. The original's own page findings stay under the original's URL.
2. **An unreadable original makes both sides `NOT_DETERMINABLE`.** Without the original's page, Cernis cannot know its URL after redirects or its canonical, so neither comparison can be judged.
3. **An original with no canonical is a fact, not a defect.** DESIGN.md's defect rule names only the copy's missing canonical; the original's absence is still reported, and `peri.canonical.present` already records it.
4. **On DEV, the og:image is the platform's.** DEV generates the `og:image` URL (a resized image on `media2.dev.to`); the author chooses a cover image but not the URL, so a defect there has no recommendation.
5. **Fetch reuse is by the URL as sent, plus a successful fetch's final URL.** Normalized URLs that differ (a trailing slash) are fetched separately, because they are different requests a server may answer differently. A bodiless result (an image fetch) is not reused where a page is needed.
6. **`owned` fetch outcomes are the author's**, as WordPress robots.txt already was: there is no platform between the author and the page.
7. **Two extra recommendation templates for the copy** (DEV front matter, and adding a missing canonical) and one for the original, because the fix differs by where the copy lives and what is wrong.

## Real request

One command, the only real requests of the session, with a scratch map holding only `[[site]] prefix = "https://www.kenwalger.com/blog/"` `type = "wordpress"`:

`cernis pair --original https://www.kenwalger.com/blog/writing/views-measure-views-nine-years-writing --copy https://dev.to/kenwalger/views-measure-views-4co7 --map <file>` (run `20261102T192732Z`, exit 0). Requests: robots.txt and the page on www.kenwalger.com (the page redirected once to its trailing-slash URL), robots.txt and the page on dev.to, the original's og:image (200 `image/png`), robots.txt on media2.dev.to, and the DEV og:image (200 `image/webp`). The canonicals were not fetched again: both are the original's URL, with and without the slash, and both were answered by the page's own fetch.

- Original: read whole (`r-002`), `wordpress.entry 1+n1`, **prefix**. Observed 15, no defects.
- Copy: read whole (`r-004`), `dev.article 1+n1`, host. Observed 15; one defect, **PLATFORM** `peri.og.url_matches_canonical`, now citing the Open Graph protocol.
- The pair: the copy's canonical **is** the original's URL (IDENTICAL); the original's canonical is **equivalent** to the original's URL (trailing slash). No defect.
- Recommendations 0; not determinable 0. The full Markdown report was shown to the Owner.

**A defect found by the real run, fixed after it.** The original's own canonical (the trailing-slash URL) was answered by the page's fetch through its final URL, and the report said it "redirects (1 hop) to" itself: the redirect was the page URL's, not the canonical's. `chain_from` now reports only the part of the chain from the URL in question on, and `test_a_canonical_reached_by_a_redirect_reuses_that_fetch` pins it. The command was not rerun, because only its one run was allowed; on the same responses, that finding now reads "The canonical URL https://www.kenwalger.com/blog/writing/views-measure-views-nine-years-writing/ answers 200." with no redirect evidence.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (57 files), pydoclint, pytest (1006 passed), and the isolated Python 3.12 pytest (1006 passed).

## For the pre-0.1.0 release audit (additions)

To the lists in `SESSION-03b.md`, `SESSION-04a.md`, `SESSION-04b.md`, and `SESSION-04d.md`, add:

22. **Fetches beyond the listed URLs**: canonical and og:image URLs come from page content, so a page can name any host. Review them against DESIGN.md section 6's "only URLs the author lists" and the address screen (ADR-005), including redirects, IDN hosts, and `data:` or non-http og:image values.
23. **`epi.pair.canonical`**: decisions 1 to 3, the redirect evidence passed to `compare_urls` (every receipt of the run), the reason code carried from the original, and `AMBIGUOUS` sides.
24. **Actors**: `owned` everywhere (decision 6), the DEV og:image as `PLATFORM` (decision 4), and `PLATFORM` on DEV's `og:url` defect.
25. **`RunFetches` reuse** (decision 5) and `chain_from`: the final-URL registration, bodiless results, and receipts collected once.
26. **`store_body=False`**: that it neither reads nor writes the cache, and that the body limit still applies.
27. **The pair report layout and `Run.pairs`**: a page in two pairs is shown under the first only; the JSON `pairs` field without a format version change.

## Deferred

- **The rest of Phase 4**: `epi.robots.access`, `epi.sitemap.listed`, `epi.links.resolve`, and the URL sources (sitemap, DEV username).
- **A pair golden file.** The pair layout is tested by heading assertions; a full golden would pin the whole report.
- Still open from Session 4b: the subject line not saying whether an article body was found, non-HTML responses, and `<base href>`.
- **SDK friction**: none this session; the SDK was not used.

## Not touched

- The URL comparison, the parser, the extractors' selectors, snapshot normalization, and finding keys.
- No ADR was changed or contradicted.
