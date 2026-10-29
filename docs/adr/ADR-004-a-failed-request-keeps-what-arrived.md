# ADR-004: A failed request keeps what arrived and names the URL that failed

**Status:** Accepted
**Date:** 2026-10-29

## Context

Session 1b defined the receipt's `error_kind` so that any value other than `NONE` meant "no response": `status_code`, `final_url`, and `body_sha256` all `None`. Session 3's fetcher showed two ways that rule makes a receipt misstate what Cernis observed (Decision Engine audit `aud_K8j95M7gmH`, findings A2 and A3 in SESSION-03.md):

1. A status line and headers can arrive and the body then fail: a read timeout, a reset connection, a total-timeout, or a body that does not decode. The old rule forced the receipt to say no response arrived, and dropped the status and headers Cernis had seen. A slow `200` looked the same as an unreachable host.
2. After one or more redirects, the next request can fail before any response. With `final_url` forced to `None`, the receipt showed only the chain of URLs that redirected, so the URL that actually failed appeared nowhere.

Principle 6 says findings are receipts of exactly what Cernis saw. Both cases lose an observation.

## Decision

- `error_kind` says how the attempt ended. `NONE` is a whole response, as before.
- For `TIMEOUT`, `CONNECTION`, and `TLS`, `final_url` is required and names the URL whose request failed. When the status line and headers arrived before the failure, `status_code` and `headers` keep them; otherwise `status_code` is `None` and there are no headers.
- `body_sha256` and `body_truncated_at` are only for `NONE`. A body that failed partway has no hash.
- `headers` require a `status_code`.
- `TOO_MANY_REDIRECTS` is unchanged: no `status_code`, no `final_url`, no hash, and a `redirect_chain` holding every URL that redirected, so the last redirect is on the chain.
- `redirect_chain` lists the URLs whose redirects were followed. A redirect that was not followed (an unusable `Location`, or a target robots.txt disallows) is the final response: its URL is `final_url` and its 3xx is `status_code`.

## Consequences

- `final_url` is set on every receipt except `TOO_MANY_REDIRECTS`. It now means "the URL of the last request in the attempt", which is wider than the DESIGN.md section 3 sketch ("None if no response"). This ADR records the change; DESIGN.md is not rewritten.
- Phase 3 can tell a slow or broken body (`TIMEOUT` or `CONNECTION` with a status) from a host that never answered (no status), and both are `FETCH_FAILED`. A `CONNECTION` with a status also covers a body in a coding Cernis did not offer or that does not decode.
- Code that assumed "error means no status" must check `status_code` instead. No stored receipts exist yet (Phase 5), so nothing needs migrating.
