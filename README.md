<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kenwalger/cernis/main/img/cernis-mark-dark.png">
  <img alt="Cernis" src="https://raw.githubusercontent.com/kenwalger/cernis/main/img/cernis-mark-light.png" width="96">
</picture>

---

# Cernis

**Cernis** is pronounced *KER-nis*, the classical Latin, with a hard C. It comes
from *cernere*, "to discern."

> *Primum cerne, deinde suade.* (First discern, then advise.)

Cernis is a content discoverability auditor for published articles. Give it the
URL of a published article, and it fetches the page politely, runs deterministic
checks on it, and reports findings that keep three things apart:

- **Observed:** a condition verified directly, with evidence. "The page declares
  no `lang` attribute."
- **Recommendation:** a suggested change, always based on an observation, and
  never a predicted outcome. "Add a `lang` attribute to the `<html>` element."
  Never "this will improve your ranking."
- **Not determinable** (*non liquet*): a question Cernis cannot answer from what
  it can see, with the reason. "Whether AI assistants cite this article cannot
  be determined from the page."

Every finding also says who can act on it (the author, the platform, or unknown)
and carries a receipt: the URL fetched, when, a hash of what came back, and the
evidence. No scores, no grades, no predicted outcomes.

## Status

**Pre-release, under active development.** Single-page audits work today; the
cross-post pair check is next. The version on PyPI (0.0.1) only reserves the
name, so install from source for now. Expect commands and report formats to
change before 0.1.0.

## Install from source

Requires Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/kenwalger/cernis.git
cd cernis
uv sync
uv run cernis --version
```

## Usage

Audit a page and print a Markdown report:

```bash
uv run cernis audit https://dev.to/<user>/<article-slug>
```

Declare the site type, so Cernis knows how to find the article body:

```bash
uv run cernis audit https://example.com/blog/my-post/ --site-type wordpress
```

Or declare site types once, in a map file, and reuse it
(see [docs/PAIR-MAP.md](docs/PAIR-MAP.md)):

```toml
[[site]]
prefix = "https://www.example.com/blog/"
type = "wordpress"
```

```bash
uv run cernis audit https://www.example.com/blog/my-post/ --map cernis-map.toml
```

Other useful commands:

```bash
uv run cernis audit <url> --format json --output report.json   # machine-readable report
uv run cernis checks                                            # list every check and its version
uv run cernis fetch <url>                                       # fetch only, and print the receipts
```

## What it checks today

Checks on the page itself (peritext):

| Check | What it reports |
| --- | --- |
| `peri.canonical.present` | Whether the page declares a canonical URL |
| `peri.canonical.single` | How many canonicals, and whether they conflict |
| `peri.canonical.absolute` | Whether the canonical is an absolute URL |
| `peri.meta.description` | The meta description and its length |
| `peri.og.core` | Each Open Graph property, and any required property missing from a page that uses Open Graph |
| `peri.og.url_matches_canonical` | Whether `og:url` agrees with the canonical URL |
| `peri.lang` | The page's declared language (a missing one fails WCAG 2 success criterion 3.1.1) |
| `peri.jsonld.parses` | Whether each JSON-LD block parses, and its types |
| `peri.title` | The title and its length |

A defect is reported only for a violation of a published standard (such as WCAG
or the Open Graph protocol) or of the author's own stated intent, never for a
style convention. Lengths and counts are reported as facts, not judged.

**Coming next:** the cross-post pair check (does a DEV copy's canonical point at
your original?), whether canonical URLs and social images actually resolve,
robots.txt access for AI crawlers, sitemaps, broken links, and history across
runs, which tells you whether a change came from you, the platform, or Cernis
itself.

## Polite by design

- Identifies itself: `Cernis/<version> (+https://github.com/kenwalger/cernis)`
- Respects robots.txt for its own user agent, using its own RFC 9309 matcher
- Paces requests (one per second per host by default) and backs off when rate
  limited
- Refuses to contact private, loopback, and cloud metadata addresses
- Audit your own content. Cernis is built for authors checking their own
  articles, not for crawling other people's sites.

## Documentation

- [docs/DESIGN.md](docs/DESIGN.md): the design, principles, and plan
- [docs/PAIR-MAP.md](docs/PAIR-MAP.md): the map file format
- [docs/adr/](docs/adr/): architecture decisions
- [docs/RELEASING.md](docs/RELEASING.md): how releases are made
- [BRAND.md](BRAND.md): the name and logo

Cernis is a sibling project of [Afterword](https://github.com/kenwalger/Afterword).

## License

Apache-2.0. See [LICENSE](LICENSE).