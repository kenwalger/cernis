# SDK friction log

Cernis is the first consumer of the Sovereign Systems SDK outside the SDK's own repositories. This log records every rough edge met while using it (sovereign-ledger as the receipt store, and sovereign-sieve if it is adopted for extraction): what was tried, what happened, what was expected, and the workaround. Each entry is dated and becomes an issue on the SDK. Entries are never reworded; a correction is a new, dated entry.

## 2026-10-30: sovereign-sieve evaluated for HTML and metadata extraction (Session 4a)

**Tried.** DESIGN.md section 13, open question 1: does sovereign-sieve fit Cernis's extraction step (Session 4a items 1 and 2: reading `<title>`, `<html lang>`, canonical links, meta description, `og:*`, JSON-LD, and body links, and finding the article body)? Evaluated in a throwaway environment (`uv run --isolated --no-project --with sovereign-sdk-sieve==1.3.0`), never added to Cernis's dependencies, against the synthetic fixtures in `tests/fixtures/`.

**Friction 1: the package name moved.** `pip install sovereign-sieve` installs `sovereign-sieve` 1.1.1, an empty package whose summary says "This package has transitioned. Please install sovereign-sdk-sieve instead" and which depends on `sovereign-sdk-sieve>=1.3.0`. The import name stayed `sovereign_sieve`, so `pip install sovereign-sdk-sieve` then `import sovereign_sieve` is the working spelling. DESIGN.md and this log still say "sovereign-sieve". Expected: one name, or the old name's README saying which import to use. Workaround: install `sovereign-sdk-sieve`.

**Friction 2: no metadata.** On PyPI, `sovereign-sdk-sieve` 1.3.0 declares no `requires_python` in the stub (`sovereign-sieve` 1.1.1) and no license on the stub; the real package says Python 3.12+ and MIT. Minor, but a consumer checking licenses sees the stub's blank.

**What it is.** A "Prose Tax" token optimizer: `pure_sieve(payload: str) -> str` and `sieve_with_metrics(payload: str) -> SieveOutput` strip greetings, hedges ("please", "just"), filler ("of course"), preamble phrases ("I hope this"), degenerate markdown, and repeated headings from LLM prompts, and estimate token savings. It has no HTML parsing, no selectors, and no notion of elements, attributes, or document structure.

**Against item 1 (metadata extraction): does not fit.** There is nothing to call: it cannot find a `<link rel="canonical">`, read an attribute, or tell `<head>` from `<body>`. Run on raw fixture HTML it returns rewritten HTML: on `dev-article.html` it changed 3464 characters to 3274 (indentation collapsed), and on `malformed.html` it changed the JSON-LD text (`"Caféé" , }` became `"Caféé", }`). Evidence must record what the page said, so any rewrite of the source before extraction is disqualifying.

**Against item 2 (article body): does not fit, and would be harmful.** Given the article text "This page is written by hand. It links to a paper. Please just read it. I hope this helps.", it returned "This page is written by hand. It links to a paper. read it. helps." It deletes the author's own words. Used before `content_sha256`, an author adding or removing "please" would not be seen as a content change, and any finding quoting the text would misquote it.

**Against snapshot normalization (item 3): does not fit.** It does not remove volatile tokens: the two volatile-token fixtures, which differ only in CSRF values, nonces, and asset hashes, are still different after `pure_sieve`. It is deterministic (the same input gives the same output), which is the one property Cernis would need.

**Conclusion, for the Owner's decision.** sovereign-sieve solves a different problem (shrinking prompts for an LLM) from Cernis's (reading HTML exactly). Session 4a uses selectolax, as DESIGN.md section 6 names. Nothing here is a defect in sovereign-sieve; it is a fit question. Possible SDK issues: unify the package name; and, if the SDK means to offer HTML extraction, that would be a separate module, since prose sieving must never run on evidence. Claim C-5 concerns sovereign-ledger only and is not affected.
