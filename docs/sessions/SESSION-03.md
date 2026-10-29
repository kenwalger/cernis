# Session 3: Phase 2, the fetcher

**Date:** 2026-10-29
**Phase:** 2 (DESIGN.md section 10)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

Fetching and receipts only. No HTML parsing, no checks, no snapshots, no findings.

## Built

- **httpx, the first runtime dependency** (`httpx>=0.28.1`, added with `uv add`). DESIGN.md section 6 names it for fetching. It brings certifi, h11, httpcore, idna, and anyio. Nothing else in Cernis needs it yet, and the standard library has no HTTP client with streaming, per-phase timeouts, and a pluggable transport for tests.
- **`src/cernis/fetch/client.py`: the `Fetcher`.** One fetcher is one run. `fetch(url)` checks robots.txt, follows redirects by hand (at most 10; one more is `TOO_MANY_REDIRECTS`), retries `429` and `503`, and returns a `FetchResult`: one `Receipt` per attempt, the robots.txt receipts and decisions it rests on, the URL robots.txt disallowed (if any), and the last body. User agent `Cernis/<version> (+https://github.com/kenwalger/cernis)`. Timeouts are configurable: connect 10 s, read 20 s, and a 60 s `total_timeout` per request, checked when the headers arrive and after each chunk. Body limit 5 MB by default. Receipts record the DESIGN.md header subset (repeats joined with `, `) and the SHA-256 of the decoded body. No cookies are stored or sent, no environment settings are read (`trust_env=False`), and URLs with user information are refused.
- **`src/cernis/fetch/robots.py`.** RFC 9309 status rules: `2xx` (or a `304` validating a cached copy) is parsed with `urllib.robotparser` for Cernis's user agent; `4xx` other than `429` allows everything; `5xx`, `429`, and no response disallow everything. robots.txt is fetched once per origin per run, and its fetch is a receipt. A disallowed URL is not requested, and `FetchResult.disallowed_url` names it, for Phase 3's `DISALLOWED_BY_ROBOTS`. Each redirect target is checked against its own origin's robots.txt before it is requested.
- **`src/cernis/fetch/pacing.py`.** At most one request per second per host by default (`min_interval`), counting robots.txt and every redirect hop. The monotonic clock, the sleep, and the wall clock are injected, so no test waits.
- **`src/cernis/fetch/cache.py`.** Conditional requests from `ETag` and `Last-Modified`. The cache defaults to `.cernis-cache/` (now in `.gitignore`), can be moved with `--cache-dir`, and writes a `.gitignore` of `*` into a directory it creates. A `304` is recorded as `304` with the cached body's hash as `body_sha256`.
- **`Receipt.body_truncated_at`** (ADR-003) and the failed-request rules (ADR-004), below.
- **`cernis fetch <url> [--format text|json] [--cache-dir PATH]`** prints the robots.txt receipts, the robots decisions, and each attempt's receipt. It exits 0 whatever the HTTP result, and 2 for a URL it will not fetch.
- **`REPOSITORY_URL`** moved to `cernis/__init__.py`, so the user agent and the CLI share it.
- **Tests.** `httpx.MockTransport` covers every case in the session prompt: 200, 301 chains (every redirect status), 304, 401, 403, 404, 410, 429 with and without `Retry-After` (seconds, HTTP date, past date, over the cap, unreadable), 503, other 5xx, all four httpx timeouts, a body that stalls, a body slower than `total_timeout`, connection and TLS errors, oversized bodies, the redirect limit and loops, and every robots.txt case. `tests/test_fetch_localhost.py` runs a real HTTP server on 127.0.0.1 to show the TIMEOUT and TLS mapping holds for the exceptions httpx really raises. `tests/conftest.py` has an autouse network guard: a connection or name lookup for anything but loopback or `localhost` raises and is recorded, and a recorded attempt fails the test in teardown even if library code caught the error. A pytester test proves that.

## Decisions

1. **Oversized bodies (ADR-003).** Reading stops at the limit; the receipt has `body_sha256` `None` and `body_truncated_at` set to the limit. A prefix hash would claim to be the body's hash, and reading on to get the true hash defeats the limit.
2. **Each attempt gets its own receipt.** A receipt is the record of one fetch. Folding retries into one receipt would hide the `429`s and the `Retry-After` values that justified the waits, which are exactly the evidence a `RATE_LIMITED` finding needs. A retry starts again from the requested URL, so each receipt stands alone.
3. **A redirect to a disallowed URL is not followed.** The 3xx is the final response, and `disallowed_url` names the target.
4. **A `429` robots.txt disallows everything.** RFC 9309 counts 429 as a 4xx (allow all), and the session prompt says "a 4xx robots.txt means everything is allowed". A server that is rate limiting Cernis has not said it may crawl, so the conservative reading was taken. This is a deviation from the prompt, now an Owner decision (A17 below).
5. **robots.txt matching depends on the Python version.** Found this session: on Python 3.14, `urllib.robotparser` applies the most specific rule and honors `*` and `$`; on 3.12 and 3.13 it applies the first matching rule and treats `*` and `$` as literal characters. The same robots.txt can get a different decision on a different Python. DESIGN.md section 6 and the session prompt both name `urllib.robotparser`, so it stays. `test_the_longest_match_wins` and `test_wildcards_are_honored` pin each version's behavior (strict xfail before 3.14), so a change on either side is noticed. Owner decision A16 below.
6. **URLs are normalized before anything else.** `fetch()` replaces the URL with httpx's normalized form, so robots.txt, the request, the cache key, and the receipt all name the resource actually requested.
7. **`fetched_at` is when the first request was sent, after the pacing wait.** The first real request showed the receipt time being taken before the wait (the page receipt 0.38 s after robots.txt, with a 1 s interval). Fixed, with `test_fetched_at_is_when_the_first_request_was_sent_after_pacing` (RED first).
8. **Location headers are hidden from httpx's client.** Even with `follow_redirects=False`, httpx builds the next request for every redirect and raises on a `Location` it cannot parse, before the fetcher sees the response. A thin transport wrapper moves `Location` into a response extension, so every redirect decision is the fetcher's.
9. **Tooling.** Ruff's D107 (docstring on `__init__`) is ignored, because pydoclint's DOC301 requires `__init__` parameters in the class docstring, as the dataclasses already do. pydoclint `check-yield-types` is off, matching `check-return-types`. Neither weakens a rule the code follows.

## Real requests

The only two real requests this session made, both with `uv run cernis fetch` and the default cache. They ran before the audit fixes; the receipt format then had no `final_url` on failures, which neither run hit.

**https://kenwalger.com/** (run before decision 7's fix):

- `r-001` robots.txt: `https://kenwalger.com/robots.txt`, 200, no redirect, `fetched_at` 2026-10-29T20:57:53.066846Z, `body_sha256` `e8cd527acd9028df23cfd7cf16981cc4fe520fbbccbe09ba0f653b3f232b9b20`, `content-type: text/plain`, `etag: "55e2d23-24-5501160305680"`, `last-modified: Sun, 21 May 2017 23:47:22 GMT`.
- Decision: allowed (RULES, `r-001`).
- `r-002` page: `https://kenwalger.com/`, 200, no redirect, `fetched_at` 2026-10-29T20:57:53.449736Z, `body_sha256` `4f1b0c3d65ddb0096f69b9e2e9e961fd31ffe6fe439f9a102b205ebc29f4d5f4`, `content-type: text/html; charset=UTF-8`, no validators (so not cached).

**https://dev.to/kenwalger/views-measure-views-4co7** (after decision 7's fix):

- `r-001` robots.txt: `https://dev.to/robots.txt`, 200, no redirect, `fetched_at` 2026-10-29T21:30:29.363540Z, `body_sha256` `983a578c850154f61ee9f3bead038657f65cb9fbed891eddf8e95135989e4855`, `content-type: text/plain; charset=utf-8`, `etag: W/"3cb6b19ce4e1d8efe9cbc041a341ba6d"`.
- Decision: allowed (RULES, `r-001`).
- `r-002` page: 200, no redirect, `fetched_at` 2026-10-29T21:30:30.364141Z (1.0006 s after robots.txt: pacing holds), `body_sha256` `6d50445d868eb38fcbc7284e7f30c8e600c7392d50c5d926ccf01679380f56a5`, `content-type: text/html; charset=utf-8`, `etag: W/"844f0240e10475220d72c8e3795d0cf4"`.

Both user agents were `Cernis/0.1.0.dev0 (+https://github.com/kenwalger/cernis)`.

## Decision Engine audit

- **audit_id:** `aud_K8j95M7gmH` (the run ID; the result carries no separate `audit_id` field)
- **Mode:** `deep`, stakes `high`, intent `prescriptive`, tier `reasoning`
- **Submission canonical SHA:** `b204a5dc5ecc0dc4be7cfe75b16370548444ffd44fa4da27184f4f2c37de3528` (result envelope: `dd204066aca2d5692b6d3b53f80853c21cc2d160b8f80384e01de526e3d73e75`)
- **Artifact:** `src/cernis/fetch/` (client, robots, cache, pacing), the `Receipt` excerpt with `body_truncated_at`, a summary of the `cernis fetch` CLI, the `tests/conftest.py` guard, a summary of ADR-003, and the session decisions. Test files were described, not sent.
- **Panel:** five auditors from five vendors, here Voice 1 to Voice 5. All five completed, with no partial failures and no fallbacks.
- **Verdicts:** 4/5 `has-serious-issues`, 1/5 `solid` (Voice 2, no findings). 30 findings (3, 0, 11, 10, 6 by voice), 13 flagged blocking: V1 f1, V1 f2, V1 f3, V3 f1, V4 f1 to f7, V5 f2, V5 f3.
- **One audit only**, as the session prompt required. The fixes below were not re-audited.

### Adjudication

Each finding was checked against current evidence before it was classified; panel majority decided nothing. Duplicates are merged into 18 rows: accepted 12, rejected 3, needs-user-decision 3. "Voices" counts how many of the five raised it.

Of the 13 blocking findings, 10 are accepted and fixed (A1, A2, A3, A5, A7, A8, A14; V5 f2 counted here for its first two parts), two are rejected (V4 f4 as A4, V4 f7 as A10), and one is an Owner decision (V4 f1, as A15). Two direct checks settled claims: robotparser's `parse()` does call `modified()` on 3.12 and 3.14 (A18 rejected), and `https://ex.com/a/../private/x` is allowed by robotparser under `Disallow: /private` while httpx sends `GET /private/x` (A5 confirmed).

| finding | decision | action | verification |
|---|---|---|---|
| A1. Voices 3 (V1 f1, V3 f7, V4 f5; major, blocking): a robots.txt fetch follows a redirect to any URL, which is requested without its own robots.txt check. | accepted | While fetching robots.txt, a redirect is followed only to a URL whose path is `/robots.txt` with no query; any other target is not requested, the 3xx is final, and robots.txt is unreachable (disallow all). | `test_a_robots_txt_redirect_to_a_page_is_not_followed` (RED before the fix); `test_a_redirected_robots_txt_is_followed` still passes. |
| A2. Voices 4 (V1 f2, V3 f5, V4 f2, V5 f2 parts 1 and 2; major, blocking): a timeout, reset, total-timeout, or decode failure after the headers arrived is recorded as "no response", dropping the status and headers. | accepted | ADR-004: `TIMEOUT`, `CONNECTION`, and `TLS` receipts keep the status and headers that arrived; `body_sha256` is `None`. `_exchange` keeps the status and headers across body failures. | `test_a_timeout_while_reading_the_body_is_timeout`, `test_a_connection_reset_while_reading_the_body_keeps_the_status`, `test_receipt_keeps_a_response_whose_body_failed`, `test_receipt_partial_response_has_no_body_hash` (RED first). |
| A3. Voices 1 (V5 f3; major, blocking): after a redirect, a failed request's receipt does not name the URL that failed. | accepted | ADR-004: `final_url` is required on `TIMEOUT`, `CONNECTION`, and `TLS` receipts and names the URL whose request failed. | `test_an_error_after_a_redirect_keeps_the_chain` asserts `final_url == OTHER`; `test_receipt_failed_request_must_name_the_url_that_failed`. |
| A4. Voices 3 (V4 f4, V5 f2 part 3, V3 f5 part; major, blocking): TOO_MANY_REDIRECTS drops the last 3xx status and headers. | rejected | The last URL that redirected is on `redirect_chain`, which by definition answered with a redirect that was followed; there is no final response to record. The model docstring now says "no final response" instead of "no response". | `test_an_eleventh_redirect_is_too_many` checks the chain holds all 11 URLs; `Receipt` docstring (ADR-004). |
| A5. Voices 1 (V3 f1; major, blocking): robots.txt is checked against the raw URL, but httpx sends its normalized form (`/a/../private/x` becomes `/private/x`). | accepted | `fetch()` replaces the URL with `str(httpx.URL(url))` before the robots check, the request, the cache key, and the receipt. | Confirmed on 3.12 and 3.14 before the fix. `test_the_url_is_requested_and_recorded_in_its_normalized_form` (RED first). |
| A6. Voices 1 (V3 f2; major): httpx decompresses each chunk without bound, so a gzip bomb or stacked codings exceed the limit in memory. | accepted | `Accept-Encoding: gzip, deflate` fixed; bodies read with `iter_raw()` and decoded by `_BodyDecoder` with `zlib` `max_length`; stacked or unoffered codings and corrupt data are `CONNECTION` with the status kept; the limit counts received and decoded bytes. ADR-003 amendment 1. | httpx `_decoders.py` calls `decompress(data)` with no bound (checked). `test_a_compressed_body_is_never_decoded_past_the_limit` (20 MB of zeros, limit 1000), `test_a_body_in_an_unsupported_coding_is_unreadable`, `test_a_corrupt_gzip_body_is_unreadable`, `test_a_deflate_body_is_decoded_wrapped_or_raw`, `test_only_gzip_and_deflate_are_offered`. |
| A7. Voices 2 (V1 f3, V4 f6 part; major, blocking): cache files are read whole with no size cap or regular-file check. | accepted | `_read_bounded` reads only regular files, at most 16 KiB for an entry and `max_body_bytes` for a body; anything larger is a miss. | `test_an_entry_too_large_to_be_one_is_a_miss`, `test_a_body_that_is_not_a_regular_file_is_a_miss`. |
| A8. Voices 2 (V3 f9, V4 f6 part; major, blocking): a 304 reuses a cached body larger than the current limit, with a hash and no truncation marker. | accepted | `Cache` takes `max_body_bytes`; a larger cached body is a miss, so no conditional request is sent. | `test_a_cached_body_over_the_limit_is_a_miss`. |
| A9. Voices 1 (V3 f10; minor): a deeply nested entry raises `RecursionError`; a damaged body file is never rewritten. | accepted | `lookup` catches `RecursionError`; `store` rewrites a body file whose hash does not match. | `json.loads("[" * 100000)` raises `RecursionError` (checked). `test_a_deeply_nested_entry_is_a_miss`, `test_a_damaged_body_is_rewritten_on_the_next_store`. |
| A10. Voices 1 (V4 f7; major, blocking): anyone who can write the cache can plant a body a 304 will treat as validated. | rejected | The cache is the user's own local state, like a browser cache; writing to it already requires the user's file permissions. Authenticating entries would need a stored secret, which the MVP does not have. The cache docstring now says its hashes detect damage, not tampering. | `src/cernis/fetch/cache.py` module docstring. |
| A11. Voices 1 (V4 f10; major): the cache writes a `.gitignore` of `*` into any directory, hiding a project from git with `--cache-dir .`. | accepted | The `.gitignore` is written only into a directory the cache creates. | `test_an_existing_directory_gets_no_gitignore`; `test_the_cache_directory_ignores_itself` still passes. |
| A12. Voices 1 (V3 f8; minor): a robots.txt cut off at the limit has its partial last line parsed as a rule. | accepted | When `body_truncated_at` is set, everything after the last newline is dropped before parsing. | `test_a_line_cut_off_at_the_limit_is_not_a_rule` (RED first). |
| A13. Voices 2 (V3 f4, V5 f4; major/minor): `total_timeout` is not checked for the header phase, redirects, or 304s. | accepted | The deadline is now checked as soon as the headers arrive (covering 3xx and 304) and after every body chunk. The header phase itself is still bounded only per read by `read_timeout`; a whole-request watchdog is deferred below, not yet approved by the Owner. | `test_total_timeout_is_checked_once_the_headers_arrive`. |
| A14. Voices 2 (V4 f3, V5 f6; major/minor): an unfollowed 3xx is not on `redirect_chain`, contradicting "every URL that answered with a redirect". | accepted | The contract now says what the code does: `redirect_chain` lists URLs whose redirects were followed; an unfollowed redirect is the final response (`final_url` and its 3xx `status_code`). V4's code change is not adopted, because it would list the final URL twice. | `Receipt` docstring (ADR-004); `test_a_redirect_that_cannot_be_followed_is_the_final_response`, `test_a_redirect_to_a_disallowed_url_is_not_followed`. |
| A15. Voices 2 (V3 f3, V4 f1; major, V4 blocking): redirects (and later, links) can reach loopback, private, link-local, or cloud metadata addresses (SSRF). | needs-user-decision | Decision actor: the Owner. Question: is Cernis only a local CLI on the author's own URLs, or will it run in CI or cloud hosts, or be used as a library on untrusted URLs? Recommendation: before Phase 4 (`epi.links.resolve` fetches links from pages), refuse non-global addresses by default, checked on the resolved peer address, with an opt-in for localhost auditing. Blocked action: Phase 4 link fetching. | Confirmed: `_redirect_target` checks only scheme, host, and user information. Owner's answer recorded in a later session record. |
| A16. Voices 3 (V3 f6, V3 f11, V4 f8, V5 f5; major): robots matching differs by Python version (decision 5); robotparser also matches user agents by substring and does not record which rule decided. | needs-user-decision | Decision actor: the Owner. Question: replace `urllib.robotparser` (named in DESIGN.md section 6 and the session prompt) with an in-tree RFC 9309 matcher, require Python 3.14 for fetching, or keep it with the skew recorded? Recommendation: an in-tree matcher (group selection by product token, longest match, `*` and `$`), recorded in the decision, before Phase 4's `epi.robots.access`. Blocked action: none in Phase 2; Phase 4 robots findings. | Checked: 3.12 and 3.13 give first-match and literal wildcards, 3.14 the RFC answers; `User-agent: e` blocks Cernis on both. Strict xfail tests pin each version. |
| A17. Voices 1 (V4 f9; minor): a `429` robots.txt is treated as disallow-all, but RFC 9309 and the session prompt say every 4xx allows all. | needs-user-decision | Decision actor: the Owner. Question: keep the conservative reading (decision 4) or follow the prompt and the RFC? Blocked action: none; the current behavior fails closed. | `src/cernis/fetch/robots.py` (`status != 429`); `test_an_unreachable_robots_txt_disallows_everything` (the 429 case). |
| A18. Voices 1 (V5 f1; major): `can_fetch` always returns False on 3.12 and 3.13 because `last_checked` is never set. | rejected | `RobotFileParser.parse()` calls `self.modified()`, which sets `last_checked`. | On 3.12.4 and 3.14.5: `last_checked` is set after `parse()`, and `can_fetch` allows `/ok` under `Disallow: /private`. `test_an_allowed_url_is_fetched_with_its_decision` passes on both. |

### Changes from the audit

- **Model (ADR-004).** Failed requests name the URL that failed; a response whose body failed keeps its status and headers; `body_sha256` and `body_truncated_at` only on `NONE`; headers require a status; the redirect chain is the followed redirects.
- **Client.** Normalized URLs; robots.txt redirects only to `/robots.txt`; bounded gzip and deflate decoding with a fixed `Accept-Encoding`; the deadline checked when headers arrive; body-phase failures keep what arrived.
- **Cache.** Bounded, regular-file-only reads; the body limit applied to cached bodies; `RecursionError` caught; damaged bodies rewritten; `.gitignore` only in a directory it creates; the trust model stated.
- **robots.txt.** The partial last line of a cut-off file is dropped.
- **ADR-003 amendment 1** corrects its last consequence.
- **Test helper.** `respond()` and the default 404 now send streamed bodies, as real transports do; httpx reads a `content=` body eagerly, which `iter_raw()` refuses.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH` (where `bash` resolves to the WSL launcher): ruff check, ruff format check, mypy strict (28 files), pydoclint, pytest (438 passed on Python 3.14), and the isolated Python 3.12 pytest (435 passed, 3 xfailed: the robotparser version tests, as intended).

## Deferred

- **Owner decisions A15 (SSRF policy), A16 (robots matching), A17 (429 robots.txt).**
- **A whole-request deadline** covering the header phase (A13's remainder): a server sending headers one byte per read can hold one request for `read_timeout` per read. Needs a watchdog or a deadline-driven transport.
- **Cache eviction.** Bodies are content-addressed and never removed; `drop` removes entries only.
- **CLI flags** for timeouts, pacing, and the body limit. They are `FetchConfig` settings; `cernis fetch` exposes only `--cache-dir`.
- **`Vary`** is ignored by the cache. Cernis always sends the same request headers, so it does not matter yet.
- **Crawl-delay** is not read. RFC 9309 does not define it, and pacing is one request per second regardless.

## Not touched

- `CHANGELOG.md`: Phase 2 lines added under `[Unreleased]` only.
- `docs/SDK-FRICTION.md`: no Sovereign Systems SDK code was used this session, so there is nothing to log.
