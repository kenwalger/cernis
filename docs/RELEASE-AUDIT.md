# Pre-0.1.0 release audit

Everything the session records set aside for review before 0.1.0 is tagged, in one list (consolidated in Session 5d, 2026-11-02). Items are deduplicated and grouped by area, with the highest-risk areas first: what Cernis fetches and from where, then what it trusts, then what it claims. Each item names the session records it came from, as `SESSION-03b #1` (that record's list, item 1), so its full context can be found.

The session records' own lists are not rewritten; this file supersedes them as the working list. Mark an item done here with the session that reviewed it.

**Session 5e (2026-11-02)** fixed 24 of the 28 real findings from the tier comparison of the network-safety code (`docs/experiments/2026-11-tier-comparison.md`, `docs/sessions/SESSION-05e.md`). The bounded-decoding half of item 5 is done and removed. The other items here are wider than those findings, so each stays, with a note on what was fixed and what remains.

## 1. Network safety: what Cernis fetches, and from where

1. **The address screen and its gaps** (ADR-005): the range lists against the current IANA special-purpose registries, embedded-IPv4 decoding, the decision to leave documentation ranges open, and the six gaps the ADR names (caller-supplied transports, public addresses that lead inward, ports, Teredo and other transition forms, proxies, and the private `_pool` replacement). *SESSION-03b #1*
   *Session 5e:* the ranges the tier comparison named were added (ADR-005 amendment 1), and the IPv4-translated and Teredo forms are decoded. The documentation ranges stay open. Still to review: the lists against the current IANA registries themselves (not consulted in Session 5e), and gaps 1, 2 (beyond Azure's address), 3 (kept open on purpose), 4 (ISATAP and operator NAT64 prefixes), 5, and 6. Also open: integer and hex IPv4 host forms against the real resolver (finding D23, deferred).
2. **Pinning and the network backend** (`network.py`): every connection httpcore opens goes through `GuardedBackend.connect_tcp`; keep-alive reuse cannot carry a connection to an unscreened address; TLS verification still uses the hostname; the `_pool` replacement keeps httpx's TLS defaults. *SESSION-03b #2*
   *Session 5e:* tests now cover a successful pinned HTTPS handshake given the hostname, IPv6 pins, the Unix-socket refusal, and the transport refusal on a new fetcher; the TLS trust store is documented as certifi's. Still to review: keep-alive reuse, and the discarded parent pool (finding D26, deferred).
3. **URLs that come from content**, end to end: canonicals, `og:image`, article-body links, sitemap documents and their index children, robots.txt `Sitemap:` lines, and the DEV API. Check each against a hostile site: the address screen on every hop, robots.txt, pacing, the caps, IDN hosts, `data:` and other non-http values, and DESIGN.md section 6 and principle 9 on what Cernis may fetch. *SESSION-05a #22, SESSION-05b #28*
4. **The deadline**: whether any httpcore operation escapes the wrapped stream (connection-pool waits, HTTP/2 if it is ever enabled), and how it interacts with `read_timeout`, `connect_timeout`, and pacing. *SESSION-03b #3*
   *Session 5e:* resolving is bounded by `connect_timeout`; the deadline is checked for every chunk; tests cover reads, connects across pinned addresses, the TLS handshake, and a trickled body. *Session 6a:* a budget for a whole fetch (`fetch_timeout`, 120 s; finding D33, ADR-005 amendment 2). Review: how the budget interacts with pacing waits and retries, that a robots.txt fetch is never charged to the page's budget, and that a request with no time left is never sent.
5. **The cache**, never re-audited under the one-audit rule: its bounded reads and its trust model, and `store_body=False` (neither reads nor writes the cache for the resource and its redirect targets; robots.txt still uses it; the body limit still applies). Bounded decoding, the other half of this item, was audited in the tier comparison and fixed in Session 5e. *SESSION-03b #6, SESSION-05a #26*

## 1b. Session 6a

32. **The bare `cernis` message** now describes what Cernis does and points to `cernis --help`; check it against what is published. *SESSION-06a #1*
33. **The store, when it is built**: Session 6a stopped before building it (C-5, `docs/SDK-FRICTION.md` 2026-11-04). Whatever the Owner decides, review then: single-writer locking, that a failed run is never appended, canonical JSON and its schema version, no page bodies in the store, and tamper detection (an edited, a deleted, and a truncated entry). *SESSION-06a #2*

## 2. Untrusted input Cernis parses

6. **The sitemap parser's expat configuration** (`parse_sitemap`): that no DTD, entity, or external-reference path remains on Python 3.12 through 3.14 and on older libexpat builds; the gzip member loop; the entry caps. *SESSION-05b #29*
7. **The HTML parser's robustness**: that `parse_page` cannot raise on any input (decoding, pathological nesting, huge attribute counts), the encoding-sniffing order, and what a truncated body yields. *SESSION-04a #10*
8. **The pair map loader** (`pairs.py`) as untrusted input, including `copies`. *SESSION-04b #18*

## 3. robots.txt

9. **The RFC 9309 matcher** against the RFC's full text, not only its examples: group boundaries, product-token extraction, percent-encoding normalization (including invalid sequences and non-UTF-8 bodies), the octet-length rule for patterns with `*` and `$`, ignoring non-path patterns, and the `Sitemap:` collection and `names()` added in Session 5b. *SESSION-03b #4*
   *Session 5e:* reading is version 2: a 500 KiB parsing limit, a cut-off body keeps lines ended by CR, and a 4xx is unavailable even when its body fails. The product-token rule was challenged in the tier comparison and found to follow RFC 9309 section 2.2.1 (findings D10, D11). The rest of the review remains.
10. **robots.txt redirects** restricted to `/robots.txt`, and URL normalization before the robots check (Session 3 audit fixes, never re-audited). *SESSION-03b #6*
11. **The AI crawler list**: re-verify each token against its operator's source at release, and decide whether Bytespider can be confirmed. *SESSION-05b #30*

## 4. The model: receipts, keys, and runs

12. **The receipt model as it stands** (ADR-003, ADR-004, ADR-005): every `ErrorKind`'s invariants, the 304 hash link, and `final_url`'s meaning; Phase 5's store depends on them. *SESSION-03b #5*
13. **Finding keys**, final since Session 4a: the NFC and URL-target rules, telling a URL target from a vocabulary identifier, and how site-level findings (one subject for a set, Session 5c decision 1) should be keyed in Phase 5 history. *SESSION-04a #9, SESSION-05c #34*
14. **Run validation**: every rule in `Run.__post_init__` holds for every run `audit` can build, and a failure cannot be swallowed between assembly and a report; `Run.pairs` and `Run.sources`. *SESSION-04b #15, SESSION-05a #27*
15. **`LIMIT_REACHED`** and ADR-001 amendment 2. *SESSION-05b #32*
16. **Fetch reuse** (`RunFetches`, `chain_from`): the final-URL registration, bodiless results, receipts collected once, and `known()` for the host budget. *SESSION-05a #25*

## 5. URLs, site types, and extractors

17. **URL normalization and comparison** (`urls.py`): every step against RFC 3986 section 6, IDNA (UTS 46) handling of mixed-case and invalid hosts, reason attribution (a shared normalization is never reported; the comparison is symmetric), removing dot segments, and redirect equivalence (which hops count, and whether a chain from a different requested URL can wrongly make two URLs equivalent). *SESSION-04a #8*
18. **Prefix matching** (`prefix_site`, `resolve_site`, `longest_prefix`): segment boundaries, IDN hosts, percent-encoded prefixes, a prefix that is a whole origin, the order of rules, and matching after redirects. *SESSION-04d #19*
19. **The extractors**: the selectors against DEV's and WordPress's current markup, the ambiguity rule, and `wordpress.entry` 2's share-container list against the plugins in use (five kenwalger.com posts use a container it does not yet name) and its skip-by-`mem_id` walk. *SESSION-04a #12, SESSION-05c #33*
20. **Snapshot normalization**: whether any volatile-token rule can hide a real author or platform change (the fingerprint regex, the hidden-input rule, dropping inline script contents), whether anything volatile on real DEV or WordPress pages is still missed (C-2 depends on it), and the head and frame split for metadata outside `<head>`. *SESSION-04a #11*

## 6. The checks: what counts as a defect (C-3)

21. **The peritext checks against DESIGN.md section 4**: every "Defect when" condition and that nothing else sets `defect`; the Session 4b edge cases (decisions 5 to 7). *SESSION-04b #13*
22. **The standards defects**: `peri.lang` against WCAG 2 SC 3.1.1's actual wording (and whether an invalid language tag should count); `peri.og.core` against the Open Graph protocol's required properties; `peri.og.url_matches_canonical`'s Open Graph citation. *SESSION-04d #20*
23. **Actors**: the DEV actor table against what DEV's front matter and template control; `owned` everywhere; the DEV `og:image` and `og:url` as `PLATFORM`. *SESSION-04b #13, SESSION-05a #24*
24. **Fetch outcomes**: the mapping from fetch results to reason codes, that no check runs on a page not seen whole, and the evidence each outcome carries, including the epitext questions an unread page now gets. *SESSION-04b #14*
25. **`epi.pair.canonical`**: Session 5a decisions 1 to 3, the redirect evidence passed to `compare_urls` (every receipt of the run), the reason code carried from the original, and `AMBIGUOUS` sides. *SESSION-05a #23*
26. **The sitemap defect rule**: the section (Session 5b decision 1, and D4 as decided in Session 5c: a whole-origin prefix is one section), pages expected to be absent (Session 5b decision 6), and news sitemaps. *SESSION-05b #31*
27. **Recommendation templates**: their citations (RFC 6596, RFC 9110, Open Graph, JSON-LD 1.1, sitemaps.org) for accuracy, their phrasing against the no-promise rule beyond the phrase list, and skipping `PLATFORM` defects. *SESSION-04b #16*

## 7. Reports and published documents

28. **The JSON report as a contract**: field names, the version policy (`pairs`, `sources`, `summary`, and `counts.site` added without a version change), and Markdown escaping of page text and grouping of not-determinable findings. *SESSION-04b #17, SESSION-05a #27*
29. **The run summary** against principle 2: plain counts only. *SESSION-05c #35*
30. **The README and BRAND.md** as published documents: the absolute URLs, and the claims in BRAND.md's README section. *SESSION-04d #21*

## 8. Release machinery

31. **Release machinery** (Session 2c) was audited and is unchanged; it needs no new review unless `publish.yml` changes. *SESSION-03b #7*

## Sources

`SESSION-03b.md` (items 1 to 7), `SESSION-04a.md` (8 to 12), `SESSION-04b.md` (13 to 18), `SESSION-04d.md` (19 to 21), `SESSION-05a.md` (22 to 27), `SESSION-05b.md` (28 to 32), and `SESSION-05c.md` (33 to 35): 35 items, 31 here. Merged: 22 with 28, 12 with 33, 9 with 34, 26 with part of 6, and 24 with the actor part of 13. Split: 3b #6 into items 5 and 10, and 5a #27 between items 14 and 28.
