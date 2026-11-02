# Session 5e: fixes from the tier comparison

**Date:** 2026-11-02
**Phase:** 6, in part (the pre-0.1.0 audit list, `docs/RELEASE-AUDIT.md` group 1)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

This session fixed the real findings listed in `docs/experiments/2026-11-tier-comparison.md` ("The real findings, for the release session"), in that list's order. Each behavior fix began with a test that failed, then the fix. Of the 28 findings, 24 are fixed and 4 are deferred. There were no real network requests, and no Decision Engine audit, as the session prompt required.

## Done

| Finding | Status | Test, and its first run | Change |
|---|---|---|---|
| D1 | fixed | `test_fetch_addresses.py`: 16 new refusals failed (with D3, D4, D5) | `192.0.0.0/24`, `192.88.99.0/24`, `198.18.0.0/15` refused |
| D3 | fixed | same | IPv4-translated `::ffff:0:0:0/96` decoded; Teredo judged by server and client; `64:ff9b:1::/48` refused |
| D4 | fixed | same | `100::/64`, `2001:2::/48`, `5f00::/16`, and any IPv6 outside `2000::/3` that carries no IPv4 refused |
| D5 | fixed | same | `168.63.129.16` refused; ADR-005 gap 2 stays open for the general class |
| D6 | fixed | `test_a_resolver_that_does_not_answer_in_time_is_timeout` failed | the lookup runs on a daemon thread, bounded by `connect_timeout`; `TIMEOUT` when late |
| D7 | fixed | three `test_a_compressed_body_that_ends_early_is_unreadable` cases failed | `_BodyDecoder.finish` requires the stream's end; otherwise `CONNECTION` |
| D8 | fixed | three multi-member tests failed | every gzip member decoded; zero padding ignored; data after a deflate stream's end does not decode |
| D14 | fixed, test only | two IPv6 tests passed on first run | none needed |
| D15 | fixed | two `test_a_host_the_resolver_cannot_encode_is_connection` cases failed | `UnicodeError` from the resolver is `CONNECTION` |
| D16 | fixed | `test_rules_past_the_parsing_limit_are_ignored` failed | `robots.PARSE_LIMIT`, 500 KiB |
| D17 | fixed, test only | `test_https_dials_the_pinned_address_and_verifies_the_hostname` passed | the fake stream can complete a handshake and records the hostname |
| D18 | fixed, test only | `test_each_read_waits_no_longer_than_the_time_left` passed | the fake stream records each read's timeout |
| D19 | fixed, test only | `test_the_deadline_is_cleared_between_requests` (now through the fetcher) passed | the old test was renamed to what it checks, `test_bounded_shrinks_a_timeout_to_the_time_left` |
| D21 | fixed, test only | connect, TLS handshake, and trickled-body deadline tests passed | the body test first sat exactly on the deadline (159 bytes in ten reads); its body was lengthened |
| D22 | fixed, test only | `test_unix_sockets_are_refused` passed | none needed |
| D23 | deferred | none | see Deferred |
| D24 | fixed, test only | the localhost refusal test now uses a new fetcher | it no longer depends on the server closing connections |
| D25 | fixed, docstring | none: no executable behavior | `GuardedTransport` says TLS trusts certifi's bundle |
| D26 | deferred | none | see Deferred |
| D27 | deferred | none | ADR-005 gap 3 kept open; amendment 1 says why |
| D28 | fixed | `test_a_4xx_robots_txt_counts_by_its_status_even_if_its_body_fails` failed | a 4xx (not 429) robots.txt is `UNAVAILABLE` whatever its body did |
| D30 | fixed | the CR case of `test_a_cut_off_robots_txt_keeps_its_whole_lines_whatever_ends_them` failed | the cut keeps the last LF or CR |
| D31 | fixed | `test_a_trailing_dot_names_the_same_host_for_pacing` failed | the pacing key drops a trailing dot |
| D33 | deferred, docstring corrected | none | `FetchConfig.total_timeout` now says it bounds each request, not a fetch |
| D34 | fixed | the raw, split-at-1 case of `test_a_deflate_body_trickled_from_its_first_byte_is_decoded` failed | raw deflate is possible until the wrapped reading produces output; the bytes are replayed |
| D35 | fixed | two tests failed (the fetcher's, and `RunFetches` reuse) | fragments dropped in `fetch`, `_redirect_target`, and the `RunFetches` key |
| D36 | fixed | `test_a_chunk_that_reaches_the_limit_after_the_deadline_is_timeout` failed | the deadline is checked as each chunk arrives |
| D37 | fixed, the verified part | `test_without_storing_the_resource_its_robots_txt_is_still_cached` failed | robots.txt uses the cache during a `store_body=False` fetch |

**Records updated:**

- ADR-005 amendment 1: the new ranges and forms, the bounded lookup, and the open gaps after it.
- ADR-003 amendment 2: complete streams, gzip members, raw deflate, and the per-chunk deadline.
- DESIGN.md section 6, draft 2.9.
- Docstrings: `client.py` (module, `FetchConfig`, `fetch`), `robots.py`, `rfc9309.py`, `addresses.py`, and `network.py`.
- CHANGELOG: Changed and Security.
- CLAUDE.md: current stage.
- The experiment document: a status on each real finding.
- `docs/RELEASE-AUDIT.md`: see decision 7.

**Versions:**

- `MATCHER_VERSION` is 2, so `epi.robots.access` is `1+c1+m2`.
- The golden reports were regenerated with `CERNIS_UPDATE_GOLDEN=1`. Their diff is the version string only: 42 findings and the check list.

## Decisions

1. **The session prompt arrived as pasted text with no other message.** It followed directly from the experiment document, so it was carried out as the author's prompt.
2. **D37 keeps redirect targets out of the cache.** The prompt said to skip the cache "for the requested URL only". The verified defect was robots.txt being kept out of the cache, and that is fixed. The redirect targets of a `store_body=False` fetch still skip the cache, because they are the resource. An `og:image` that redirects to a CDN must never be stored (`fetch`'s docstring, DESIGN.md section 6: "the cache never holds them"). `test_without_storing_neither_the_resource_nor_its_redirect_target_is_cached` holds this.
3. **One version covers robots.txt reading.** `MATCHER_VERSION` now versions both which rules are read (`RobotsPolicy`: the parsing limit, the cut, the 4xx rule) and how they are matched. Its docstring says so. The fetcher has no version of its own, and receipts carry `cernis_version`, so no other check's version changed.
4. **Address ranges.**
   - All of `192.0.0.0/24` is refused, including the two addresses IANA lists as globally reachable (`192.0.0.9`, `192.0.0.10`), which Cernis never needs.
   - For IPv6, everything outside `2000::/3` that carries no IPv4 is refused. A list of the reserved blocks there would be longer and easier to get wrong.
   - The documentation ranges stay open (Session 3b decision 4), and that now includes `3fff::/20`.
   - The IANA registries themselves were not consulted in this session, so comparing the lists with them stays on the release audit.
5. **The DNS bound is `connect_timeout`, not the request deadline.** Resolving comes before pacing and before the deadline starts, and a name is resolved for every hop. A lookup that never returns is abandoned on its daemon thread; it cannot be cancelled.
6. **The parsing limit is 500 KiB, RFC 9309's minimum.** Measured in the tier comparison, a 5 MiB robots.txt held about 105 MB; the cap bounds that at roughly a tenth per origin. The number of origins per run is still unbounded.
7. **`docs/RELEASE-AUDIT.md`: only the bounded-decoding half of item 5 was removed.** Each item there is a review wider than the findings it contained: item 1 asks for the IANA comparison and the remaining gaps, item 4 for connection-pool waits. Removing them would claim reviews that did not happen. Items 1, 2, 4, and 9 carry a Session 5e note instead, naming what was fixed and what remains, including the deferred findings.
8. **Test-only findings have no failing first run.** Each was a missing test for behavior that turned out correct. The test is the fix.
9. **No Decision Engine audit**, as the prompt required. The author's AQG policy would route this change to `deep`: it changes trust-boundary input handling, the address screen. So the audit-before-commit gate is not met by this session, and whether to audit before committing is the author's decision.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`:

- ruff check
- ruff format check
- mypy strict (68 files)
- pydoclint
- pytest: 1179 passed (1115 before, 64 new)
- the isolated Python 3.12 pytest: 1179 passed

## Deferred

- **D23: integer and hex IPv4 host forms against the real resolver.** A test needs the system resolver, which the test network guard refuses for any non-local name, by design. The screen judges whatever the resolver returns, so the risk is in the platform resolver.
- **D26: the discarded parent pool.** It holds no connections. Not building it would mean bypassing `HTTPTransport.__init__`, more private coupling to httpx than the cost it removes.
- **D27: ports.** ADR-005 gap 3 is kept open: author-named URLs and local tests use other ports.
- **D33: a budget for a whole fetch.** This is a design decision. A robots.txt fetch cut short by such a budget would count as unreachable and disallow its origin for the rest of the run. The docstring's overclaim is corrected.
- **SDK friction:** none this session; the SDK was not used.

## Not touched

- The cache module, the parsers, the checks, and the reports, apart from the golden version strings.
- The product-token rule: findings D10 and D11 were wrong, as recorded in the experiment.
