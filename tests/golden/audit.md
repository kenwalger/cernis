# Cernis audit

Run: 20261030T120000Z · Cernis 0.1.0.dev0
Started: 2026-10-30T12:00:00+00:00 · Finished: 2026-10-30T12:00:01+00:00
Checks: peri.canonical.present 1 · peri.canonical.single 1 · peri.canonical.absolute 1 · peri.meta.description 1 · peri.og.core 1 · peri.og.url_matches_canonical 1 · peri.lang 1 · peri.jsonld.parses 1 · peri.title 1

Subjects:

- https://dev.to/example-author/a-synthetic-post-1a2b: read whole (receipt r-002); extractor dev.article 1+n1, host
- https://blog.example.com/two-canonicals/: read whole (receipt r-004); extractor wordpress.entry 1+n1, declared
- https://blog.example.com/gone/: not read (FETCH_FAILED)

## Observed (24)

### https://dev.to/example-author/a-synthetic-post-1a2b

- AUTHOR · peri.canonical.present
  The page declares a canonical link.
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/2026/10/a-synthetic-post/` (receipt r-002)

- AUTHOR · peri.canonical.single
  The page declares one canonical URL: https://blog.example.com/2026/10/a-synthetic-post/.
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/2026/10/a-synthetic-post/` (receipt r-002)

- AUTHOR · peri.canonical.absolute
  The canonical URL is absolute.
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/2026/10/a-synthetic-post/` (receipt r-002)

- AUTHOR · peri.meta.description
  The page has a meta description of 68 characters.
  Evidence: `head > meta[name="description"] content`: `A hand-written page that imitates a DEV article, for Cernis's tests.` (receipt r-002)

- AUTHOR · peri.og.core · og:title
  og:title is present.
  Evidence: `head > meta[property="og:title"] content`: `A Synthetic Post About Fixtures` (receipt r-002)

- AUTHOR · peri.og.core · og:description
  og:description is present.
  Evidence: `head > meta[property="og:description"] content`: `A hand-written page that imitates a DEV article.` (receipt r-002)

- AUTHOR · peri.og.core · og:image
  og:image is present.
  Evidence: `head > meta[property="og:image"] content`: `https://media.dev.example/cover/synthetic-cover.png` (receipt r-002)

- PLATFORM · peri.og.core · og:url
  og:url is present.
  Evidence: `head > meta[property="og:url"] content`: `https://dev.to/example-author/a-synthetic-post-1a2b` (receipt r-002)

- DEFECT · PLATFORM · peri.og.url_matches_canonical
  og:url (https://dev.to/example-author/a-synthetic-post-1a2b) and the canonical URL (https://blog.example.com/2026/10/a-synthetic-post/) are different.
  Evidence: `head > meta[property="og:url"] content`: `https://dev.to/example-author/a-synthetic-post-1a2b` (receipt r-002)
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/2026/10/a-synthetic-post/` (receipt r-002)

- PLATFORM · peri.lang
  The page declares its language as 'en'.
  Evidence: `html lang`: `en` (receipt r-002)

- PLATFORM · peri.jsonld.parses · block 1
  JSON-LD block 1 parses; its @type is Article.
  Evidence: `script[type="application/ld+json"] #1`: `{ "@context": "http://schema.org", "@type": "Article", "headline": "A Synthetic Post About Fixtures", "author": {"@type": "Person", "name": "Example Author"}, "`... (200 characters) (receipt r-002)

- PLATFORM · peri.title
  The page's title is 47 characters long.
  Evidence: `head > title`: `A Synthetic Post About Fixtures - DEV Community` (receipt r-002)

### https://blog.example.com/two-canonicals/

- AUTHOR · peri.canonical.present
  The page declares 2 canonical links.
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/two-canonicals/` (receipt r-004)
  Evidence: `head > link[rel="canonical"] href`: `https://dev.to/example-author/two-canonicals-5e6f` (receipt r-004)

- DEFECT · AUTHOR · peri.canonical.single
  The page declares 2 canonical links that name different URLs.
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/two-canonicals/` (receipt r-004)
  Evidence: `head > link[rel="canonical"] href`: `https://dev.to/example-author/two-canonicals-5e6f` (receipt r-004)

- AUTHOR · peri.canonical.absolute
  All 2 canonical URLs are absolute.
  Evidence: `head > link[rel="canonical"] href`: `https://blog.example.com/two-canonicals/` (receipt r-004)
  Evidence: `head > link[rel="canonical"] href`: `https://dev.to/example-author/two-canonicals-5e6f` (receipt r-004)

- AUTHOR · peri.meta.description
  The page has a meta description of 34 characters.
  Evidence: `head > meta[name="description"] content`: `Two canonical links that disagree.` (receipt r-004)

- AUTHOR · peri.og.core · og:title
  og:title is absent.
  Evidence: `the whole document`: searched for a \<meta property="og:title"\>, found none (receipt r-004)

- AUTHOR · peri.og.core · og:description
  og:description is absent.
  Evidence: `the whole document`: searched for a \<meta property="og:description"\>, found none (receipt r-004)

- AUTHOR · peri.og.core · og:image
  og:image is absent.
  Evidence: `the whole document`: searched for a \<meta property="og:image"\>, found none (receipt r-004)

- AUTHOR · peri.og.core · og:url
  og:url is absent.
  Evidence: `the whole document`: searched for a \<meta property="og:url"\>, found none (receipt r-004)

- AUTHOR · peri.og.url_matches_canonical
  There is no og:url to compare with the canonical URL.
  Evidence: `the whole document`: searched for a \<meta property="og:url"\>, found none (receipt r-004)

- AUTHOR · peri.lang
  The page declares its language as 'en'.
  Evidence: `html lang`: `en` (receipt r-004)

- AUTHOR · peri.jsonld.parses
  The page has no JSON-LD blocks.
  Evidence: `the whole document`: searched for \<script type="application/ld+json"\>, found none (receipt r-004)

- AUTHOR · peri.title
  The page's title is 26 characters long.
  Evidence: `head > title`: `A Post With Two Canonicals` (receipt r-004)

## Recommendations (1)

### https://blog.example.com/two-canonicals/

- Remove the extra canonical links so that the page declares one canonical URL, the page's preferred URL.
  Why: The page declares 2 canonical links that name different URLs (https://blog.example.com/two-canonicals/, https://dev.to/example-author/two-canonicals-5e6f). RFC 6596 defines the canonical link relation as naming one preferred URL for a page; links that disagree leave that URL undeclared.
  Based on: peri.canonical.single (The page declares 2 canonical links that name different URLs.)

## Not determinable (non liquet) (12)

### https://blog.example.com/gone/

- The page could not be read: the request timed out.
  Reason: FETCH_FAILED. Not determinable: whether the page declares a canonical link; how many canonical URLs the page declares, and whether they agree; whether the page's canonical URL is absolute; whether the page has a meta description, and how long it is; whether the page declares og:title; whether the page declares og:description; whether the page declares og:image; whether the page declares og:url; whether og:url agrees with the canonical URL; whether the page declares its language; whether the page's JSON-LD blocks parse; what the page's title is, and how long it is.
  Evidence: `error_kind`: `TIMEOUT` (receipt r-005)
