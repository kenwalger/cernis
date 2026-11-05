# Cernis audit

Run: 20261030T120000Z-0a1b2c · Cernis 0.1.0.dev0
Started: 2026-10-30T12:00:00+00:00 · Finished: 2026-10-30T12:00:01+00:00
Checks: peri.canonical.present 1 · peri.canonical.single 1 · peri.canonical.absolute 1 · peri.meta.description 1 · peri.og.core 2 · peri.og.url_matches_canonical 2 · peri.lang 2 · peri.jsonld.parses 1 · peri.title 1 · peri.robots.directives 1 · epi.canonical.resolves 1 · epi.og.image.resolves 1 · epi.robots.access 1+c1+m2 · epi.sitemap.listed 1 · epi.links.resolve 1

Subjects:

- https://dev.to/example-author/a-synthetic-post-1a2b: read whole (receipt r-002); extractor dev.article 1+n1, host
- https://blog.example.com/two-canonicals/: read whole (receipt r-004); extractor wordpress.entry 2+n1, declared
- https://blog.example.com/gone/: not read (FETCH_FAILED)

## Summary

AUTHOR defects per article:

- https://dev.to/example-author/a-synthetic-post-1a2b: 2
- https://blog.example.com/two-canonicals/: 2
- https://blog.example.com/gone/: 0

Articles with at least one AUTHOR defect: 2 of 3.

## Site (0)

None.

## Observed (79)

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

- PLATFORM · peri.og.core · og:type
  og:type is present.
  Evidence: `head > meta[property="og:type"] content`: `article` (receipt r-002)

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
  og:url (https://dev.to/example-author/a-synthetic-post-1a2b) and the canonical URL (https://blog.example.com/2026/10/a-synthetic-post/) are different; the Open Graph protocol (ogp.me) defines og:url as the object's canonical URL.
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

- PLATFORM · peri.robots.directives
  The page declares no robots directives: no robots meta tag and no X-Robots-Tag header.
  Evidence: `the whole document`: searched for a \<meta\> named one of: amazonbot, applebot-extended, bingbot, ccbot, chatgpt-user, claude-searchbot, claude-user, claudebot, google-extended, googlebot, googlebot-news, gptbot, meta-externalagent, oai-searchbot, perplexity-user, perplexitybot, robots, found none (receipt r-002)
  Evidence: `response headers`: searched for an X-Robots-Tag header, found none (receipt r-002)

- AUTHOR · epi.canonical.resolves · https://blog.example.com/2026/10/a-synthetic-post/
  The canonical URL https://blog.example.com/2026/10/a-synthetic-post/ answers 200.
  Evidence: `HTTP status`: `200` (receipt r-006)

- PLATFORM · epi.og.image.resolves · https://media.dev.example/cover/synthetic-cover.png
  og:image https://media.dev.example/cover/synthetic-cover.png answers 200 with an image (image/png).
  Evidence: `HTTP status`: `200` (receipt r-008)
  Evidence: `Content-Type`: `image/png` (receipt r-008)

- PLATFORM · epi.robots.access · \*
  robots.txt answered 404, so under RFC 9309 it allows general crawlers (\*) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · GPTBot
  robots.txt answered 404, so under RFC 9309 it allows GPTBot (OpenAI) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · ChatGPT-User
  robots.txt answered 404, so under RFC 9309 it allows ChatGPT-User (OpenAI) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · OAI-SearchBot
  robots.txt answered 404, so under RFC 9309 it allows OAI-SearchBot (OpenAI) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · ClaudeBot
  robots.txt answered 404, so under RFC 9309 it allows ClaudeBot (Anthropic) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Claude-User
  robots.txt answered 404, so under RFC 9309 it allows Claude-User (Anthropic) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Claude-SearchBot
  robots.txt answered 404, so under RFC 9309 it allows Claude-SearchBot (Anthropic) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Google-Extended
  robots.txt answered 404, so under RFC 9309 it allows Google-Extended (Google) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · PerplexityBot
  robots.txt answered 404, so under RFC 9309 it allows PerplexityBot (Perplexity) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Perplexity-User
  robots.txt answered 404, so under RFC 9309 it allows Perplexity-User (Perplexity) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · CCBot
  robots.txt answered 404, so under RFC 9309 it allows CCBot (Common Crawl) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Applebot-Extended
  robots.txt answered 404, so under RFC 9309 it allows Applebot-Extended (Apple) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Amazonbot
  robots.txt answered 404, so under RFC 9309 it allows Amazonbot (Amazon) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- PLATFORM · epi.robots.access · Meta-ExternalAgent
  robots.txt answered 404, so under RFC 9309 it allows Meta-ExternalAgent (Meta) to fetch this page.
  Evidence: `https://dev.to/robots.txt`: `404` (receipt r-001)

- DEFECT · AUTHOR · epi.links.resolve · https://www.example.org/paper
  The link https://www.example.org/paper answers 404, so it leads to no page.
  Evidence: `HTTP status`: `404` (receipt r-010)

- DEFECT · AUTHOR · epi.links.resolve · https://dev.to/example-author/another-post-3c4d
  The link https://dev.to/example-author/another-post-3c4d answers 404, so it leads to no page.
  Evidence: `HTTP status`: `404` (receipt r-011)

- AUTHOR · epi.links.resolve · skipped links
  1 of the article body's 3 links is not checked, by design: 1 fragment-only.
  Evidence: `article body links`: `1 fragment-only` (receipt r-002)

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

- AUTHOR · peri.og.core · og:type
  og:type is absent.
  Evidence: `the whole document`: searched for a \<meta property="og:type"\>, found none (receipt r-004)

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

- AUTHOR · peri.robots.directives
  The page declares no robots directives: no robots meta tag and no X-Robots-Tag header.
  Evidence: `the whole document`: searched for a \<meta\> named one of: amazonbot, applebot-extended, bingbot, ccbot, chatgpt-user, claude-searchbot, claude-user, claudebot, google-extended, googlebot, googlebot-news, gptbot, meta-externalagent, oai-searchbot, perplexity-user, perplexitybot, robots, found none (receipt r-004)
  Evidence: `response headers`: searched for an X-Robots-Tag header, found none (receipt r-004)

- AUTHOR · epi.canonical.resolves · https://blog.example.com/two-canonicals/
  The canonical URL https://blog.example.com/two-canonicals/ answers 200.
  Evidence: `HTTP status`: `200` (receipt r-004)

- DEFECT · AUTHOR · epi.canonical.resolves · https://dev.to/example-author/two-canonicals-5e6f
  The canonical URL https://dev.to/example-author/two-canonicals-5e6f answers 404, so it names no page.
  Evidence: `HTTP status`: `404` (receipt r-012)

- AUTHOR · epi.robots.access · \*
  robots.txt answered 404, so under RFC 9309 it allows general crawlers (\*) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · GPTBot
  robots.txt answered 404, so under RFC 9309 it allows GPTBot (OpenAI) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · ChatGPT-User
  robots.txt answered 404, so under RFC 9309 it allows ChatGPT-User (OpenAI) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · OAI-SearchBot
  robots.txt answered 404, so under RFC 9309 it allows OAI-SearchBot (OpenAI) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · ClaudeBot
  robots.txt answered 404, so under RFC 9309 it allows ClaudeBot (Anthropic) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Claude-User
  robots.txt answered 404, so under RFC 9309 it allows Claude-User (Anthropic) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Claude-SearchBot
  robots.txt answered 404, so under RFC 9309 it allows Claude-SearchBot (Anthropic) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Google-Extended
  robots.txt answered 404, so under RFC 9309 it allows Google-Extended (Google) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · PerplexityBot
  robots.txt answered 404, so under RFC 9309 it allows PerplexityBot (Perplexity) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Perplexity-User
  robots.txt answered 404, so under RFC 9309 it allows Perplexity-User (Perplexity) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · CCBot
  robots.txt answered 404, so under RFC 9309 it allows CCBot (Common Crawl) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Applebot-Extended
  robots.txt answered 404, so under RFC 9309 it allows Applebot-Extended (Apple) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Amazonbot
  robots.txt answered 404, so under RFC 9309 it allows Amazonbot (Amazon) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Meta-ExternalAgent
  robots.txt answered 404, so under RFC 9309 it allows Meta-ExternalAgent (Meta) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.sitemap.listed
  No sitemap was found: Cernis looked in robots.txt and at https://blog.example.com/sitemap.xml (answered 404); https://blog.example.com/wp-sitemap.xml (answered 404).
  Evidence: `robots.txt`: searched for a Sitemap: line, found none (receipt r-003)
  Evidence: `https://blog.example.com/sitemap.xml`: `answered 404` (receipt r-013)
  Evidence: `https://blog.example.com/wp-sitemap.xml`: `answered 404` (receipt r-014)

- AUTHOR · epi.links.resolve
  The article body has no links.
  Evidence: `article body`: searched for an \<a href\> element, found none (receipt r-004)

### https://blog.example.com/gone/

- AUTHOR · epi.robots.access · \*
  robots.txt answered 404, so under RFC 9309 it allows general crawlers (\*) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · GPTBot
  robots.txt answered 404, so under RFC 9309 it allows GPTBot (OpenAI) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · ChatGPT-User
  robots.txt answered 404, so under RFC 9309 it allows ChatGPT-User (OpenAI) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · OAI-SearchBot
  robots.txt answered 404, so under RFC 9309 it allows OAI-SearchBot (OpenAI) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · ClaudeBot
  robots.txt answered 404, so under RFC 9309 it allows ClaudeBot (Anthropic) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Claude-User
  robots.txt answered 404, so under RFC 9309 it allows Claude-User (Anthropic) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Claude-SearchBot
  robots.txt answered 404, so under RFC 9309 it allows Claude-SearchBot (Anthropic) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Google-Extended
  robots.txt answered 404, so under RFC 9309 it allows Google-Extended (Google) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · PerplexityBot
  robots.txt answered 404, so under RFC 9309 it allows PerplexityBot (Perplexity) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Perplexity-User
  robots.txt answered 404, so under RFC 9309 it allows Perplexity-User (Perplexity) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · CCBot
  robots.txt answered 404, so under RFC 9309 it allows CCBot (Common Crawl) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Applebot-Extended
  robots.txt answered 404, so under RFC 9309 it allows Applebot-Extended (Apple) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Amazonbot
  robots.txt answered 404, so under RFC 9309 it allows Amazonbot (Amazon) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

- AUTHOR · epi.robots.access · Meta-ExternalAgent
  robots.txt answered 404, so under RFC 9309 it allows Meta-ExternalAgent (Meta) to fetch this page.
  Evidence: `https://blog.example.com/robots.txt`: `404` (receipt r-003)

## Recommendations (4)

### https://dev.to/example-author/a-synthetic-post-1a2b

- Update or remove the article's link to https://www.example.org/paper.
  Why: The link names https://www.example.org/paper, which answers 404: HTTP defines 404 as no current representation of the resource and 410 as gone (RFC 9110).
  Based on: epi.links.resolve (The link https://www.example.org/paper answers 404, so it leads to no page.)

- Update or remove the article's link to https://dev.to/example-author/another-post-3c4d.
  Why: The link names https://dev.to/example-author/another-post-3c4d, which answers 404: HTTP defines 404 as no current representation of the resource and 410 as gone (RFC 9110).
  Based on: epi.links.resolve (The link https://dev.to/example-author/another-post-3c4d answers 404, so it leads to no page.)

### https://blog.example.com/two-canonicals/

- Remove the extra canonical links so that the page declares one canonical URL, the page's preferred URL.
  Why: The page declares 2 canonical links that name different URLs (https://blog.example.com/two-canonicals/, https://dev.to/example-author/two-canonicals-5e6f). RFC 6596 defines the canonical link relation as naming one preferred URL for a page; links that disagree leave that URL undeclared.
  Based on: peri.canonical.single (The page declares 2 canonical links that name different URLs.)

- Change the canonical URL https://dev.to/example-author/two-canonicals-5e6f to the URL of a page that exists.
  Why: A canonical URL names the preferred URL for the page (RFC 6596), and https://dev.to/example-author/two-canonicals-5e6f answers 404, so it names no page.
  Based on: epi.canonical.resolves (The canonical URL https://dev.to/example-author/two-canonicals-5e6f answers 404, so it names no page.)

## Not determinable (non liquet) (16)

### https://blog.example.com/gone/

- The page could not be read: the request timed out.
  Reason: FETCH_FAILED. Not determinable: whether the page declares a canonical link; how many canonical URLs the page declares, and whether they agree; whether the page's canonical URL is absolute; whether the page has a meta description, and how long it is; whether the page declares og:title; whether the page declares og:type; whether the page declares og:description; whether the page declares og:image; whether the page declares og:url; whether og:url agrees with the canonical URL; whether the page declares its language; whether the page's JSON-LD blocks parse; what the page's title is, and how long it is; which robots directives the page declares; whether the site's sitemap lists the page; whether the article body's links resolve.
  Evidence: `error_kind`: `TIMEOUT` (receipt r-005)
