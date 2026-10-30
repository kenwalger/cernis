# Test fixtures

All fixtures in this directory are synthetic: hand-written HTML pages, robots.txt files, and sitemaps. None is captured from a real page, and none may be.

- Write each fixture by hand to exercise one condition (a missing canonical, two canonicals, a relative canonical, and so on).
- Real fetched pages live only in the git-ignored cache, never here.

## The pages

Each imitates the structure of a DEV article or a WordPress entry. The hosts are `dev.to` (so host-based extractor selection can be tested) or reserved example domains, the author is "Example Author", and every token is made up.

| Fixture | Imitates | Condition |
| --- | --- | --- |
| `dev-article.html` | DEV | Well formed: one canonical (pointing at the WordPress original), description, `og:*`, one JSON-LD block, `#article-body`, a CSRF token and hashed assets |
| `wordpress-entry.html` | WordPress | Well formed: single-quoted attributes, Yoast-style JSON-LD graph, `.entry-content`, `?ver=` assets, a `_wpnonce` |
| `missing-canonical.html` | WordPress | No `rel="canonical"` link (other `link` elements present) |
| `two-canonicals.html` | WordPress | Two canonicals with different hosts, one with `rel="CANONICAL"` |
| `relative-canonical.html` | WordPress | A canonical that is a path |
| `missing-og.html` | WordPress | No `og:url` or description, no `html lang`, an `og:` property in `name=`, and an empty `og:image` |
| `broken-jsonld.html` | WordPress | Four JSON-LD blocks: valid, broken, an array with a list `@type`, and empty; plus a non-JSON-LD script |
| `malformed.html` | WordPress | No head or body tags, unquoted attributes, misnested and unclosed elements, a canonical with no `href`, JSON-LD with a trailing comma, two `.entry-content` blocks, and a `meta` in the body |
| `volatile-a.html`, `volatile-b.html` | DEV | The same page twice, differing only in volatile tokens: the CSRF meta, hidden-input and `data-` values, nonces, `integrity` hashes, hashed asset file names, `?ver=` values, and a token in an inline script |
