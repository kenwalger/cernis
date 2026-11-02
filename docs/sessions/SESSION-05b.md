# Session 5b: Phase 4, part two

**Date:** 2026-11-02
**Phase:** 4 (DESIGN.md draft 2.6, sections 2, 3, 4, 6, 7, and 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

The rest of Phase 4: robots access for AI crawlers, robots directives, sitemaps, article-body links, and two URL sources. This is the largest expansion of what Cernis fetches, so one deep Decision Engine audit ran before finishing, as the session prompt required. The only real requests were the two the prompt named.

## Built

- **`peri.robots.directives`** (version 1): every robots `meta` tag (`robots`, `googlebot`, `googlebot-news`, `bingbot`, and each AI crawler token) and the response's `X-Robots-Tag` header, as written, or that there are none. One finding, never a defect. On DEV the actor is `PLATFORM`. An unread page gets it as a `NOT_DETERMINABLE` question.
- **`epi.robots.access`** (version `1+c1+m1`): one finding per name, the name being the target: `*`, then each token in `src/cernis/data/ai_crawlers.toml`. It reads the robots.txt Cernis already fetched for the page, with the same receipt, through Cernis's own RFC 9309 matcher. Each finding says whether a group names the crawler or the `*` group applies, and which rule decided. A 4xx robots.txt allows every crawler (a fact). A 5xx, 429, or failed robots.txt, or one never fetched because the address screen refused the host, is `NOT_DETERMINABLE`. Never a defect. Actor: `PLATFORM` on DEV, `AUTHOR` on WordPress and owned sites, `UNKNOWN` otherwise. The check version folds in the crawler list's version and the matcher's version, so changing either is a `CHECKER` change.
- **The crawler list** (`src/cernis/data/ai_crawlers.toml`, version 1, loaded by `src/cernis/crawlers.py` and validated): 13 tokens, each checked against its operator's own documentation on 2026-11-02, with the operator, a purpose, and the source URL:
  - OpenAI: GPTBot, ChatGPT-User, OAI-SearchBot (developers.openai.com/api/docs/bots, the page platform.openai.com/docs/bots redirects to).
  - Anthropic: ClaudeBot, Claude-User, Claude-SearchBot (support.claude.com/en/articles/8896518).
  - Google: Google-Extended (Google's common crawlers page; a product token, not a crawler).
  - Perplexity: PerplexityBot, Perplexity-User (docs.perplexity.ai/guides/bots).
  - Common Crawl: CCBot (commoncrawl.org/ccbot).
  - Apple: Applebot-Extended (support.apple.com/en-us/119829; a product token).
  - Amazon: Amazonbot (developer.amazon.com/amazonbot).
  - Meta: Meta-ExternalAgent (Meta's web crawlers page, which writes it in lowercase; matching ignores case).
  - **Dropped: Bytespider.** Only third-party pages describe it, and ByteDance's own site showed no documentation of the token, so it could not be confirmed.
  - The wheel ships the data file (checked by building it).
- **`epi.sitemap.listed`** (version 1; `src/cernis/sitemaps.py`, `src/cernis/checks/sitemap_listed.py`):
  - **Discovery:** robots.txt `Sitemap:` lines; then `sitemap.xml` and `wp-sitemap.xml` at the site's root (the `[[site]]` prefix covering the page), then at the origin's.
  - **Reading:** indexes are followed (children on the index's own host only); `.xml.gz` is read in every gzip member, within the body limit; documents are parsed with expat handlers that refuse any `DOCTYPE` or entity declaration, in any encoding.
  - **Caps:** 50 documents per site (`--max-sitemap-documents`), two index levels, 50,000 entries per document, and 200,000 per site.
  - **Matching:** a `<loc>` matches when it is equivalent to the page's URL, the URL it answered at, or a hop in its redirect chain.
  - **Reading once:** each site's sitemaps are read once per run.
  - **Outcomes:** no sitemap found (404 or 410 everywhere searched) is a fact. A place that could not be read, a child the fetcher refuses, or a read stopped by a limit is `NOT_DETERMINABLE`, and so is an omission when a Google News sitemap was read. A page expected to be absent (its canonical names another URL, or it declares `noindex`) is a fact.
  - **The defect:** only when a completely read sitemap lists other pages in the section (the `[[site]]` prefix, else the parent path) and not this one. Its recommendation is "Add {url} to the site's sitemap." It is skipped on DEV.
- **`epi.links.resolve`** (version 1; `src/cernis/checks/links.py`):
  - **Scope:** links in the extracted article body only, deduplicated without fragments, fetched with `store_body=False`.
  - **Skipped, and counted in one fact** (`skipped links`): `mailto:`, `tel:`, `javascript:`, other schemes, fragment-only links, empty values, and URLs the fetcher never fetches (`not fetchable`).
  - **Limits:** 100 links per page and 5 per external host per run (`--max-links-per-page`, `--max-links-per-host`). The host budget is charged once per distinct URL and for each external host a link redirects to. Links over a limit get one `NOT_DETERMINABLE` finding per page (`unchecked links`, `LIMIT_REACHED`) naming how many, which, and why.
  - **The defect:** only 404 or 410, with the recommendation "Update or remove the article's link to {url}." A redirect is a fact naming the final URL.
  - **Other outcomes:** the usual reason codes. The generic extractor gives `REQUIRES_EXTERNAL_DATA`, an ambiguous body gives `AMBIGUOUS`, and an unread page gives its own reason.
- **`ReasonCode.LIMIT_REACHED`**: attempt-based, so it needs evidence. ADR-001 amendment 2 (dated 2026-11-02) records it. ADR-001 itself says new reason codes are a model change, so this amends it rather than contradicting it.
- **URL sources** (`src/cernis/sources.py`):
  - `cernis audit --from-sitemap URL [--include-prefix P]` lists only pages on the sitemap's own host, with a note counting the rest.
  - `cernis audit --from-dev-user NAME` reads DEV's public articles API page by page (at most 50 pages, `per_page` = min(100, limit)). It keeps published articles at dev.to URLs only, and a failed page stops the listing with a note. The username must be letters, digits, and underscores.
  - Both take `--limit N` and `--list-only`. Every request goes through the run's fetches and is a receipt. The run records its source (`Run.sources`, `RunSource`, `SourceNote`, and `sources` in the JSON report and the Markdown header).
- **Pairs:**
  - A `[[pair]]` accepts `copies = [...]` (exactly one of `copy` or `copies`; no copy twice), and each copy loads as its own pair.
  - `cernis pairs --from-dev-user NAME [--map FILE] [--limit N] [--list-only]` pairs each DEV article whose `canonical_url` is off dev.to (the canonical is the original, the DEV URL the copy). Other articles are noted as not cross-posted. A map then supplies only site types and prefix rules.
- **`--allow-loopback`** is refused together with `--from-sitemap` or `--from-dev-user`, and prints a warning otherwise.
- **Fetcher:** `Fetcher.robots_policy(url)` exposes the run's cached policy, and `url_problem` is now public. The matcher collects `Sitemap:` lines and reports whether a group names a token (`names`). Matching itself is unchanged, so `MATCHER_VERSION` stays 1.
- **Tests:** 1106 in all. New: `tests/test_robots_access.py`, `tests/test_sitemaps.py`, `tests/test_links.py`, and `tests/test_sources.py`, plus additions to `tests/test_pairs.py`. All of them use MockTransport, and they include every case the prompt named: AI-crawler groups, sitemap indexes and gzip, a page missing from its sitemap, link limits, a 410 link, a private-address link, and DEV API pagination. There is one regression test per accepted audit finding. The peritext fixture expectations gained the directives row. The older audit, CLI, and report tests were updated, and the goldens were regenerated with the diff read before accepting: the new checks per page, two broken DEV body links as defects with recommendations, and the unread page's three new open questions.
- **Docs:** DESIGN.md draft 2.6, ADR-001 amendment 2, PAIR-MAP.md (`copies`, `--from-dev-user`), README, CHANGELOG, and CLAUDE.md.

## Decisions

1. **The section for the sitemap defect** is the `[[site]]` prefix covering the page, else the page's parent path (trailing slash stripped first). This follows the prompt's "same prefix". Whether a whole-origin prefix should count as one section is left for the Owner (audit V1 f4, below).
2. **Sitemap discovery looks at the site's root before the origin's.** The real run showed why: kenwalger.com's root `sitemap.xml` belongs to another site, and the WordPress install's sitemap is under `/blog/`.
3. **Robots access for unread pages.** A page Cernis may not fetch still has a robots.txt to report on, so it gets the 14 findings. A page whose host was refused before robots.txt was fetched gets 14 `NOT_DETERMINABLE` findings.
4. **Links with no body.** With the generic extractor (owned and undeclared sites), links are `REQUIRES_EXTERNAL_DATA`, never guessed from the whole page.
5. **`LIMIT_REACHED` needs evidence**: the page's receipt and the links left unchecked, or the sitemap documents read.
6. **Pages expected to be absent from a sitemap** (a copy whose canonical names its original, or a `noindex` page) are facts, never defects. A news sitemap makes an omission `NOT_DETERMINABLE` (`AMBIGUOUS`).
7. **The `meta` names read as robots directives** are `robots`, three search crawlers, and the AI crawler tokens. Values are reported as written, never interpreted.

## Real requests

**`cernis pairs --from-dev-user kenwalger --list-only --limit 10`:** two requests. They were `https://dev.to/robots.txt` (304, cached) and `https://dev.to/api/articles?username=kenwalger&page=1&per_page=10` (200). The listing found 9 pairs, each a kenwalger.com/blog original with its DEV copy, and 1 article not cross-posted: "Building an Enterprise AI Governance Stack", whose canonical URL is the DEV article itself. The listing was shown to the Owner.

**`cernis pair` on Views Measure Views**, with the scratch map holding only `[[site]] prefix = "https://www.kenwalger.com/blog/" type = "wordpress"` (run `20261102T200711Z`, 16 seconds, exit 0):
- **Observed 74.** The original (wordpress.entry, prefix) has robots directives `max-image-preview:large`. The copy (dev.article, host) has `max-snippet:-1, max-image-preview:large, max-video-preview:-1`.
- **Robots access:** both robots.txt files allow `*` and every one of the 13 AI crawlers, with no group naming any of them. The findings are `AUTHOR` on kenwalger.com and `PLATFORM` on dev.to.
- **The sitemap** was a fact: "does not list the page, and lists no other page under https://www.kenwalger.com/blog". Cernis had read the root `https://www.kenwalger.com/sitemap.xml`, which belongs to the site at the root, not to the blog. That led to decision 2 and its test. The fix was not rerun, because only one run was allowed.
- **Links:** the original's body has 13 links. Five answer 200 (two dev.to links, mongodb.com, rust-lang.org, and its own permalink), and 2 `mailto:` links are skipped. The copy's body has 15 links: 4 answer 200, reused from the original's fetches, and 10 fragment-only links are skipped.
- **The pair:** unchanged from 5a. The copy's canonical is identical to the original's URL, and the original's canonical is equivalent to it (trailing slash).
- **Recommendations 0. Not determinable 5:** the original's Jetpack share buttons inside `.entry-content` (Facebook, X, Reddit, LinkedIn, and `?share=linkedin`), whose targets' robots.txt files disallow Cernis. These are correct, but they will repeat on every WordPress article; see Deferred.
- The full Markdown report was shown to the Owner.

## Decision Engine audit

- **audit_id:** `aud_gwCSZD5Y6S`
- **Mode:** `deep`, stakes `high`, intent `prescriptive`, tier `reasoning`
- **Voices:** 4 (V1 OpenAI, V2 Google, V3 Anthropic, V4 DeepSeek), all completed, all "has-serious-issues".
- **Artifact:** the source diff, in full for the new modules, with argparse boilerplate, the report renderers, the crawler data rows, and the tests summarized.

**Tally:** 38 raw findings (V1 6, V2 9, V3 14, V4 9), 26 distinct after merging duplicates. 13 were fixed, 12 rejected as wrong, and 1 is left for the Owner.

**A lesson about the artifact.** For a few hunks I sent summarized pseudocode instead of the code. Voice 2 read those summaries as the code, and six of its nine findings describe code that does not exist (undefined names, missing returns, strings passed instead of `Target`s). Each was rejected against the real source and its tests. A future deep audit should send real code only.

| # | Voices | Finding | Outcome | Evidence |
| --- | --- | --- | --- | --- |
| D1 | 3 (V1 f1, V4 f5, V3 f11) | Sitemap entries and the index queue are unbounded; entries renormalized per page | fixed | 50,000 entries per document, 200,000 per site, queue capped to the documents left, normalized keys stored once (`SitemapEntry.key`); `test_the_entry_cap_is_a_limit_reached`, `test_the_document_limit_is_never_a_silent_skip` |
| D2 | 4 (V1 f2, V2 f1, V4 f1, V4 f2) | `sitemap_listed` falls through after a match, or after an incomplete read, emitting duplicate keys and false defects | rejected | Every branch returns: the match loop returns on the first match, and `if not read.complete` returns before the omission test; tests for listed, incomplete, and limit cases pass |
| D3 | 1 (V1 f3) | A readable fallback hides an earlier unreadable sitemap | rejected | `discover_sitemaps` keeps every document tried, and `complete` checks all of them, so an earlier unread document makes the read incomplete; earlier candidates were not found, so they hold no entries |
| D4 | 1 (V1 f4) | A whole-origin `[[site]]` prefix makes the whole site one section | left for the Owner | Decision 1; the prompt says "same prefix" |
| D5 | 1 (V1 f5) | Redirect destinations bypass the per-host budget | fixed | Each external host a link redirects to is charged after the fetch (`HostBudget.spend`); `test_a_redirect_destination_is_charged_to_its_host`. Every hop was already paced and screened |
| D6 | 3 (V1 f6, V3 f3, V4 f7) | A `FetchError` sitemap document is dropped silently, and a refused link is called "not a URL" | fixed | It is recorded as an unread document citing the receipt that named it, so the read is incomplete; links say `not fetchable`; `test_a_child_the_fetcher_refuses_leaves_the_answer_open`, `test_a_link_with_user_information_is_not_fetchable` |
| D7 | 1 (V2 f2) | `RobotsPolicy.sitemaps` raises on no rules; `receipt_id` is missing | rejected | The property returns `()` without rules; `RobotsPolicy.receipt_id` exists; `test_a_missing_robots_txt_allows_every_crawler` |
| D8 | 1 (V2 f3) | `host` shadows a function in `links_resolve` | rejected | The function is `_host`; `own_host = _host(page.base)`; the link tests pass |
| D9 | 1 (V2 f4) | `names` is undefined in `robots_directives` | rejected | `names = _robots_meta_names()`; `test_robots_meta_and_header_are_facts_never_defects` |
| D10 | 1 (V2 f5) | `final` and `max_body_bytes` are undefined | rejected | `final = result.final`; `fetches.fetcher.config.max_body_bytes`; the sitemap and source tests pass |
| D11 | 1 (V2 f6) | A 404 sitemap is parsed and becomes `FETCH_FAILED` | rejected | Non-2xx returns before parsing; `test_no_sitemap_is_a_fact_naming_every_place_searched` |
| D12 | 1 (V2 f7) | `run_audit` passes strings, not `Target`s | rejected | `targets = [Target(url=url, ...) for url in listed]`; `test_audit_from_sitemap_list_only`, CLI tests |
| D13 | 1 (V3 f7) | `audit --from-dev-user` URLs lose the DEV site type | rejected | Site resolution detects dev.to by host (`effective_site`); the from-dev-user CLI test shows `dev.article`, host |
| D14 | 2 (V2 f8, V4 f9) | Repeated `robots_policy` calls duplicate receipts | rejected | `RunFetches.receipts` is a dict and `setdefault` adds each id once; the Run's receipt-uniqueness validation passes in every run test |
| D15 | 2 (V2 f9, V3 f13) | Cross-host index children and sitemap locs widen the crawl | fixed | Index children on other hosts are recorded, not followed; `--from-sitemap` lists only its own host's pages, with a note; `test_cross_host_index_children_are_not_followed`, `test_a_sitemap_lists_only_its_own_hosts_pages`. robots.txt `Sitemap:` lines may name other hosts, as sitemaps.org allows |
| D16 | 1 (V3 f1) | A UTF-16 document gets past the byte-level DOCTYPE guard, and ElementTree expands its entities | fixed | Expat with handlers that refuse DOCTYPE, entity, notation, and external entity declarations; `test_a_utf16_doctype_is_refused_by_the_parser` |
| D17 | 2 (V3 f2, V4 f4) | A malformed href or `<loc>` crashes the run | fixed (locs); rejected (hrefs) | `<loc>` values are kept only if the fetcher would fetch them, and `InvalidURL` is caught when queuing; `test_malformed_locs_are_counted_not_fatal`. `sort_links` already caught `ValueError` around `urljoin` |
| D18 | 1 (V3 f4) | False omission defects for copies, `noindex` pages, and news sitemaps | fixed | Decision 6; `test_a_page_expected_to_be_left_out_is_a_fact` (both cases), `test_a_news_sitemap_omission_is_not_determinable` |
| D19 | 2 (V3 f5, V4 f3) | Matching uses `normalize_url` instead of the shared comparison | fixed | Redirect-chain hops now count, which is the one equivalence `compare_urls` adds beyond normalization (a scheme change stays `DIFFERENT` by design); `test_a_loc_the_page_redirected_through_is_the_page` |
| D20 | 1 (V3 f6) | `--allow-loopback` combines with untrusted URL sources | fixed | Refused with `--from-sitemap` and `--from-dev-user`, warned otherwise; `test_loopback_is_refused_with_a_url_source` |
| D21 | 2 (V3 f8, V4 f6) | Robots access is silent when robots.txt was never fetched; unread pages get no epitext findings | fixed | `NOT_DETERMINABLE` per name, and for the sitemap and links, with the page's reason; `test_a_refused_address_is_address_refused` and the unread-page tests |
| D22 | 1 (V3 f9) | Only the first member of a multi-member gzip is read | fixed | Every member is decompressed within the limit; `test_every_gzip_member_is_read` |
| D23 | 1 (V3 f10) | The host budget is charged per occurrence and for memoized URLs | fixed | Charged once per distinct URL (`RunFetches.known`); `test_a_link_already_fetched_costs_no_host_budget` |
| D24 | 1 (V3 f12) | A trailing-slash permalink's section is the page itself | rejected | `section_of` strips the trailing slash before cutting; `test_a_section_is_the_prefix_or_the_parent_path` (`/2026/10/a-synthetic-post/` gives `/2026/10/`) |
| D25 | 1 (V3 f14) | A repeated `X-Robots-Tag` loses values | rejected | Receipts join repeated headers with ", " (RFC 9110 section 5.3; `_recorded_headers`) |
| D26 | 1 (V4 f8) | Any 4xx counts as no sitemap | fixed | Only 404 and 410; `test_only_404_and_410_mean_no_sitemap` |

There was one audit and no re-audit after the fixes, as the prompt required.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (67 files), pydoclint, pytest (1106 passed), and the isolated Python 3.12 pytest (1106 passed).

## For the pre-0.1.0 release audit (additions)

To the lists in `SESSION-03b.md` through `SESSION-05a.md`, add:

28. **What Cernis fetches from content**, end to end: body links, sitemap documents, and the DEV API. Check the address screen, robots.txt, pacing, and caps against a hostile site, beyond this session's deep audit.
29. **The expat configuration** in `parse_sitemap`: that no DTD, entity, or external reference path remains on Python 3.12 through 3.14 and older libexpat builds.
30. **The crawler list**: re-verify each token against its source at release, and decide whether Bytespider can be confirmed.
31. **The sitemap defect rule**: decisions 1 and 6, and D4.
32. **`LIMIT_REACHED`** and ADR-001 amendment 2.

## Deferred

- **D4, for the Owner:** whether a `[[site]]` prefix that covers a whole origin should count as one section for the sitemap defect, or whether the parent path should always be used.
- **Share widgets, for the Owner:** links in Jetpack's `.sharedaddy` block inside `.entry-content` are checked as article links, and their targets' robots.txt files disallow Cernis. Excluding them would change the WordPress extractor (and its version), so it is the Owner's call.
- **Rerunning the pair** after the sitemap discovery fix, in the next session's full run.
- **SDK friction:** none this session; the SDK was not used.

## Not touched

- The URL comparison, finding keys, snapshots, and the extractors' selectors.
- No ADR was contradicted; ADR-001 gained a dated amendment.
