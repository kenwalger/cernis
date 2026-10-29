# ADR-006: A 429 robots.txt disallows everything

**Status:** Accepted
**Date:** 2026-10-29

## Context

RFC 9309 section 2.3.1.3 says that when robots.txt answers with a status in the 400 to 499 range, it is "unavailable", and a crawler may access any resource on the server. `429 Too Many Requests` is in that range. Section 2.3.1.4 says that when robots.txt is unreachable because of server or network errors (5xx, timeouts), the crawler must assume complete disallow.

Read literally, a server that answers Cernis's robots.txt request with 429, meaning "you are sending too many requests, slow down", has thereby permitted Cernis to fetch everything. Session 3 treated 429 as unreachable instead (decision 4). The Decision Engine audit flagged the departure (finding A17), and the Owner decided in DESIGN.md draft 2.2 to keep it and record why.

## Decision

A robots.txt that still answers `429` after the fetcher's retries (up to three attempts, honoring `Retry-After`) is treated as **unreachable**: `RobotsBasis.UNREACHABLE`, and every URL on that origin is disallowed for the rest of the run. Every other 4xx stays "unavailable", allowing everything, as RFC 9309 says.

This is a deliberate departure from RFC 9309, in favor of politeness:

- A 429 is the server asking Cernis to back off. Responding by fetching pages is the opposite of what it asked.
- A 429 says nothing about whether crawling is welcome. The RFC's 4xx rule exists for a robots.txt that does not exist (404) or is not served to anyone (401, 403), which is a statement about the file. A 429 is a statement about the client's rate.
- RATE_LIMITED is temporary by nature (DESIGN.md section 3). A later run, with the server no longer rate limiting, gets the real robots.txt and the real answer, so the cost of being conservative is one run's worth of findings, recorded as such.
- Large crawlers take the same view: Google documents treating a 429 robots.txt like a server error.

## Consequences

- When a site rate limits its robots.txt, Cernis audits nothing on that origin in that run. The robots.txt receipts (one per attempt, each with its `Retry-After`) show why.
- Phase 3 reports pages on that origin as not fetched because robots.txt was unreachable. It must not report a robots.txt *rule* as the reason, since none was read.
- `src/cernis/fetch/robots.py` keeps the `status != 429` condition, and `test_an_unreachable_robots_txt_disallows_everything` keeps the 429 case. Changing either changes this decision and needs a dated amendment here.
