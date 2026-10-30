# Session 4a: Phase 3, part one (foundations)

**Date:** 2026-10-30
**Phase:** 3 (DESIGN.md draft 2.3, sections 3 and 4)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

Parsing and comparing only: no findings, no checks, no reports. No Cernis fetches; the only network use was PyPI (adding selectolax and idna, and the sovereign-sieve check). No Decision Engine audit, as the session prompt required.

## Built

- **selectolax** (1.0.2, Lexbor backend) is the HTML parser. lxml was not needed: Lexbor implements the WHATWG parsing algorithm, so malformed markup is repaired exactly as a browser repairs it (an unclosed `<a>` is reopened after `</div>`, a `meta` after the body content lands in `<body>`); it ships type stubs, so mypy strict checks every call; and it has wheels for Python 3.12 to 3.15. Nothing on the fixtures needed a second parser.
- **`src/cernis/parse/html.py`: `parse_page(receipt, body)`.** Decodes the body (byte-order mark, then the `Content-Type` charset, then `<meta charset>` in the first 1024 bytes, then UTF-8; Latin-1 labels mean windows-1252, as in browsers) and extracts every `<title>` in `<head>`, `<html lang>`, every `rel="canonical"` link (with `href` as written, or `None`, and whether it is in `<head>`), every `meta` with a `name` or `property` (so `og:*` written as `name=` is kept and labeled), every JSON-LD block (raw text, whether it parsed, the value, the error, and every `@type` at the top level, in an array, or in an `@graph`), and every `<a href>` in `<body>`. It never raises: undecodable bytes, a canonical without `href`, a JSON-LD block that is empty, broken, or nested too deeply, and a truncated body are each recorded in `ParsedPage.problems`. Values are recorded exactly as the parser saw them; normalization is only for hashing and comparison.
- **`src/cernis/parse/extractors.py`.** `dev.article` (`#article-body`), `wordpress.entry` (`.entry-content`, else `.wp-block-post-content`), and `generic` (never a body), each at version 1. `choose_extractor(url, site)` takes a declared `SiteType` first, then the host (`dev.to`, `www.dev.to`), then `generic`. An extractor whose selector matches more than one element returns no body, with the reason, rather than guess. `read_article` returns the body's visible text and links.
- **`src/cernis/parse/snapshot.py`: `build_snapshot(receipt, body, site=)`.** The three hashes per DESIGN.md section 3, with the normalization written out in the module docstring and tested rule by rule:
  - `content_sha256`: the article body's visible text, with script, style, noscript, and template contents left out, whitespace collapsed, and NFC applied. `None` when no body was found.
  - `head_sha256`: a sorted list of `lang`, `<head>` titles, canonical hrefs, every `meta` (attribute, lowercased key, normalized content), and JSON-LD (re-serialized with sorted keys, or the normalized raw text if it does not parse). Element order and attribute order do not matter, and a CSRF `meta`'s content is `~`.
  - `frame_sha256`: the rest of the document, `<head>` included, with the metadata removed and the article body as a placeholder. Elements carry sorted, normalized attributes; comments, `<html lang>`, and script, style, noscript, and template contents are dropped.
  - Volatile tokens are replaced in the frame: `nonce`, `integrity`, and any attribute named with `csrf` are dropped; hidden inputs named with `csrf`, `token`, or `nonce` have their value replaced; asset fingerprints of 8 or more hex digits and cache-busting query values (`v`, `ver`, `hash`, and the rest) are replaced in URL attributes.
  - The snapshot's `extractor_version` is `<extractor version>+n<NORMALIZATION_VERSION>` (now `1+n1`), so changing a normalization rule shows in history as a `CHECKER` change.
  - A snapshot is made only from a whole body: a failed, truncated, or bodiless receipt, or a body that does not hash to the receipt's `body_sha256`, raises `SnapshotError` (ADR-003). A `304` with its cached body works.
- **`src/cernis/urls.py`: the one URL normalization and `compare_urls`.** `normalize_url` applies, in order: surrounding whitespace removed, NFC, scheme lowercased, host lowercased and IDNA (UTS 46) encoded, default and empty ports removed, empty path made `/`, dot segments removed, percent-encoding normalized, one trailing slash ignored, and the fragment removed. Query and user information are kept exactly; anything that is not an absolute http(s) URL is returned as NFC text. `compare_urls(a, b, redirects=)` returns `IDENTICAL`, `EQUIVALENT` with every normalization that mattered (in a fixed order, and never one both sides share), or `DIFFERENT`. A receipt whose redirect chain passes through one URL and later reaches the other makes the pair `EQUIVALENT` with reason `redirect` and the receipt id. The comparison is symmetric.
- **One normalization.** `normalize_percent_encoding` in `cernis.urls` is now what the RFC 9309 matcher uses for patterns and paths; the matcher adds only the RFC's special handling of `*` and `$` (passed as the `literal` mapping). The matcher's behavior is unchanged (all 122 robots and matcher tests pass untouched), so `MATCHER_VERSION` stays `1`.
- **Finding keys, final.** `finding_key` NFC-normalizes every string, sends the subject URL through `normalize_url`, and sends a target through it too when the target is an absolute http(s) URL; any other target (a vocabulary identifier such as `og:image`) is NFC only. The Session 1b placeholder is gone.
- **`ReasonCode.ADDRESS_REFUSED`**, added to match DESIGN.md draft 2.3's reason-code table.
- **Fixtures** (`tests/fixtures/`, indexed in its README): `dev-article`, `wordpress-entry`, `missing-canonical`, `two-canonicals`, `relative-canonical`, `missing-og`, `broken-jsonld`, `malformed`, and the pair `volatile-a` and `volatile-b`. All are hand-written; the hosts are `dev.to` or reserved example domains, and every token is invented.
- **Dependencies.** selectolax (`>=1.0.2`) and idna (`>=3.10`; it came with httpx, and `urls.py` now imports it directly).

## Decisions

1. **Finding keys are final, and must not change before Phase 5 without an ADR.** Changing `finding_key` or `normalize_url` changes every key and makes stored history unmatchable. The pinned key test changed on purpose this session: the builder's subject URL ends in `/`, which the final normalization ignores, so its key moved from `23d4acbd...` to `c23399e3...`; a second pin covers a URL target. `test_key_payload_is_check_normalized_url_and_target` spells out the payload so the pin can be checked by hand.
2. **Dot-segment removal is in the URL normalization, beyond DESIGN.md's list.** Every HTTP client resolves `.` and `..` before sending, so `/a/../b` and `/b` always name the same resource, and calling them `DIFFERENT` would be a false defect (claim C-3). For the Owner to confirm.
3. **Only one trailing slash is ignored**, so `/a//` and `/a` stay `DIFFERENT`; and a bare `?` counts as a query, so `/a?` and `/a` are `DIFFERENT` (queries compare exactly).
4. **Metadata counts wherever it is.** A canonical, `meta`, or JSON-LD element in `<body>` (where malformed or careless pages put them) is recorded with `in_head` false and hashed into `head_sha256`, so a change to it is never lost. The frame's scripts are not hashed, so leaving body JSON-LD to the frame would have hidden it.
5. **The frame includes `<head>`'s non-metadata** (stylesheets, scripts, viewport and similar `link`s), since DESIGN.md calls it "the rest of the page"; a stylesheet change is a platform rendering change.
6. **`content_sha256` is text only**, as DESIGN.md says. A link target changed inside the article body without its text changing does not move it; Phase 3's link checks see the link itself.
7. **WordPress must be declared.** Its host cannot be recognized, and sniffing `<meta name="generator">` would be a guess; until a page's site type is declared, it gets `generic` and no content hash.
8. **Asset fingerprints are 8 or more hex digits.** DEV's article slug suffixes (four characters, such as `-1a2b`) and WordPress paths must not be mistaken for fingerprints; a 7-digit run is kept, and a test pins that boundary.
9. **sovereign-sieve is not adopted**, pending the Owner's decision. It is installable from PyPI, but as `sovereign-sdk-sieve` (the `sovereign-sieve` name is now a stub pointing there), and it is a prose token optimizer with no HTML parsing. On the fixtures it deletes the author's words and rewrites raw HTML. The full evaluation is in `docs/SDK-FRICTION.md` (2026-10-30).

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (43 files), pydoclint, pytest (786 passed), and the isolated Python 3.12 pytest (786 passed). An isolated Python 3.13 run also gives 786 passes.

## For the pre-0.1.0 release audit (additions)

To the list in `SESSION-03b.md`, add:

8. **The URL normalization and comparison** (`urls.py`): every step against RFC 3986 section 6, IDNA (UTS 46) handling of mixed-case and invalid hosts, the reason-attribution logic (that a shared normalization is never reported, and that the comparison is symmetric), the decision to remove dot segments (decision 2), and redirect equivalence (which hops count, and whether a chain from a different requested URL can wrongly make two URLs equivalent).
9. **Finding keys** as now final: the NFC and URL-target rules, and the rule for telling a URL target from a vocabulary identifier.
10. **The parser's robustness**: that `parse_page` cannot raise on any input (decoding, pathological nesting, huge attribute counts), the encoding-sniffing order, and what a truncated body yields.
11. **The snapshot normalization**: whether any volatile-token rule can hide a real author or platform change (the fingerprint regex, the hidden-input rule, dropping inline script contents), whether anything volatile on real DEV or WordPress pages is still missed (C-2 depends on it), and the head/frame split for metadata outside `<head>`.
12. **The extractors**: the selectors against DEV's and WordPress's current markup, and the ambiguity rule.

## Deferred

- **Owner decisions:** adopt sovereign-sieve or not (decision 9; the evaluation recommends against for extraction); confirm dot-segment removal (decision 2).
- **Volatile text in the frame**, such as relative dates ("3 hours ago") or view counters, is not normalized. C-2's stability runs (Phase 5) will show whether real pages need it.
- **Site-type declaration** has no input yet: Phase 3's `cernis audit` needs a way to say a URL is WordPress.

## Not touched

- `img/` (untracked logo files in the working tree): not this session's, left as found.
- The fetcher, apart from the matcher's move onto the shared percent-encoding function.
