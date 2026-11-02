# The pair map file

A pair map tells Cernis which article is the **original** and which is a **copy** (a cross-post), and which kind of site a URL is on: one URL at a time, or for a whole part of a site by URL prefix. `cernis audit --map <file>` and `cernis pair --map <file>` use it for site types; `cernis pairs --map <file>` audits every pair in it and runs the flagship check, `epi.pair.canonical`, over each. The format was defined in Session 4b; Session 4d added `[[site]]` prefix rules; Session 5a added the `owned` site type and the pair commands.

## Format

A TOML file, UTF-8:

```toml
# My cross-posted articles.
format = 1

[[pair]]
original = { url = "https://kenwalger.com/blog/a-word-list-tied-the-model/", site = "wordpress" }
copy = { url = "https://dev.to/kenwalger/a-word-list-tied-the-model-1a2b", site = "dev" }

[[pair]]
original = { url = "https://www.kenwalger.com/blog/writing/views-measure-views-nine-years-writing" }
copy = { url = "https://dev.to/kenwalger/views-measure-views-4co7" }

# Everything under the blog is WordPress, so its URLs need no site of their own.
[[site]]
prefix = "https://www.kenwalger.com/blog/"
type = "wordpress"
```

| Key | Required | Meaning |
| --- | --- | --- |
| `format` | yes | The format version. Must be `1`. |
| `[[pair]]` | see below | One original and its copy. |
| `original.url`, `copy.url` | yes | An absolute `http` or `https` URL. |
| `original.site`, `copy.site` | no | The URL's site type: `dev`, `wordpress`, or `owned`. |
| `[[site]]` | no | A prefix rule: every URL under `prefix` has site type `type`. |
| `site.prefix` | yes, in a `[[site]]` | An absolute `http` or `https` URL with no query or fragment. |
| `site.type` | yes, in a `[[site]]` | `dev`, `wordpress`, or `owned`. |

A map needs at least one `[[pair]]` or one `[[site]]`; a map of prefix rules alone is fine.

Tables may be written inline, as above, or as sub-tables (`[pair.original]`); TOML treats them the same.

## Site types

A site type chooses how Cernis finds the article body (DESIGN.md section 3):

| `site` | Extractor | Article body |
| --- | --- | --- |
| `dev` | `dev.article` | `#article-body` |
| `wordpress` | `wordpress.entry` | `.entry-content`, else `.wp-block-post-content` |
| `owned` | `generic` | none: `generic` finds no body |
| (none) | by host: `dev.article` on `dev.to`; otherwise `generic` | `generic` finds no body |

The site type is decided by the first of these that applies:

1. the command line: `cernis audit --site-type dev|wordpress|owned` for every URL on it, or `cernis pair --original-site` and `--copy-site` for one URL each;
2. the URL's own `site` in the pair map (matched after URL normalization);
3. the **longest** `[[site]]` prefix the URL is under;
4. the host: `dev.to` is `dev`;
5. nothing: the `generic` extractor, which finds no body.

So a URL on `dev.to` declared `wordpress` uses `wordpress.entry`, and a URL under two prefixes takes the longer one. Cernis never guesses a site type from page content, so a WordPress site, whose host Cernis cannot recognize, gets no article-body hash unless it is declared or under a prefix. Each snapshot records which rule chose its extractor: `declared` (1 or 2), `prefix`, `host`, or `generic`.

**Owned pages.** `owned` is for pages the author fully controls (a static site, a self-hosted blog without a WordPress theme) that have no specific extractor. The page is read with the `generic` extractor, so it has no article-body hash, and every finding about it, including a fetch that failed, has actor `AUTHOR`: there is no platform between the author and the page. Without `owned`, a generic page's fetch outcomes are `UNKNOWN`. `dev` pages put some findings on the `PLATFORM`, and `wordpress` and `owned` pages put them all on the `AUTHOR` (DESIGN.md section 4).

**How prefixes match.** The prefix and the URL are both normalized (DESIGN.md section 3: scheme and host case, default port, trailing slash, and so on), then compared by whole path segments: `https://www.kenwalger.com/blog/` covers `/blog`, `/blog/`, `/blog/writing/a-post`, and `/blog?page=2`, but not `/blogger`. Scheme and host must match exactly after normalization, so `http` and `https`, or `www.kenwalger.com` and `kenwalger.com`, are different prefixes. Prefixes are matched against the URL that answered, after redirects.

## The pair commands

```
cernis pair --original <url> --copy <url> [--original-site TYPE] [--copy-site TYPE] [--map FILE]
cernis pairs --map FILE
```

Both take `--format md|json`, `--output FILE`, and `--cache-dir DIR`, as `cernis audit` does. `cernis pair` audits one pair; with `--map`, the map's site types and prefix rules apply, and `--original-site` and `--copy-site` override them. `cernis pairs` audits every `[[pair]]` in the map in one run, and refuses a map with none.

A pair run audits both pages (every peritext check), checks each page's canonical URL and og:image (`epi.canonical.resolves`, `epi.og.image.resolves`), and then runs `epi.pair.canonical`: the copy's canonical against the original's URL, and the original's canonical against its own. Each distinct URL is fetched once per run, so an original shared by two pairs, or a canonical that is the page itself, costs one request. The report presents each pair as one subject with both pages: the original, the copy, and the pair check.

## Rules

Loading fails, naming the pair and the key, when:

- the file is not valid TOML, or `format` is not `1`;
- there is neither a `[[pair]]` nor a `[[site]]`;
- a key is not one of those above (a typo such as `orginal` or `sites` is an error, not ignored);
- a `url` is missing, or is not an absolute `http` or `https` URL;
- a `site` is not `dev`, `wordpress`, or `owned`;
- a pair's copy is the same URL as its original (compared after URL normalization);
- one URL is declared with two different site types in different pairs (again compared after normalization). Declaring it the same way twice, or once with a site and once without, is fine;
- a `[[site]]` has an unknown key, a missing or non-absolute `prefix`, a prefix with a query or fragment, or a `type` other than `dev`, `wordpress`, or `owned`;
- one prefix (after normalization) is given two different types. Giving it the same type twice is fine.
