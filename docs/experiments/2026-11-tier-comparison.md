# Tier comparison: fast, standard, and deep Decision Engine audits on identical code

**Started:** 2026-11-02T21:31:53Z
**Commit audited:** `9d27005ff3f141979ddeeaf5dc8f4da4d3255f82`

No code changes were made. Findings are verified and recorded here, never fixed.

## Claims

Fixed on 2026-11-02, before any audit ran, copied verbatim from the session prompt:

- T-1: Standard finds at least 80% of the deep panel's verified real findings.
- T-2: Fast finds at least 50% of the deep panel's verified real findings.
- T-3: Deep finds at least one verified real finding, rated high severity or above, that neither fast nor standard found. Falsified if none.

## Setup

**Scope.** The network-safety group of `docs/RELEASE-AUDIT.md` (items 1 to 5, and the matcher of item 9). The Decision Engine takes an artifact inline only, and the full scope with every test file was about 176 KB, too large to send reliably three times as identical inline copies. Following CLAUDE.md ("audit fewer files in full rather than more files in summary"), the artifact holds these files in full, each under a `===== FILE: <path> =====` line:

- `src/cernis/fetch/__init__.py`, `addresses.py`, `network.py`, `pacing.py`, `robots.py`, `rfc9309.py`, `client.py`
- `tests/fetch_support.py`, `test_fetch_addresses.py`, `test_fetch_ssrf.py`, `test_fetch_network.py`, `test_fetch_localhost.py`

Left out: `src/cernis/fetch/cache.py`, `tests/test_fetch_client.py` (the retry and deadline tests), `test_fetch_rfc9309.py`, `test_fetch_robots.py`, `test_fetch_pacing.py`, and `test_fetch_cache.py`. The audit context said so, and named `cernis.model` and `cernis.urls.normalize_percent_encoding` as absent. The excluded files were used during verification.

**Artifact.** 103,059 bytes, 2,670 lines, SHA-256 `e42d212e86813f6171cfe8d77f8cd9b481e476f915d897f9fde8e075120e99bb`. Each submission pasted it inline. The engine reported 101,736 characters for both the fast and standard runs. The three inline copies cannot be checked byte for byte against the file, so their identity rests on being pasted from the same file each time.

**Identical instructions.** Title "Cernis network-safety code: tier comparison", stakes `high`, intent `prescriptive`, focus "security, correctness, resource exhaustion, missing tests", domain `engineering`, and the same context paragraph. Only `audit_mode` and `client_request_id` differed.

**Severity.** The engine rates `critical`, `major`, or `minor`; it has no "high". For T-3, "high severity or above" is read as `major` or `critical`. A distinct finding takes the highest rating any matched raw finding gave it.

**Two voices returned output the engine did not parse.** Both are counted here, because the voice raised the findings. The claims are also computed on the engine-parsed findings alone.

- Standard, `claude-sonnet-5-5`: 12 findings, but the JSON is invalid at character 7,172 (finding f5's evidence is a parenthesized string concatenation). The engine's panel shows it as "(no verdict), 0 findings".
- Deep, `gemini-3.8-flash-high`: 6 findings in a fenced JSON block that ends partway through f6. The engine's panel shows "(no verdict), 0 findings".

## Runs

All three were submitted before any finding was verified, and all three had finished before verification began. Times are UTC. The records carry no run-level start or end time, so an audit's wall time runs from its earliest voice start to its latest voice completion.

| Tier | Audit id | Status | Voices that ran (role, vendor, model) | Substitution or dropout | Wall time |
|---|---|---|---|---|---|
| fast | `aud_UsrjzfzYd0` | partial | `openai`: OpenAI gpt-5.6-terra; `google`: DeepSeek deepseek-v4.1-flash | The `google` role ran a DeepSeek model (`used_fallback: true`, `fallback_kind: model`), which failed: "deepseek: 2xx response had no message.content". One voice produced findings. | 21:37:26 to 21:47:01, 574.9 s |
| standard | `aud_r7xrsMQcXA` | completed | `openai`: OpenAI gpt-6-sol; `google`: Google gemini-3.8-flash-high; `primary`: Anthropic claude-sonnet-5-5 (reasoning high) | None. The Claude voice's output was not parsed (see Setup). | 21:41:44 to 21:47:20, 336.4 s |
| deep | `aud_ZDSjzlcYvi` | partial | `openai`: OpenAI gpt-6-sol; `google`: Google gemini-3.8-flash-high; `primary`: Anthropic claude-opus-5-5 (reasoning high); `feat`: DeepSeek deepseek-flash | DeepSeek failed (`used_fallback: true`, `fallback_kind: model`): "model_not_found ... No available channel for model deepseek-flash". The Gemini voice's output was not parsed (see Setup). | 21:46:02 to 21:52:40, 398.1 s |

Costs: to be added from the billing page.

## Merge

**Raw finding labels.** Tier (`F` fast, `S` standard, `D` deep), then voice (`o` OpenAI, `g` Google, `c` Claude), then the voice's own finding number. For example, `S.c5` is standard's Claude voice, f5.

**Matching rules.**

1. Two findings are the same if they describe the same problem at the same location.
2. A raw finding that bundles several problems is split, and each part is matched on its own. These were split: F.o1, S.o1, S.c1, S.c3, S.c5, S.c6, S.c11, D.o1, D.o3, D.c3, D.c6, D.c11, and D.g6.
3. A missing-test finding about a behavior that another finding already raises as a defect is matched to that defect. This applies to F.o5 (to D7), and to D.g6's parts (to D37, D11, and D13).
4. The address-screen findings are split by range and mechanism, because their verdicts differ:
   - D1: IPv4 special-purpose ranges, other than documentation.
   - D2: documentation ranges.
   - D3: IPv4 hidden in IPv6 translation forms.
   - D4: other non-global IPv6.
   - D5: public cloud endpoints.
5. F.o1 says the IPv6 list "omits many IPv6 special-use ranges", but the only IPv6 range it names is 2001:db8::/32. It is matched to D2 only, not to D4.
6. Two pairs of findings share a location but are distinct problems:
   - The product token: D10 says it is too permissive, D11 that it is too strict.
   - The gzip decoder: D7 is a truncated stream, D8 a multi-member stream.

| Raw | Engine severity | Claim, in brief | Distinct |
|---|---|---|---|
| F.o1 | major | Screen allows documentation and benchmarking ranges (198.18/15, 192.0.2/24, 198.51.100/24, 203.0.113/24, 2001:db8::/32) | D1, D2 |
| F.o2 | major | DNS resolution is outside `total_timeout` | D6 |
| F.o3 | major | Truncated gzip or deflate is recorded as complete, with a hash | D7 |
| F.o4 | minor | Redirect cycles are followed to the limit, against the docstring | D9 |
| F.o5 | minor | No test for a truncated compressed body | D7 |
| S.o1 | critical | 198.18/15 and local-use NAT64 64:ff9b:1::/48 allowed | D1, D3 |
| S.o2 | major | DNS outside the deadline | D6 |
| S.o3 | major | Truncated gzip or deflate gets a successful receipt | D7 |
| S.o4 | major | `User-agent: Cernis2` is taken as a Cernis group | D10 |
| S.g1 | critical | SIIT `::ffff:0:0:0/96` and 64:ff9b:1::/48 not decoded | D3 |
| S.g2 | major | Product token regex drops digits | D11 |
| S.g3 | minor | Terminal redirect bodies are not read or hashed | D12 |
| S.g4 | minor | `Location` missing from receipt headers | D13 |
| S.g5 | minor | No IPv6 tests through GuardedBackend | D14 |
| S.c1 | major | Missing ranges: 192.0.0.0/24, 198.18/15, documentation ranges, 192.88.99/24, Azure 168.63.129.16, 2001:db8::/32, 100::/64, 64:ff9b:1::/48, Teredo | D1, D2, D3, D4, D5 |
| S.c2 | major | A hostname IDNA cannot encode raises UnicodeError and crashes `fetch` | D15 |
| S.c3 | major | No gzip eof check; later gzip members dropped | D7, D8 |
| S.c4 | major | Parsed robots rules are kept without bound | D16 |
| S.c5 | major | Tests check less than their names say: (1) TLS hostname, (2) read timeout ignored, (3) deadline cleared, (4) rebinding, (5) untested paths, (6) keep-alive dependence | D17, D18, D19, D20, D21, D22, D23, D24 |
| S.c6 | minor | "System trust store" is really certifi; an unused parent pool | D25, D26 |
| S.c7 | minor | Ports are not restricted | D27 |
| S.c8 | minor | DNS outside every timeout | D6 |
| S.c9 | minor | `Location` lost from recorded headers | D13 |
| S.c10 | minor | A 4xx robots.txt in an unsupported coding becomes UNREACHABLE | D28 |
| S.c11 | minor | (a) Received bytes past the limit mark a body truncated; (b) a CR-only truncated robots.txt is emptied | D29, D30 |
| S.c12 | minor | Pacing keyed by the literal host (trailing dot) | D31 |
| D.o1 | critical | 198.18/15 and 2001:db8::/32 allowed | D1, D2 |
| D.o2 | major | DNS outside the deadline | D6 |
| D.o3 | major | Multi-member gzip robots.txt loses rules; a missing trailer is accepted | D7, D8 |
| D.o4 | minor | An oversized final chunk skips the deadline check | D36 |
| D.o5 | minor | No successful pinned-HTTPS test | D17 |
| D.c1 | major | UnicodeError from getaddrinfo crashes `fetch` | D15 |
| D.c2 | major | A non-ASCII cached ETag crashes the next request | D32 |
| D.c3 | major | Missing ranges: 192.0.0.0/24, 198.18/15, 64:ff9b:1::/48, Teredo, 100::/64 | D1, D3, D4 |
| D.c4 | major | `total_timeout` restarts on every hop and retry; the whole fetch is unbounded | D33 |
| D.c5 | minor | A truncated robots.txt with no LF is emptied, allowing everything | D30 |
| D.c6 | minor | No gzip eof check; raw-deflate fallback only on the first chunk; received bytes mark truncation; multi-member gzip | D7, D34, D29, D8 |
| D.c7 | minor | DNS has no timeout | D6 |
| D.c8 | minor | certifi, not the system trust store | D25 |
| D.c9 | minor | Fragments kept in fetcher URLs | D35 |
| D.c10 | minor | No successful HTTPS test through GuardedBackend | D17 |
| D.c11 | minor | Deadline-cleared test never runs the fetcher; deadline paths through the real transport untested | D19, D21 |
| D.g1 | critical | `store_body=False` disables the cache for robots.txt and redirect hops | D37 |
| D.g2 | major | Product token regex drops digits | D11 |
| D.g3 | major | `Location` missing from receipt headers | D13 |
| D.g4 | minor | 192.0.0.0/24 and 198.18/15 missing | D1 |
| D.g5 | minor | CR-only truncated robots.txt is emptied | D30 |
| D.g6 | minor | Missing tests: `store_body=False` with a 304 robots.txt, digit tokens, `Location` in receipts | D37, D11, D13 |

There are 48 raw findings: fast 5, standard 21, and deep 22. They merge into 37 distinct findings.

## Verification

Each distinct finding was verified once. "Repro" means a throwaway script in the session scratchpad, outside the repository, that drove the real fetcher code: `httpx.MockTransport`, the test fakes in `tests/fetch_support.py`, and no network access. The only resolver call that reached the system resolver used hostnames that fail IDNA encoding, which happens before any DNS query. The repository was not changed.

| Id | Finding | Verdict | Evidence |
|---|---|---|---|
| D1 | IPv4 special-purpose ranges allowed (198.18.0.0/15, 192.0.0.0/24, 192.88.99.0/24) | real | Repro: `refusal_reason` returns `None` for 198.18.0.1, 192.0.0.1, 192.0.0.192, and 192.88.99.1. SESSION-03b decision 4 leaves only the documentation ranges open on purpose. |
| D2 | Documentation ranges allowed, and tests treat them as public | wrong | SESSION-03b decision 4: "Documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) are not refused: they route nowhere and are what the tests use as public". 2001:db8::/32 is not named in that decision; the test treats it the same way, for the same reason. |
| D3 | IPv4 in other IPv6 translation forms not decoded (64:ff9b:1::/48, SIIT `::ffff:0:0:0/96`, Teredo) | real | Repro: `None` for 64:ff9b:1::a9fe:a9fe, ::ffff:0:a9fe:a9fe, ::ffff:0:7f00:1, and a Teredo address whose client is 10.0.0.1 (`ipaddress` decodes it). ADR-005 open gap 4 already records Teredo and "other IPv6 transition forms". |
| D4 | Other non-global IPv6 allowed (100::/64, and ::/8 outside ::/96 and the mapped range) | real | Repro: `None` for 100::1 and ::a:0:a9fe:a9fe. |
| D5 | Public cloud endpoints (Azure 168.63.129.16) not refused | real | Repro: `None`. ADR-005 open gap 2 already records this class ("public addresses that lead inward"). |
| D6 | DNS resolution is outside `total_timeout` | real | Repro: a resolver taking 500 s per lookup, with `total_timeout=60`, gave a receipt `NONE` after 1,001 s of fake time. `_screen` runs before `_exchange` sets the deadline. |
| D7 | Truncated gzip or deflate is recorded as a complete body with a hash | real | Repro: gzip cut 20 bytes short gave `NONE`, with a hash, for 291 of 1,600 decoded bytes. Deflate cut 6 bytes short gave 1,582 of 1,600. No test covers it: `test_fetch_client.py` has `test_a_corrupt_gzip_body_is_unreadable` (invalid bytes), but no truncated stream. |
| D8 | Multi-member gzip: later members silently dropped | real | Repro: a robots.txt of two gzip members (`User-agent: *`, then `Disallow: /secret`) let `/secret` be fetched (basis `RULES`, allowed). |
| D9 | Redirect cycles are not stopped on a repeated target | wrong | The docstring's "appears more than once" is about the `Location` header (`len(locations) != 1` in `_redirect_target`). Loops stopping at `max_redirects` is the design, tested by `test_redirect_limit_is_configurable_and_catches_loops`. |
| D10 | `User-agent: Cernis2` is taken as Cernis's group | wrong | The behavior is real (repro: the `Cernis2` group's `Allow: /` was applied), but it is as documented. The module defines the token as "the leading run of letters, `_`, and `-`", which is RFC 9309 section 2.2.1's character set for product tokens, so `Cernis2` is no crawler's token. The leading-run rule is what makes `user-agent: Cernis/1.0` match (tested). |
| D11 | Product token drops digits | wrong | RFC 9309 section 2.2.1: a product token contains only letters, underscores, and hyphens. Digits are not product-token characters. |
| D12 | Terminal redirect bodies are not read or hashed | wrong | No ADR or model rule asks for a redirect's body. `Receipt.body_sha256` is "the hash of the whole body or None", and the fetcher never reads redirect bodies by design. |
| D13 | `Location` missing from receipt headers | wrong | `RECORDED_HEADERS` (`src/cernis/model.py:113`) is content-type, etag, last-modified, retry-after, and x-robots-tag. The model rejects any other header name. |
| D14 | No IPv6 tests through GuardedBackend | real | Every real-transport test (`test_fetch_network.py`, `test_fetch_localhost.py`) uses an IPv4 address. |
| D15 | A hostname IDNA cannot encode (`a..b.example`, a 64-character label) crashes `fetch` with UnicodeError | real | Repro: `url_problem` returns `None` for both; `socket.getaddrinfo` raises `UnicodeEncodeError` (a `UnicodeError`, not an `OSError`); `Fetcher.fetch` with `system_resolve` raised it to the caller. |
| D16 | Parsed robots rules are kept for the whole run without bound | real | Repro: parsing a 5 MiB robots.txt of `Disallow: /a` lines retains 104.6 MB (peak 133.2 MB). `Fetcher._robots` is never evicted, and the links check's budget is per host, not a cap on the number of hosts. |
| D17 | No test of a successful pinned HTTPS connection verified against the hostname | real | `FakeStream.start_tls` always raises, and the only TLS test checks a failure. No test in the excluded files calls `start_tls` successfully. |
| D18 | `FakeStream.read` ignores its timeout, so the shrunken timeout is never checked | real | `tests/test_fetch_network.py`: `read` never looks at `timeout`. |
| D19 | The "deadline is cleared between requests" test never runs the fetcher | real | The test sets `RunNetwork.deadline` by hand and calls `bounded`. It never runs `_exchange`. |
| D20 | The DNS-rebinding test proves only one screen per hop | wrong | It also asserts `{address for address, _ in backend.connects} == {PUBLIC_ADDRESS}`: the backend under GuardedBackend was handed only the pinned address. `GuardedBackend.connect_tcp` makes no resolver call. |
| D21 | Deadline paths through the real transport are untested (connect over several pinned addresses, body trickle, TLS handshake) | real | The only real-transport deadline test trickles headers. The excluded `test_fetch_client.py` raises `httpx.ConnectTimeout` from a MockTransport, which bypasses GuardedBackend. |
| D22 | Unix-socket refusal untested | real | No test calls `connect_unix_socket`. |
| D23 | Integer and hex IPv4 host forms untested against the real resolver | real | `FakeResolver` resolves `2130706433` to the public address. `httpx.URL` keeps that host as is, so only the system resolver would reveal 127.0.0.1. The screen judges resolved addresses, so the gap is in the tests, not the screen. |
| D24 | The localhost pin test depends on the server closing the connection | real | `BaseHTTPRequestHandler` defaults to HTTP/1.0. On a keep-alive server, the second `_exchange` would reuse the pooled connection, never call `connect_tcp`, and the test's assertion would fail. |
| D25 | `GuardedTransport` says "system's default trust store", but httpx uses certifi | real | httpx 0.28 `_config.py`, `create_ssl_context`: `ssl.create_default_context(cafile=certifi.where())`. |
| D26 | `GuardedTransport.__init__` builds a parent pool and SSL context it then discards | real | `super().__init__(trust_env=False)` builds `_pool`, which is then replaced. The discarded pool holds no connections. |
| D27 | Ports are not restricted | real | Only addresses are screened. ADR-005 open gap 3 already records it. |
| D28 | A 4xx robots.txt in an unsupported coding makes the origin UNREACHABLE (disallowed), not UNAVAILABLE | real | Repro: robots.txt 404 with `Content-Encoding: br` gave `CONNECTION` with status 404, basis `UNREACHABLE`, and the page disallowed. RFC 9309 section 2.3.1.3 allows crawling on a 4xx. |
| D29 | Received bytes past the limit mark the body truncated, even when it decodes shorter | wrong | The behavior is real (repro: 123 bytes received, a 110-byte limit, 100 decoded, `body_truncated_at=110`), and it is the documented rule. ADR-003 amendment 1: "max_body_bytes bounds both the bytes received and the bytes after decoding. Either one passing the limit ends the read". The body was not read whole. |
| D30 | A truncated robots.txt with CR-only line endings is emptied, so everything is allowed | real | Repro: CR-separated `User-agent: *`, `Disallow: /`, then padding past a 100-byte limit: allowed, basis `RULES`. The same with LF: disallowed. |
| D31 | Pacing is keyed by the literal host, so `example.com.` skips the pause after `example.com` | real | Repro: `httpx.URL` keeps the trailing dot. A request to `example.com./robots.txt` right after `example.com/post` had no pacing sleep. |
| D32 | A non-ASCII cached ETag crashes the next conditional request | wrong | `cache._usable_validator` keeps only `[\x20-\x7e]+` values. Repro: a 200 with ETag bytes `"caf\xe9"`, then a second fetcher on the same cache: no `If-None-Match` was sent, and nothing was raised. |
| D33 | `total_timeout` restarts on every hop, retry, and robots.txt fetch, so one fetch can take about 3 x 11 x 60 s or more | real | `_exchange` sets a new deadline on each call. `FetchConfig` says "so a server that sends slowly cannot hold a run". The limits multiply as the finding says (`max_attempts` 3, `max_redirects` 10, `total_timeout` 60), and a new origin's robots.txt adds its own attempts. |
| D34 | The raw-deflate fallback is tried only when the first chunk fails | real | Repro: raw deflate in one chunk decoded (1,600 bytes). The same bytes split 1 + rest gave `CONNECTION`. |
| D35 | Fragments are kept in the requested URL, the final URL, the robots decision, and the cache key | real | Repro: `fetch(PAGE + "#a")` recorded `.../post#a`, and `#a` then `#b` made two paced requests for one resource. The docstring says URLs are recorded "in the normalized form httpx sends", and the fragment is not sent. The links check strips fragments before fetching; other callers were not checked. |
| D36 | An oversized final chunk skips the deadline check | real | Repro: a second chunk delivered 1,000 s after the start, over the limit, gave `NONE` with `body_truncated_at` set. The same chunk under the limit gave `TIMEOUT`. With the default transport, `DeadlineStream` bounds each read, so this needs a caller transport or data already buffered. |
| D37 | `store_body=False` bypasses the cache for every request in that call, robots.txt and redirect hops included | real (narrow) | Repro: after `fetch(PAGE, store_body=False)`, the cache directory was empty, and the next run's robots.txt request was unconditional. The docstring says the cache is skipped "for the URL". Not supported: the finding's critical consequence. With no cache entry no conditional request is sent, and an unconditional 304 robots.txt gives `UNREACHABLE` with or without `store_body=False` (repro). |

Totals: 37 distinct findings: 28 real, 9 wrong, 0 undetermined.

## Per tier

| Tier | Raw | Distinct | Real | Wrong | Undetermined | Wall time | Cost |
|---|---|---|---|---|---|---|---|
| fast | 5 | 5 | 3 | 2 | 0 | 574.9 s | |
| standard | 21 | 30 | 23 | 7 | 0 | 336.4 s | |
| deep | 22 | 22 | 17 | 5 | 0 | 398.1 s | |

Engine-parsed findings only (without standard's Claude voice and deep's Gemini voice): fast 5 raw, 5 distinct, 3 real, 2 wrong; standard 9 raw, 9 distinct, 5 real, 4 wrong; deep 16 raw, 19 distinct, 16 real, 3 wrong.

A tier's distinct count can exceed its raw count because bundled findings were split.

## Per voice

| Tier | Voice | Vendor | Raw | Distinct | Real | Wrong |
|---|---|---|---|---|---|---|
| fast | gpt-5.6-terra | OpenAI | 5 | 5 | 3 | 2 |
| fast | deepseek-v4.1-flash | DeepSeek | 0 (failed) | 0 | 0 | 0 |
| standard | gpt-6-sol | OpenAI | 4 | 5 | 4 | 1 |
| standard | gemini-3.8-flash-high | Google | 5 | 5 | 2 | 3 |
| standard | claude-sonnet-5-5 | Anthropic | 12 (not parsed by the engine) | 26 | 22 | 4 |
| deep | gpt-6-sol | OpenAI | 5 | 7 | 6 | 1 |
| deep | gemini-3.8-flash-high | Google | 6 (not parsed by the engine) | 5 | 3 | 2 |
| deep | claude-opus-5-5 | Anthropic | 11 | 17 | 15 | 2 |
| deep | deepseek-flash | DeepSeek | 0 (failed) | 0 | 0 | 0 |

## Overlap: real findings one tier found and the others did not

- **Fast only:** none.
- **Standard only:** 11 findings: D5, D14, D16, D18, D22, D23, D24, D26, D27, D28, and D31. All but D14 come from the unparsed Claude voice.
- **Deep only:** 5 findings: D33, D34, D35, D36, and D37.
- **Real findings all three tiers found:** D1, D6, and D7.

Engine-parsed only:

- **Fast only:** none.
- **Standard only:** D14.
- **Deep only:** 12 findings: D4, D8, D15, D17, D19, D21, D25, D30, D33, D34, D35, and D36.

## Claims

The deep panel's verified real findings are 17: D1, D3, D4, D6, D7, D8, D15, D17, D19, D21, D25, D30, D33, D34, D35, D36, and D37.

**T-1: falsified.** Standard found 12 of the 17: D1, D3, D4, D6, D7, D8, D15, D17, D19, D21, D25, and D30. 12 / 17 = 70.6%, below 80%. On engine-parsed findings only: deep has 16 real, standard found 4 of them (D1, D3, D6, D7), 4 / 16 = 25.0%. Falsified either way.

**T-2: falsified.** Fast found 3 of the 17 (D1, D6, D7). 3 / 17 = 17.6%, below 50%. Engine-parsed only: 3 / 16 = 18.8%. Falsified either way.

**T-3: held.** Deep found five real findings that neither fast nor standard found: D33, D34, D35, D36, and D37. Two are rated `major` or above:

- D33 (`total_timeout` restarts per hop): `major`, from claude-opus-5-5, which the engine parsed.
- D37: `critical`, from the unparsed Gemini voice. Its critical rating rests on a consequence that verification did not support (see D37).

D33 alone satisfies the claim. On engine-parsed findings only, the deep-only real findings rated `major` are D4, D8, D15, and D33, so the claim holds there too. If "high severity or above" were read as `critical` only, D37 would be the only candidate, and the claim would rest on a rating its own evidence does not support.

## The real findings, for the release session

Listed by distinct id. Severity is the highest the engine's voices gave. An entry marked "known" is already recorded as an open gap in ADR-005. Each entry's status comes from Session 5e (`docs/sessions/SESSION-05e.md`): 24 fixed, 4 deferred (D23, D26, D27, D33). Session 6a then fixed D33.

1. **D1 (critical): IPv4 special-purpose ranges are allowed.** **Status: Fixed (Session 5e).** `src/cernis/fetch/addresses.py`, `_REFUSED_V4`. 198.18.0.0/15 (benchmarking), 192.0.0.0/24 (IETF protocol assignments, including 192.0.0.192), and 192.88.99.0/24 pass the screen. Compare the list against the IANA IPv4 Special-Purpose Address Registry.
2. **D3 (critical; Teredo and "other transition forms" known, ADR-005 gap 4): IPv4 inside other IPv6 translation forms is not decoded.** **Status: Fixed (Session 5e); ADR-005 gap 4 closed for Teredo, and stays open for ISATAP and operator NAT64 prefixes.** `addresses.py`, `_embedded_ipv4`. The local-use NAT64 prefix 64:ff9b:1::/48 (RFC 8215), SIIT `::ffff:0:0:0/96`, and Teredo 2001::/32 (`ipaddress` exposes `.teredo`) carry IPv4 addresses that are never judged. Example: 64:ff9b:1::a9fe:a9fe embeds 169.254.169.254.
3. **D4 (major): other non-global IPv6 is allowed.** **Status: Fixed (Session 5e).** `addresses.py`, `_REFUSED_V6`. 100::/64 (discard-only), and addresses in ::/8 outside ::/96 and the mapped range, pass the screen.
4. **D5 (major; known, ADR-005 gap 2): public cloud endpoints are not refused.** **Status: Fixed (Session 5e): `168.63.129.16` is refused; ADR-005 gap 2 stays open for the general class.** `addresses.py`. Azure's 168.63.129.16 is a public address that reaches the host platform from inside Azure.
5. **D6 (major): DNS resolution is outside `total_timeout`.** **Status: Fixed (Session 5e): resolving is bounded by `connect_timeout`.** `src/cernis/fetch/client.py`, `_screen`; `src/cernis/fetch/network.py`, `system_resolve`. `getaddrinfo` blocks with no bound, before the deadline is set. Each new origin is resolved twice (the page, then robots.txt).
6. **D7 (major): a truncated gzip or deflate body is recorded as complete.** **Status: Fixed (Session 5e).** `client.py`, `_BodyDecoder.feed` and `_read_response`. After the read loop, nothing checks the inflater's `eof`, so a prefix gets `NONE`, a hash, and possibly a cache entry. For robots.txt, rules after the cut are lost. There is no test for a truncated compressed stream.
7. **D8 (major): later gzip members are silently dropped.** **Status: Fixed (Session 5e).** `_BodyDecoder`. `zlib.decompressobj` stops at the first member, and `unused_data` is never read. A two-member robots.txt loses its second member's rules.
8. **D14 (minor): no IPv6 tests through GuardedBackend.** **Status: Fixed (Session 5e), test only.** `tests/test_fetch_network.py`, `tests/test_fetch_localhost.py`.
9. **D15 (major): a hostname IDNA cannot encode crashes the fetch.** **Status: Fixed (Session 5e).** `client.py`, `_screen` (`except OSError`). `socket.getaddrinfo` raises `UnicodeError` for an empty label or one over 63 characters. `url_problem` and `_redirect_target` accept such hosts, so a link or a `Location` from untrusted content raises out of `Fetcher.fetch`.
10. **D16 (major): robots rules are kept for the run without bound.** **Status: Fixed (Session 5e): the first 500 KiB are parsed.** `client.py`, `Fetcher._robots`; `src/cernis/fetch/rfc9309.py`, `RobotsRules`. A 5 MiB robots.txt retains about 105 MB, once per origin, with no cap on rules, `Sitemap:` lines, or origins. RFC 9309 section 2.5 lets a parser stop after 500 KiB.
11. **D17 (major): no test of a successful pinned HTTPS connection verified against the hostname.** **Status: Fixed (Session 5e), test only.** `tests/test_fetch_network.py` (`FakeStream.start_tls` always raises), `tests/test_fetch_localhost.py`.
12. **D18 (major): the fake stream ignores the timeout it is given.** **Status: Fixed (Session 5e), test only.** `tests/test_fetch_network.py`, `FakeStream.read`. `min(timeout, remaining)` is never checked.
13. **D19 (major): the "deadline is cleared between requests" test never runs the fetcher.** **Status: Fixed (Session 5e), test only.** `tests/test_fetch_network.py`, `test_the_deadline_is_cleared_between_requests`. The `finally` reset in `_exchange` is untested.
14. **D21 (major): deadline paths through the real transport are untested.** **Status: Fixed (Session 5e), test only.** A connect over several pinned addresses, a trickled body, and the TLS handshake are not tested.
15. **D22 (major): the Unix-socket refusal is untested.** **Status: Fixed (Session 5e), test only.** `GuardedBackend.connect_unix_socket`.
16. **D23 (major): integer and hex IPv4 host forms are untested against the real resolver.** **Status: Deferred (Session 5e): the test needs the system resolver, which the test network guard refuses for any non-local name; the screen judges whatever the resolver returns, so the risk is the platform resolver's, not Cernis's.** `FakeResolver` resolves `2130706433` to the public address.
17. **D24 (major): the localhost pin test depends on the server closing the connection.** **Status: Fixed (Session 5e), test only.** `test_the_real_transport_connects_only_to_screened_hosts` relies on `BaseHTTPRequestHandler`'s HTTP/1.0 default.
18. **D25 (minor): the trust-store docstring is wrong.** **Status: Fixed (Session 5e), docstring.** `network.py`, `GuardedTransport`. httpx 0.28 loads certifi's bundle (`ssl.create_default_context(cafile=certifi.where())`), not the system store.
19. **D26 (minor): an unused pool and SSL context are built.** **Status: Deferred (Session 5e): the discarded pool holds no connections, and not building it would mean bypassing `HTTPTransport.__init__`, more private coupling to httpx than the cost it removes.** `network.py`, `GuardedTransport.__init__`. `super().__init__` builds `_pool`, which is then replaced.
20. **D27 (minor; known, ADR-005 gap 3): ports are not restricted.** **Status: Deferred (Session 5e): ADR-005 gap 3 kept open; amendment 1 says why.** `client.py`, `_screen` and `url_problem`.
21. **D28 (minor): a 4xx robots.txt in an unsupported coding disallows the origin.** **Status: Fixed (Session 5e).** `client.py`, `_read_response` (`_BodyDecoder` is built for every non-redirect, non-304 response); `src/cernis/fetch/robots.py`, `RobotsPolicy`. A 404 with `Content-Encoding: br` becomes `CONNECTION`, so the basis is `UNREACHABLE`, not `UNAVAILABLE` (RFC 9309 section 2.3.1.3).
22. **D30 (minor): a truncated robots.txt with no LF is emptied, and everything is allowed.** **Status: Fixed (Session 5e).** `robots.py`, `RobotsPolicy.__init__`, `rules[: rules.rfind(b"\n") + 1]`. The matcher treats CR as a line end. A file with no LF before the cut gives `b""`, so it fails open while the basis says `RULES`.
23. **D31 (minor): pacing is keyed by the literal host.** **Status: Fixed (Session 5e).** `client.py`, `_exchange`. `example.com.` and `example.com` are paced (and given robots.txt) separately.
24. **D33 (major): the deadline is per request, not per fetch.** **Status: Deferred (Session 5e): the overclaiming docstring is corrected, but a budget for a whole fetch is a design decision. A robots.txt fetch cut short by such a budget would count as unreachable and disallow its origin for the rest of the run. Fixed in Session 6a: `fetch_timeout` (120 s) bounds the whole fetch, and robots.txt has its own budget (ADR-005 amendment 2).** `client.py`, `_exchange`, `_attempt`, and `_attempts`; the `FetchConfig` docstring ("cannot hold a run"). One fetch can run for `max_attempts x (max_redirects + 1) x total_timeout`, about 33 minutes at the defaults, plus robots.txt fetches for each new origin.
25. **D34 (minor): the raw-deflate fallback is tried only on the first chunk.** **Status: Fixed (Session 5e).** `_BodyDecoder.feed`. A first chunk too short to fail (1 byte) sends a later failure to `CONNECTION`.
26. **D35 (minor): fragments are kept in fetcher URLs.** **Status: Fixed (Session 5e).** `client.py`, `fetch` and `_redirect_target`. The requested URL, final URL, robots decision, and cache key keep `#...`, so URLs differing only by fragment are fetched and recorded separately. The links check strips fragments; other callers were not checked.
27. **D36 (minor): an oversized final chunk skips the deadline check.** **Status: Fixed (Session 5e).** `client.py`, `_read_response`. The loop breaks on the limit before `_check_deadline`. With the default transport, each read is bounded, so this needs a caller transport or already-buffered data.
28. **D37 (minor on verification; rated critical): `store_body=False` bypasses the cache for every request in the call.** **Status: Fixed (Session 5e), the verified part: robots.txt uses the cache again during a `store_body=False` fetch. The resource and its redirect targets still skip the cache.** `client.py`, `_exchange` and `_read_response` (`self._no_store_url is None`). robots.txt and redirect hops are neither read from nor written to the cache, while the docstring says "for the URL". The finding's claim that this makes robots.txt `UNREACHABLE` through a 304 did not hold in verification.

## Follow-up: same model across tiers, and per-voice timing

Added on 2026-11-02 at the author's follow-up request, from the records above. No new audit was run, and nothing was re-verified; the matching rules and verdicts are the ones above.

### Same model, same artifact

The request named gemini-3.8-flash-high as appearing in all three tiers. The records show otherwise. In fast, the `google` role ran DeepSeek's deepseek-v4.1-flash as a model fallback, and that voice failed with no output. gemini-3.8-flash-high ran in standard and deep only. gpt-6-sol also ran in standard and deep only. No model ran in all three tiers.

| Model | Standard (distinct) | Deep (distinct) | Shared by both runs | Unique to one run | Recur (shared / all distinct) | Shared: real / wrong | Unique: real / wrong |
|---|---|---|---|---|---|---|---|
| gemini-3.8-flash-high (Google) | D3, D11, D12, D13, D14 | D1, D11, D13, D30, D37 | D11, D13 | standard: D3, D12, D14; deep: D1, D30, D37 | 2 / 8 = 25.0% | 0 / 2 | 5 / 1 |
| gpt-6-sol (OpenAI) | D1, D3, D6, D7, D10 | D1, D2, D6, D7, D8, D17, D36 | D1, D6, D7 | standard: D3, D10; deep: D2, D8, D17, D36 | 3 / 9 = 33.3% | 3 / 0 | 4 / 2 |

Notes from the records:

- gemini-3.8-flash-high's two shared findings (the product-token digits, and `Location` in receipts) are both wrong. Its standard run was parsed by the engine; its deep run was not.
- gpt-6-sol's shared address-range finding (D1) names 198.18.0.0/15 in both runs. Each run names a different second range: 64:ff9b:1::/48 in standard (D3), and 2001:db8::/32 in deep (D2).

**Role and instructions.** In both its runs, each model had the same engine role and the same recorded reasoning setting. The profile member ids differ, since each tier's profile has its own members.

| Model | Standard | Deep |
|---|---|---|
| gemini-3.8-flash-high | role `google`, reasoning `""`, member `apm_nCDdwLrjIk` | role `google`, reasoning `""`, member `apm_TaE1VpJrgu` |
| gpt-6-sol | role `openai`, reasoning `""`, member `apm_FnV4iDRQXE` | role `openai`, reasoning `""`, member `apm_eSTjV5FuNX` |

The submissions were identical apart from `audit_mode` and `client_request_id`. The audit records do not contain the prompt or instructions the engine gave each voice, so whether the engine's own per-voice instructions differed between tiers cannot be determined from them.

### Per-voice timing

From each voice's `started_at` and `completed_at` in the records (UTC). The records also carry an `elapsed_s` per voice. It matches the timestamps for every voice except the two DeepSeek voices, both of which used a model fallback and failed. Both figures are given, without explanation, since the records give none.

| Tier | Voice | Status | Start | End | End minus start | `elapsed_s` |
|---|---|---|---|---|---|---|
| fast | gpt-5.6-terra (OpenAI) | completed | 21:37:26 | 21:42:47 | 320.4 s | 320.3 s |
| fast | deepseek-v4.1-flash (DeepSeek, in the `google` role) | failed | 21:37:26 | 21:47:01 | 574.9 s | 381.9 s |
| standard | gpt-6-sol (OpenAI) | completed | 21:41:44 | 21:43:37 | 113.7 s | 113.6 s |
| standard | gemini-3.8-flash-high (Google) | completed | 21:41:44 | 21:44:50 | 186.3 s | 186.3 s |
| standard | claude-sonnet-5-5 (Anthropic) | completed | 21:41:44 | 21:47:20 | 336.4 s | 336.3 s |
| deep | gpt-6-sol (OpenAI) | completed | 21:46:02 | 21:48:08 | 125.8 s | 125.7 s |
| deep | gemini-3.8-flash-high (Google) | completed | 21:46:02 | 21:49:10 | 187.9 s | 187.8 s |
| deep | claude-opus-5-5 (Anthropic) | completed | 21:46:02 | 21:52:40 | 398.1 s | 398.1 s |
| deep | deepseek-flash (DeepSeek) | failed | 21:46:02 | 21:51:41 | 338.8 s | 10.7 s |

The voice that finished last in each audit:

- **Fast:** deepseek-v4.1-flash, which failed, at 574.9 s. The only voice that produced findings finished at 320.4 s.
- **Standard:** claude-sonnet-5-5, at 336.4 s.
- **Deep:** claude-opus-5-5, at 398.1 s.
