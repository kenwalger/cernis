# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

Everything since 0.0.1. Sessions are recorded in `docs/sessions/`; the
pre-release review list is `docs/RELEASE-AUDIT.md`.

### Added

- CI (`.github/workflows/ci.yml`): the full check list on Python 3.12, 3.13,
  and 3.14 for every push and pull request.
- Trusted Publishing to PyPI (`.github/workflows/publish.yml`), bound to the
  release tag, with the wheel checked before upload; `docs/RELEASING.md`.
- The brand: `BRAND.md`, the mark in light and dark variants, favicons, and
  the README logo.
- The finding and receipt model (`cernis.model`): `Status`, `Actor`,
  `ReasonCode`, and `Family` enums, and frozen `Evidence`, `Finding`, and
  `Receipt` dataclasses that enforce the status rules at construction
  (ADR-001).
- The no-promise checker (`cernis.promises`) and a test that fails if any
  recommendation template contains outcome language.
- The check registry (`cernis.checks.registry`) listing every planned check at
  version 1, none implemented yet.
- `cernis checks [--format table|json]`.
- DESIGN.md draft 2 model changes: `would_require` on NOT_DETERMINABLE
  findings with no possible attempt, and required evidence for the rest;
  `ReasonCode.RATE_LIMITED`; `ErrorKind` and `Receipt.error_kind`, with
  `retry-after` in the recorded headers; `Finding.target` and the derived
  cross-run `Finding.key`; `Snapshot`; `ChangeClass`.
- The fetcher (`cernis.fetch`, DESIGN.md Phase 2): robots.txt for Cernis's own
  user agent (RFC 9309 status rules), per-host pacing, manual redirects with
  every hop recorded, retries for 429 and 503 honoring `Retry-After`, a body
  size limit, timeouts, and a conditional-request cache in `.cernis-cache/`.
  Each attempt produces a receipt.
- `Receipt.body_truncated_at`: the limit at which an oversized body was cut
  off, which then has no `body_sha256` (ADR-003).
- A `TIMEOUT`, `CONNECTION`, or `TLS` receipt names the URL that failed in
  `final_url`, and keeps the status and headers when they arrived before the
  body failed (ADR-004).
- `cernis fetch <url> [--format text|json] [--cache-dir PATH]`.
- httpx is the first runtime dependency.
- An address screen (ADR-005): before every hop, Cernis refuses hosts that
  resolve to loopback, private, link-local (cloud metadata), carrier-grade
  NAT, or other non-public addresses, and connects only to the addresses it
  screened. A refusal is an `ADDRESS_REFUSED` receipt with a reason.
  `cernis fetch --allow-loopback` allows loopback only, for testing.
- Cernis's own RFC 9309 matcher (`cernis.fetch.rfc9309`, version 1)
  replaces `urllib.robotparser`: group selection by product token, longest
  match, Allow winning ties, `*` and `$`, and percent-encoding
  normalization, the same on every supported Python. Robots decisions record
  the deciding rule and the matcher version.
- An overall deadline per request (`total_timeout`), headers included.
- A 429 robots.txt disallows everything, a deliberate departure from
  RFC 9309 (ADR-006).
- httpcore is a declared dependency, and httpx is held below 0.29.
- The parser (`cernis.parse`, Phase 3 part one), on selectolax: `parse_page`
  reads titles, `html lang`, every canonical, every `meta` (including
  `og:*`), every JSON-LD block (raw text and parse result), and body links,
  and never raises on malformed HTML; article-body extractors `dev.article`,
  `wordpress.entry`, and `generic`, each versioned; and `build_snapshot`,
  with documented normalization and volatile-token handling.
- `cernis.urls`: the one URL normalization (`normalize_url`,
  `normalize_percent_encoding`, also used by the robots matcher) and
  `compare_urls` (IDENTICAL, EQUIVALENT with the reason, or DIFFERENT).
- Finding keys are final: NFC on every string, and URL targets normalized.
- `ReasonCode.ADDRESS_REFUSED`.
- selectolax and idna are declared dependencies.
- The nine peritext checks (`cernis.checks.peritext`), exactly per DESIGN.md
  section 4, with recommendations for author-actionable defects from six new
  templates.
- Fetch outcomes as `NOT_DETERMINABLE` findings (`cernis.checks.outcomes`):
  robots.txt, refused addresses, rate limiting, access denied, failed and
  truncated fetches; no check runs against a page not seen whole.
- `Run`, validated as a whole at construction, and `cernis.audit.audit`.
- Reports: JSON (`cernis-report`, format version 1) and Markdown.
- `cernis audit <url> ... [--site-type dev|wordpress] [--format md|json]
  [--output FILE]`.
- The pair map format (`docs/PAIR-MAP.md`) and its loader (`cernis.pairs`).
- `Snapshot.extractor_selection`: declared, prefix, host, or generic.
- Path-prefix site types: `[[site]]` entries in the pair map, the longest
  matching prefix winning, and `cernis audit --map FILE`.
- `peri.lang` 2: a missing or empty `lang` is a defect (WCAG 2 SC 3.1.1).
- `peri.og.core` 2: reports `og:type`; on a page that uses Open Graph, a
  missing required property (`og:title`, `og:type`, `og:image`, `og:url`)
  is a defect. Two new recommendation templates.
- The README logo uses absolute PNG URLs, so it renders on PyPI.
- The `owned` site type, for pages the author fully controls with no specific
  extractor: the generic extractor, and actor `AUTHOR` on every finding. It
  works in the pair map, `[[site]]` prefix rules, and `--site-type`.
- `cernis pair --original URL --copy URL` and `cernis pairs --map FILE`: both
  pages audited, then the pair checks; the report presents each pair as one
  subject with both pages, and the JSON report gains `pairs`.
- `epi.pair.canonical`, the flagship check: the copy's canonical against the
  original's URL, and the original's against its own.
- `epi.canonical.resolves`: each canonical URL's status and redirect chain,
  through the normal fetcher; a defect only for 404 or 410.
- `epi.og.image.resolves`: the og:image URL's status and content type; a
  defect for 404, 410, or a response that is not an image. The image is never
  stored.
- Each distinct URL is fetched once per run, and its receipt reused.
- `Fetcher.fetch(url, store_body=False)`, which neither reads nor writes the
  cache.
- `peri.og.url_matches_canonical` 2: a `DIFFERENT` defect cites the Open
  Graph protocol, which defines `og:url` as the object's canonical URL.
- Five recommendation templates for the epitext checks.
- `peri.robots.directives`: robots meta tags and the `X-Robots-Tag` header,
  as facts.
- `epi.robots.access`: what robots.txt says for `*` and each AI crawler in the
  versioned list `src/cernis/data/ai_crawlers.toml` (13 tokens, each with
  its operator's documentation), never a defect.
- `epi.sitemap.listed`: sitemap discovery (robots.txt, `sitemap.xml`,
  `wp-sitemap.xml`), indexes, and gzip; a defect only when the sitemap lists
  other pages in the section but not this one.
- `epi.links.resolve`: article-body links, deduplicated and fetched without
  storing bodies, limited to 100 per page and 5 per external host per run.
- `ReasonCode.LIMIT_REACHED` (ADR-001 amendment 2).
- `cernis audit --from-sitemap URL [--include-prefix P]` and
  `--from-dev-user NAME`, with `--limit` and `--list-only`; the run records
  its source (`Run.sources`, and `sources` in the JSON report).
- Pair maps accept `copies = [...]`; `cernis pairs --from-dev-user NAME`.
- `--max-links-per-page`, `--max-links-per-host`, `--max-sitemap-documents`.
- Claims C-1 to C-3 have their numbers fixed (DESIGN.md section 8).
- `wordpress.entry` 2: share-button containers (Jetpack and other common
  plugins) are left out of the article body, for links and the content hash.
- A `[[site]]` prefix covering a whole origin makes the whole site one
  section for `epi.sitemap.listed`.
- `epi.og.image.shared`: a site-level fact when audited articles on one site
  share an og:image; reports gain a Site section.
- A run summary: each article's count of AUTHOR defects, and how many
  articles have any, in the Markdown and JSON reports (`summary`,
  `counts.site`).

### Changed

- robots.txt matching moved from `urllib.robotparser`, whose answers differ
  between Python versions, to Cernis's own RFC 9309 matcher.
- The version is read from the package metadata.
- DESIGN.md went from draft 2 to draft 2.9; claims C-1 and C-3 have results
  (section 8), and C-1b is proposed.
- robots.txt reading is version 2 (`epi.robots.access` 1+c1+m2): only the
  first 500 KiB are parsed, a cut-off body keeps lines ended by CR, and a
  4xx answer allows everything even when its body then fails to decode.
- A fetch records and requests URLs without their fragment, and the run
  reuses one fetch for URLs that differ only by fragment.
- Every gzip member is decoded; raw deflate is recognized however the first
  bytes are split; a compressed body that ends early is `CONNECTION`.
- `store_body=False` no longer keeps the resource's robots.txt out of the
  cache.
- A trailing dot in a host no longer escapes pacing.

### Security

- Non-public addresses are refused on every hop, and connections go only to
  the screened addresses (ADR-005). Session 5e (ADR-005 amendment 1) added
  benchmarking, protocol-assignment, and 6to4 relay ranges, Azure's host
  address, every IPv6 address outside global unicast that carries no IPv4,
  and the IPv4 inside IPv4-translated and Teredo addresses.
- Resolving a host is bounded by `connect_timeout`, and a name the resolver
  cannot encode is `CONNECTION`, not a crash.
- Bodies are decoded with bounded output, so a small compressed body cannot
  expand past the size limit.
- Sitemaps are parsed by expat with handlers that refuse any DOCTYPE or
  entity declaration, in any encoding; entries per document and per site
  are capped; index children on other hosts are not followed.
- `--allow-loopback` is refused together with `--from-sitemap` or
  `--from-dev-user`, and warns otherwise.
- A DEV username must be letters, digits, and underscores before it is put
  in a URL.

## [0.0.1] - 2026-10-28

### Added

- Initial package to reserve the `cernis` name on PyPI.
- `cernis` command that prints a project status message, and `cernis --version`.
