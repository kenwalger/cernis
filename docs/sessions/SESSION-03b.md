# Session 3b: fetcher hardening before Phase 4

**Date:** 2026-10-29
**Phase:** 2 (DESIGN.md draft 2.2, section 6)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

Closes the three Owner decisions from Session 3 (A15, A16, A17, all decided in DESIGN.md draft 2.2) and its deferred whole-request deadline. No real network requests: MockTransport, a fake httpcore network, and a server on 127.0.0.1 only. No Decision Engine audit, as the session prompt required.

## Built

- **The address screen (A15, ADR-005).** `src/cernis/fetch/addresses.py` lists the refused ranges explicitly: loopback, RFC 1918, link-local (including `169.254.169.254`), carrier-grade NAT, unspecified, broadcast, multicast, and reserved; for IPv6, `::1`, `::`, `fc00::/7`, `fe80::/10`, `fec0::/10`, and `ff00::/8`; and IPv4-mapped, IPv4-compatible, NAT64, and 6to4 addresses by the IPv4 address inside them. Before every hop, the requested URL, each redirect target, and each robots.txt fetch (retries included), `Fetcher._screen` resolves the host and screens every address. Any refused address refuses the hop before anything is sent, robots.txt included. The receipt is `ADDRESS_REFUSED`, a new `ErrorKind`, and `FetchResult.refusals` gives the reason (`example.com resolves to 169.254.169.254 is link-local, including cloud metadata (169.254.0.0/16)`), which `cernis fetch` prints. `FetchConfig(allow_loopback=True)` and `--allow-loopback` allow loopback only.
- **Pinned connections.** `src/cernis/fetch/network.py`: the screened addresses are pinned per host, and `GuardedBackend`, an httpcore network backend under httpx's transport, connects only to them and never resolves a name. TLS is still verified against the hostname. A host with no pins is refused inside the transport.
- **The overall request deadline.** The same backend wraps every stream: each read, write, connect, and TLS handshake gets the smaller of its own timeout and the time left before `total_timeout`. Headers trickled a byte at a time can no longer hold a request open. The fetcher's own checks, after the headers arrive and after each body chunk, stay in place for injected transports.
- **Cernis's own RFC 9309 matcher (A16).** `src/cernis/fetch/rfc9309.py`, `MATCHER_VERSION = "1"`, replaces `urllib.robotparser`. It selects groups by the whole product token, case-insensitively, never by substring, and combines groups for the same agent (and `*` groups). Matching takes the longest pattern in octets, with Allow winning ties. `*` and a final `$` are special, `%2A` and `%24` are literal, and pattern and path are percent-encoding normalized the same way. Rules are matched against the request target exactly as httpx sends it, and `/robots.txt` is always allowed. It uses no regular expressions, so a pattern full of `*` cannot backtrack. `RobotsDecision` now records the deciding rule as written (`Disallow: /private/`) and the matcher version, and `cernis fetch` shows both.
- **429 on robots.txt (A17, ADR-006).** Unchanged behavior, now an ADR: a robots.txt still answering 429 after retries disallows everything, a deliberate departure from RFC 9309 for politeness. `test_a_429_robots_txt_disallows_everything` locks it.
- **Dependencies.** httpcore is declared (`>=1.0.9,<2`), since `network.py` imports it. httpx is held to `>=0.28.1,<0.29`, because `GuardedTransport` replaces its `_pool` attribute (no public way to pass a network backend exists in 0.28).
- **Tests.** `test_fetch_addresses.py` covers every range, its edges, the opt-in, and unparseable input. `test_fetch_ssrf.py` covers refusal on the first hop, on a redirect, among several addresses, and on a robots.txt redirect; the order of screens; re-screening on retry; DNS failure; and the opt-in. `test_fetch_network.py` runs httpx, httpcore, and h11 over a fake network with no sockets, checking pinned connections, rebinding, failover across addresses, the deadline against one header byte per second, and a slow response that still finishes in time. `test_fetch_rfc9309.py` has 76 matcher tests, including cases built from RFC 9309's examples (section 5.1's simple example for each crawler, 5.2's longest match, the special-character and percent-encoding tables of 2.2.2 and 2.2.3, and 2.2.1's group combining). The localhost tests now need `allow_loopback`, and two more run on a real socket: loopback refused without the opt-in (the server sees no request), and an unscreened host refused inside the real transport. `tests/fetch_support.py` gains `FakeResolver`, so no test reaches DNS; the network guard caught the first test that tried.

## Decisions

1. **A refusal is its own `ErrorKind`.** `ADDRESS_REFUSED` instead of `CONNECTION`, because nothing was sent: a refusal is Cernis's choice, not the server's failure, and Phase 3 must be able to tell them apart. It is a sixth value beyond DESIGN.md's receipt sketch, recorded in ADR-005.
2. **The screen comes before robots.txt.** A refused host's robots.txt is never fetched, so a refusal is never mistaken for "disallowed by robots".
3. **One refused address refuses the host.** A resolver that returns a public and a private address could otherwise get the private one used.
4. **Ranges are explicit, not `ipaddress.is_private` or `is_global`.** Their answers changed between Python versions, which is the problem the matcher fixes for robots.txt; the address screen must not repeat it. Documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) are not refused: they route nowhere and are what the tests use as "public".
5. **A rule that is not a path pattern is ignored.** RFC 9309's grammar requires a pattern to start with `/`; `*` is accepted too, as the RFC's own example uses `*.gif$`. `Disallow: private` is ignored, not read as `/private`.
6. **The deadline lives in the network backend.** A watchdog thread closing sockets would work on any transport but turns a timeout into a connection error and adds a thread. Bounding each socket operation by the time left keeps the error a timeout and needs no thread.

## Supersedes

- **SESSION-03.md decision 4** stands, now recorded as ADR-006 (Owner decision A17).
- **SESSION-03.md decision 5**: `urllib.robotparser` is gone; robots decisions are the same on Python 3.12, 3.13, and 3.14 (A16). The version-conditional xfails are removed.
- **SESSION-03.md A15**: decided and built (ADR-005).
- **SESSION-03.md A13 and its deferred whole-request deadline**: built, for the default transport.

## Checks

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH`: ruff check, ruff format check, mypy strict (35 files), pydoclint, pytest (610 passed), and the isolated Python 3.12 pytest (610 passed). The suite also gives the same 610 passes on Python 3.13 (`uv run --isolated --python 3.13 pytest`); there are no xfails on any version.

The deadline test was checked against a mutation: with `RunNetwork.bounded` returning the plain timeout, `test_trickled_headers_cannot_hold_a_request_past_its_deadline` fails.

## For the pre-0.1.0 release audit

One `deep` Decision Engine audit should cover, before 0.1.0 is tagged:

1. **The address screen and its gaps** (ADR-005): the range lists against current IANA special-purpose registries, the embedded-IPv4 decoding, the decision to leave documentation ranges open, and the six remaining gaps the ADR names (caller-supplied transports, public addresses that lead inward, ports, Teredo and other transition forms, proxies, and the private `_pool` replacement).
2. **Pinning and the network backend** (`network.py`): that every connection httpcore opens goes through `GuardedBackend.connect_tcp`, that keep-alive reuse cannot carry a connection to an unscreened address, that TLS verification still uses the hostname, and that the `_pool` replacement keeps httpx's TLS defaults.
3. **The deadline**: whether any httpcore operation escapes the wrapped stream (connection-pool waits, HTTP/2 if ever enabled), and the interaction with `read_timeout`, `connect_timeout`, and pacing.
4. **The RFC 9309 matcher** against the RFC's full text, not only its examples: group boundaries, product-token extraction, percent-encoding normalization (including invalid sequences and non-UTF-8 bodies), the octet-length rule for patterns with `*` and `$`, and the decision to ignore non-path patterns.
5. **The receipt model as it now stands** (ADR-003, ADR-004, ADR-005): every `ErrorKind`'s invariants, the 304 hash link, and `final_url`'s meaning, since Phase 3 and the Phase 5 store depend on them.
6. **The Session 3 audit fixes that were never re-audited** under the one-audit rule: bounded gzip and deflate decoding, the cache's bounded reads and trust model, robots.txt redirects restricted to `/robots.txt`, and URL normalization before the robots check.
7. **Release machinery** (Session 2c) is unchanged and was audited; it needs no new review unless `publish.yml` changes.

## Deferred

- **DESIGN.md's Stack list** still names `urllib.robotparser` (section 6, "Stack"), while section 6's polite-fetching list says Cernis's own matcher. Left for the Owner, since DESIGN.md is the Owner's document.
- **Phase 3's mapping** of `ADDRESS_REFUSED` to a `NOT_DETERMINABLE` reason code.
- Still open from Session 3: cache eviction, CLI flags for timeouts and the body limit, `Vary`, and crawl-delay.

## Not touched

- `docs/SDK-FRICTION.md`: no Sovereign Systems SDK code was used.
- The release workflows and `docs/RELEASING.md`.
