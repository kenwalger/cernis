# The pair map file

A pair map tells Cernis which article is the **original** and which is a **copy** (a cross-post), and, for any URL, which kind of site it is on. Phase 4's `cernis pairs --map <file>` runs the flagship check, `epi.pair.canonical`, over every pair. The format is defined now (Session 4b) so site types have one place to be declared.

## Format

A TOML file, UTF-8:

```toml
# My cross-posted articles.
format = 1

[[pair]]
original = { url = "https://kenwalger.com/blog/a-word-list-tied-the-model/", site = "wordpress" }
copy = { url = "https://dev.to/kenwalger/a-word-list-tied-the-model-1a2b", site = "dev" }

[[pair]]
original = { url = "https://kenwalger.com/blog/views-measure-views/", site = "wordpress" }
copy = { url = "https://dev.to/kenwalger/views-measure-views-4co7" }
```

| Key | Required | Meaning |
| --- | --- | --- |
| `format` | yes | The format version. Must be `1`. |
| `[[pair]]` | at least one | One original and its copy. |
| `original.url`, `copy.url` | yes | An absolute `http` or `https` URL. |
| `original.site`, `copy.site` | no | The URL's site type: `dev` or `wordpress`. |

Tables may be written inline, as above, or as sub-tables (`[pair.original]`); TOML treats them the same.

## Site types

A site type chooses how Cernis finds the article body (DESIGN.md section 3):

| `site` | Extractor | Article body |
| --- | --- | --- |
| `dev` | `dev.article` | `#article-body` |
| `wordpress` | `wordpress.entry` | `.entry-content`, else `.wp-block-post-content` |
| (none) | by host: `dev.article` on `dev.to`; otherwise `generic` | `generic` finds no body |

**A declaration overrides host detection.** A URL on `dev.to` declared `wordpress` uses `wordpress.entry`. Cernis never guesses a site type from page content, so a WordPress site, whose host Cernis cannot recognize, gets no article-body hash unless it is declared. Each snapshot records how its extractor was chosen: `declared`, `host`, or `generic`.

`cernis audit --site-type dev|wordpress` declares one site type for every URL given on that command line.

## Rules

Loading fails, naming the pair and the key, when:

- the file is not valid TOML, or `format` is not `1`;
- there is no `[[pair]]`;
- a key is not one of those above (a typo such as `orginal` or `sites` is an error, not ignored);
- a `url` is missing, or is not an absolute `http` or `https` URL;
- a `site` is not `dev` or `wordpress`;
- a pair's copy is the same URL as its original (compared after URL normalization);
- one URL is declared with two different site types in different pairs (again compared after normalization). Declaring it the same way twice, or once with a site and once without, is fine.
