# ADR-005: Non-public addresses are refused, on every hop

**Status:** Accepted
**Date:** 2026-10-29

## Context

A page Cernis audits, or any redirect along the way, can point it at an address that is not on the public internet: this machine (`127.0.0.1`), a private network (`10.0.0.0/8`), or a cloud metadata service (`169.254.169.254`). Cernis would then fetch it, record its status, headers, and hash, cache its body, and print all of it. Where Cernis runs in CI or on a cloud host, that turns it into a probe of the internal network (server-side request forgery). Phase 4 makes this much easier to reach, because `epi.links.resolve` fetches links taken from page bodies. The Decision Engine audit of Session 3 raised it (finding A15), and DESIGN.md draft 2.2 section 6 decides it: refuse non-public addresses by default, on every hop, with an opt-in for localhost.

## Decision

- **What is refused** (`src/cernis/fetch/addresses.py`), from explicit ranges rather than `ipaddress`'s `is_private` and `is_global`, whose answers have changed between Python versions:
  - IPv4: unspecified `0.0.0.0/8`, private `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, carrier-grade NAT `100.64.0.0/10`, loopback `127.0.0.0/8`, link-local `169.254.0.0/16` (cloud metadata), multicast `224.0.0.0/4`, reserved `240.0.0.0/4`, and broadcast `255.255.255.255`.
  - IPv6: unspecified `::`, loopback `::1`, unique local `fc00::/7`, link-local `fe80::/10`, site-local `fec0::/10`, and multicast `ff00::/8`.
  - An IPv6 address that carries an IPv4 address (IPv4-mapped `::ffff:0:0/96`, IPv4-compatible `::/96`, NAT64 `64:ff9b::/96`, 6to4 `2002::/16`) is judged by the IPv4 address inside it.
  - Anything that is not an IP address is refused.
- **When.** Before every hop: the requested URL, each redirect target, and each robots.txt fetch, including a retry, the fetcher resolves the host and screens every address it resolves to. One refused address refuses the hop, so a resolver cannot slip a private address in after a public one. The screen comes before the robots.txt check, so a refused host's robots.txt is not fetched either.
- **What a refusal records.** A receipt with a new `error_kind`, `ADDRESS_REFUSED`: `final_url` is the refused URL, with no status, headers, or hash, and the hops before it on `redirect_chain`. `FetchResult.refusals` carries the reason, naming the host, the address, and its range, for example `example.com resolves to 169.254.169.254 is link-local, including cloud metadata (169.254.0.0/16)`. `cernis fetch` prints it. A host that does not resolve is `CONNECTION`, not a refusal.
- **The opt-in.** `FetchConfig(allow_loopback=True)` and `cernis fetch --allow-loopback` allow loopback (`127.0.0.0/8`, `::1`, and their IPv4-mapped forms) and nothing else.
- **Connecting.** With the default transport, the screened addresses are pinned, and Cernis's network backend (`src/cernis/fetch/network.py`) connects only to them, never resolving the name again. TLS is still verified against the hostname. A host with no pins is refused inside the transport, so a code path that forgot to screen fails closed.

`ErrorKind` gains `ADDRESS_REFUSED`. It is a sixth value beyond the five in the DESIGN.md section 3 receipt sketch; this ADR records it. ADR-004's rules for failed requests apply, except that a refused receipt never has a status, since nothing was sent.

## The gap between resolving and connecting (DNS rebinding)

A screen that resolves a name, checks the answer, and then lets the HTTP library resolve the name again can be beaten by a DNS server that answers with a public address the first time and a private one the second. **For the default transport this session closes that gap:** the addresses screened are the addresses connected to, because the backend dials the pinned IP addresses and does no lookup of its own. `tests/test_fetch_network.py` drives this through httpx and httpcore over a fake network, with a resolver that rebinds after the screen's lookups; every connection goes to the screened address.

What remains open:

1. **A transport passed in by the caller.** `Fetcher(transport=...)` (the tests' `httpx.MockTransport`, or a library user's own transport) gets the screen but not the pinning. Such a transport resolves on its own, so the rebinding window is open there.
2. **Public addresses that lead inward.** An address in a public range that routes to internal services (a NAT hairpin, a public load balancer in front of private ones) passes the screen. Cernis cannot see that from the address.
3. **Ports.** Only addresses are screened. A redirect to a public host on any port (`:22`, `:6379`) is followed, though only with an HTTP GET.
4. **Other IPv6 transition forms.** Teredo (`2001::/32`) and other mappings that obscure an IPv4 address are not decoded, so an internal IPv4 address hidden that way is not recognized.
5. **Proxies.** None are used (`trust_env=False`). If a proxy is ever added, the screen must apply to it as well as to the target.
6. **A private httpx detail.** httpx 0.28 has no public way to give its transport a network backend, so `GuardedTransport` replaces the transport's `_pool` attribute. `pyproject.toml` holds httpx below 0.29. `test_the_real_transport_connects_only_to_screened_hosts` fails if the replacement stops taking effect.

## Consequences

- Cernis cannot be pointed at internal services by the pages it audits, by default, on any supported Python.
- Testing against a local server needs `--allow-loopback`; the localhost tests set it.
- Every hop costs one DNS lookup before it is sent (two per new origin, counting robots.txt). The connection reuses the answer.
- Phase 3 must report an `ADDRESS_REFUSED` receipt as `NOT_DETERMINABLE`, with the receipt as evidence of the attempt; which reason code it uses is a Phase 3 decision.
