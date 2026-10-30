"""The nine peritext checks (DESIGN.md section 4, "Peritext: on the page").

Each check reads a :class:`~cernis.parse.ParsedPage` and returns findings,
following the table's two columns exactly: "Reports" is what every finding
says, and "Defect when" is the only condition that sets ``defect``. A check
the table marks "never" reports facts only. Lengths are facts, never
defects (principle 4). Absence is evidence: when Cernis looks for something
and finds nothing, the evidence says what it searched for (principle 5).

One finding per check, except where the table says otherwise:
``peri.og.core`` gives one per property (the property is the ``target``),
and ``peri.jsonld.parses`` one per block (``block 1``, ``block 2``, ...; or
one with an empty target when there are no blocks). ``peri.canonical.absolute``
gives none when there is no canonical, since there is nothing to assess.

**Actors** (DESIGN.md section 3): on WordPress the author controls
everything; on DEV the author controls what the front matter sets (the
canonical URL, the description, the title and cover image behind
``og:title``, ``og:description``, and ``og:image``) and the platform
controls the template (``og:type``, ``og:url``, ``lang``, JSON-LD, and the
``<title>`` DEV builds as "<title> - DEV Community"). With no known site type, the actor
is ``UNKNOWN``.

Lengths are counted in characters after whitespace is collapsed and NFC is
applied, which is the text a reader sees.
"""

from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from cernis.checks.registry import check
from cernis.model import Actor, Evidence, Finding, ReasonCode, Receipt, Status
from cernis.parse.extractors import SiteType
from cernis.parse.html import Canonical, MetaTag, ParsedPage, normalize_text
from cernis.urls import UrlMatch, compare_urls, is_absolute_http_url

OG_CORE: tuple[str, ...] = ("og:title", "og:type", "og:description", "og:image", "og:url")
"""The five properties ``peri.og.core`` reports on, in order."""

OG_REQUIRED: frozenset[str] = frozenset({"og:title", "og:type", "og:image", "og:url"})
"""The Open Graph protocol's required properties (ogp.me, "Basic Metadata")."""

OPEN_GRAPH = "the Open Graph protocol (ogp.me)"
"""How a finding names the Open Graph standard."""

WCAG_LANGUAGE = "WCAG 2 success criterion 3.1.1 (Language of Page, Level A)"
"""How a finding names the WCAG criterion for a page's language."""

WHOLE_DOCUMENT = "the whole document"
"""The location of a search that covered the page and found nothing."""

_DEV_PLATFORM = frozenset(
    {
        ("peri.og.core", "og:type"),
        ("peri.og.core", "og:url"),
        ("peri.og.url_matches_canonical", ""),
        ("peri.lang", ""),
        ("peri.jsonld.parses", ""),
        ("peri.title", ""),
    }
)

NewId = Callable[[], str]
"""Returns the next finding id in the run."""


def actor_for(site: SiteType | None, check_id: str, target: str = "") -> Actor:
    """Say who can change what a check looks at.

    :param site: The page's site type, declared or detected; ``None`` if unknown.
    :param check_id: The check.
    :param target: The finding's target; only ``og:url`` matters, and every
        JSON-LD block counts the same.
    :return: The actor.
    """
    if site is SiteType.WORDPRESS:
        return Actor.AUTHOR
    if site is SiteType.DEV:
        key = (check_id, "" if check_id == "peri.jsonld.parses" else target)
        return Actor.PLATFORM if key in _DEV_PLATFORM else Actor.AUTHOR
    return Actor.UNKNOWN


class _Context:
    """What every check needs to build its findings.

    :param page: The parsed page.
    :param receipt: The receipt the page was read from.
    :param subject_url: The audited URL.
    :param site: The page's site type, for actors.
    :param new_id: The run's finding id source.
    """

    def __init__(
        self,
        page: ParsedPage,
        receipt: Receipt,
        subject_url: str,
        site: SiteType | None,
        new_id: NewId,
    ) -> None:
        self.page = page
        self.receipt = receipt
        self.subject_url = subject_url
        self.site = site
        self.new_id = new_id

    def evidence(
        self, location: str, observed: str | None, searched_for: str | None = None
    ) -> Evidence:
        """Record what was seen, or searched for, on this page.

        :param location: Where Cernis looked.
        :param observed: The value found, or ``None``.
        :param searched_for: What Cernis looked for, when nothing was found.
        :return: The evidence.
        """
        return Evidence(
            receipt_id=self.receipt.id,
            location=location,
            observed=observed,
            searched_for=searched_for,
        )

    def observed(
        self,
        check_id: str,
        summary: str,
        evidence: list[Evidence],
        *,
        target: str = "",
        defect: bool = False,
    ) -> Finding:
        """Build an OBSERVED finding.

        :param check_id: The check.
        :param summary: One sentence.
        :param evidence: What was seen or searched for.
        :param target: The finding's target.
        :param defect: Whether the table's defect condition holds.
        :return: The finding.
        """
        return Finding(
            id=self.new_id(),
            check_id=check_id,
            check_version=check(check_id).version,
            status=Status.OBSERVED,
            actor=actor_for(self.site, check_id, target),
            subject_url=self.subject_url,
            summary=summary,
            target=target,
            evidence=tuple(evidence),
            defect=defect,
        )


def _canonical_location(canonical: Canonical) -> str:
    """Name where a canonical link was.

    :param canonical: The canonical.
    :return: A location naming ``head`` or ``body``.
    """
    return f'{"head" if canonical.in_head else "body"} > link[rel="canonical"] href'


def _canonical_evidence(ctx: _Context) -> list[Evidence]:
    """Record each canonical link, or the search that found none.

    :param ctx: The check context.
    :return: One piece of evidence per canonical, or one search.
    """
    canonicals = ctx.page.canonicals
    if not canonicals:
        return [
            ctx.evidence(WHOLE_DOCUMENT, None, 'a <link> element whose rel includes "canonical"')
        ]
    return [
        ctx.evidence(_canonical_location(c), c.href)
        if c.href is not None
        else ctx.evidence(_canonical_location(c), None, "an href attribute")
        for c in canonicals
    ]


def canonical_present(ctx: _Context) -> list[Finding]:
    """``peri.canonical.present``: whether a canonical link exists. Never a defect.

    :param ctx: The check context.
    :return: One finding.
    """
    count = len(ctx.page.canonicals)
    if count == 0:
        summary = "The page declares no canonical link."
    elif count == 1:
        summary = "The page declares a canonical link."
    else:
        summary = f"The page declares {count} canonical links."
    return [ctx.observed("peri.canonical.present", summary, _canonical_evidence(ctx))]


def _resolved(ctx: _Context, href: str) -> str:
    """Resolve an ``href`` against the page's URL, as a browser would.

    :param ctx: The check context.
    :param href: The ``href`` as written.
    :return: The absolute URL, or ``href`` unchanged if it cannot be resolved.
    """
    base = ctx.receipt.final_url or ctx.receipt.requested_url
    try:
        return urljoin(base, href.strip())
    except ValueError:
        return href


def _canonicals_disagree(ctx: _Context) -> bool:
    """Tell whether two canonical hrefs name different URLs.

    :param ctx: The check context.
    :return: Whether any href, resolved against the page's URL, is DIFFERENT
        from the first.
    """
    hrefs = [_resolved(ctx, c.href) for c in ctx.page.canonicals if c.href is not None]
    return any(
        compare_urls(hrefs[0], other, redirects=(ctx.receipt,)).outcome is UrlMatch.DIFFERENT
        for other in hrefs[1:]
    )


def canonical_single(ctx: _Context) -> list[Finding]:
    """``peri.canonical.single``: how many canonicals, and their values.

    Defect when there is more than one and their values are not all IDENTICAL
    or EQUIVALENT. A canonical with no ``href`` has no value to compare.

    :param ctx: The check context.
    :return: One finding.
    """
    canonicals = ctx.page.canonicals
    hrefs = [c.href for c in canonicals if c.href is not None]
    defect = False
    if not canonicals:
        summary = "The page declares no canonical URL, so there is nothing to compare."
    elif len(canonicals) == 1:
        summary = (
            f"The page declares one canonical URL: {hrefs[0]}."
            if hrefs
            else "The page's one canonical link has no href."
        )
    elif not hrefs:
        summary = f"The page declares {len(canonicals)} canonical links, and none has an href."
    elif len(hrefs) == 1:
        summary = (
            f"The page declares {len(canonicals)} canonical links; only one has an href, "
            f"naming {hrefs[0]}."
        )
    elif _canonicals_disagree(ctx):
        defect = True
        summary = f"The page declares {len(canonicals)} canonical links that name different URLs."
    else:
        summary = f"The page declares {len(canonicals)} canonical links, all naming the same URL."
    return [ctx.observed("peri.canonical.single", summary, _canonical_evidence(ctx), defect=defect)]


def canonical_problem(href: str | None) -> str | None:
    """Say why a canonical href is not an absolute http(s) URL.

    :param href: The ``href`` as written, or ``None``.
    :return: ``"no href"``, ``"relative"``, ``"not http"``, or ``None`` if it
        is absolute.
    """
    if href is None:
        return "no href"
    if is_absolute_http_url(href):
        return None
    try:
        parts = urlsplit(href.strip())
    except ValueError:
        return "not http"
    return "relative" if not parts.scheme else "not http"


def canonical_absolute(ctx: _Context) -> list[Finding]:
    """``peri.canonical.absolute``: whether the canonical is an absolute URL.

    Defect when it is relative or malformed (no ``href``, not http(s), or
    not parseable). No finding when there is no canonical.

    :param ctx: The check context.
    :return: One finding, or none.
    """
    canonicals = ctx.page.canonicals
    if not canonicals:
        return []
    problems = [canonical_problem(c.href) for c in canonicals]
    bad = [p for p in problems if p is not None]
    if len(canonicals) == 1:
        href = canonicals[0].href
        summary = {
            None: "The canonical URL is absolute.",
            "no href": "The canonical link has no href.",
            "relative": f"The canonical URL {href!r} is relative.",
            "not http": f"The canonical URL {href!r} is not an absolute http or https URL.",
        }[problems[0]]
    elif not bad:
        summary = f"All {len(canonicals)} canonical URLs are absolute."
    else:
        verb = "is" if len(bad) == 1 else "are"
        summary = (
            f"Of {len(canonicals)} canonical links, {len(bad)} {verb} not an absolute "
            "http or https URL."
        )
    return [
        ctx.observed("peri.canonical.absolute", summary, _canonical_evidence(ctx), defect=bool(bad))
    ]


def _meta_location(tag: MetaTag) -> str:
    """Name where a ``meta`` element's content was.

    :param tag: The tag.
    :return: The location.
    """
    where = "head" if tag.in_head else "body"
    return f'{where} > meta[{tag.attribute}="{tag.key}"] content'


def _meta_evidence(ctx: _Context, tag: MetaTag) -> Evidence:
    """Record one ``meta`` element's content.

    :param ctx: The check context.
    :param tag: The tag.
    :return: The evidence; a missing ``content`` attribute is a search.
    """
    if tag.content is None:
        return ctx.evidence(_meta_location(tag), None, "a content attribute")
    return ctx.evidence(_meta_location(tag), tag.content)


def meta_description(ctx: _Context) -> list[Finding]:
    """``peri.meta.description``: presence, and length in characters. Never a defect.

    :param ctx: The check context.
    :return: One finding.
    """
    tags = [
        tag
        for tag in ctx.page.meta
        if tag.attribute == "name" and tag.key.strip().lower() == "description"
    ]
    if not tags:
        evidence = [ctx.evidence(WHOLE_DOCUMENT, None, 'a <meta name="description">')]
        return [
            ctx.observed("peri.meta.description", "The page has no meta description.", evidence)
        ]
    first = tags[0]
    if first.content is None:
        detail = "with no content attribute"
    else:
        detail = f"of {len(normalize_text(first.content))} characters"
    if len(tags) == 1:
        summary = f"The page has a meta description {detail}."
    else:
        first_is = detail.removeprefix("of ")
        summary = f"The page has {len(tags)} meta descriptions; the first is {first_is}."
    return [
        ctx.observed("peri.meta.description", summary, [_meta_evidence(ctx, tag) for tag in tags])
    ]


def uses_open_graph(page: ParsedPage) -> bool:
    """Tell whether a page declares any Open Graph property.

    :param page: The parsed page.
    :return: Whether any ``meta`` names a key starting ``og:``, in either
        ``property`` or ``name``.
    """
    return any(tag.key.strip().lower().startswith("og:") for tag in page.meta)


def og_missing(page: ParsedPage, prop: str) -> bool:
    """Tell whether an Open Graph property is missing: absent, or with no value.

    A property declared with ``name=`` and a value counts as present (most
    consumers read it), so it is reported, not called missing.

    :param page: The parsed page.
    :param prop: The property.
    :return: Whether no tag for it has a non-blank ``content``.
    """
    return not any(tag.content and tag.content.strip() for tag in page.og(prop))


def og_core(ctx: _Context) -> list[Finding]:
    """``peri.og.core``: presence of each core Open Graph property, one finding each.

    The property is the target. Defect when the page uses Open Graph (it
    declares at least one ``og:`` property) and a property the Open Graph
    protocol requires (``og:title``, ``og:type``, ``og:image``, ``og:url``)
    is missing: absent, empty, or with no ``content``. A page with no
    ``og:`` properties at all is a fact, never a defect. ``og:description``
    is optional and never a defect.

    :param ctx: The check context.
    :return: Five findings.
    """
    uses = uses_open_graph(ctx.page)
    findings: list[Finding] = []
    for prop in OG_CORE:
        tags = list(ctx.page.og(prop))
        standard = [tag for tag in tags if tag.attribute == "property"]
        if not tags:
            evidence = [ctx.evidence(WHOLE_DOCUMENT, None, f'a <meta property="{prop}">')]
            state = "is absent"
        else:
            evidence = [_meta_evidence(ctx, tag) for tag in tags]
            chosen = standard[0] if standard else tags[0]
            if not standard:
                state = "is declared with name= rather than property="
            elif chosen.content is None:
                state = "is present but has no content attribute"
            elif not chosen.content.strip():
                state = "is present but empty"
            elif len(standard) > 1:
                state = f"is declared {len(standard)} times"
            else:
                state = "is present"
        defect = uses and prop in OG_REQUIRED and og_missing(ctx.page, prop)
        summary = f"{prop} {state}."
        if defect:
            summary += (
                f" The page uses Open Graph, and {OPEN_GRAPH} requires {prop} on every page "
                "that does."
            )
        findings.append(ctx.observed("peri.og.core", summary, evidence, target=prop, defect=defect))
    return findings


def og_url_matches_canonical(ctx: _Context) -> list[Finding]:
    """``peri.og.url_matches_canonical``: the URL comparison outcome.

    Defect when DIFFERENT. A relative canonical is resolved against the
    page's URL first, as a browser would. When two canonicals disagree, which
    one ``og:url`` should match cannot be told: ``NOT_DETERMINABLE``
    (``AMBIGUOUS``).

    :param ctx: The check context.
    :return: One finding.
    """
    check_id = "peri.og.url_matches_canonical"
    og_tags = [tag for tag in ctx.page.og("og:url") if tag.content and tag.content.strip()]
    canonicals = [c for c in ctx.page.canonicals if c.href is not None and c.href.strip()]
    if not og_tags and not canonicals:
        evidence = [
            ctx.evidence(WHOLE_DOCUMENT, None, 'a <meta property="og:url">'),
            ctx.evidence(WHOLE_DOCUMENT, None, 'a <link rel="canonical"> with an href'),
        ]
        return [
            ctx.observed(
                check_id, "There is neither an og:url nor a canonical URL to compare.", evidence
            )
        ]
    if not og_tags:
        evidence = [ctx.evidence(WHOLE_DOCUMENT, None, 'a <meta property="og:url">')]
        return [
            ctx.observed(
                check_id, "There is no og:url to compare with the canonical URL.", evidence
            )
        ]
    if not canonicals:
        evidence = [ctx.evidence(WHOLE_DOCUMENT, None, 'a <link rel="canonical"> with an href')]
        return [
            ctx.observed(check_id, "There is no canonical URL to compare with og:url.", evidence)
        ]
    og_tag = og_tags[0]
    og_url = og_tag.content or ""
    evidence = [_meta_evidence(ctx, og_tag)] + [
        ctx.evidence(_canonical_location(c), c.href) for c in canonicals
    ]
    if _canonicals_disagree(ctx):
        return [
            Finding(
                id=ctx.new_id(),
                check_id=check_id,
                check_version=check(check_id).version,
                status=Status.NOT_DETERMINABLE,
                actor=actor_for(ctx.site, check_id),
                subject_url=ctx.subject_url,
                summary=(
                    "The page declares canonical URLs that name different URLs, so which one "
                    "og:url should match cannot be told."
                ),
                evidence=tuple(evidence),
                reason_code=ReasonCode.AMBIGUOUS,
                question="Whether og:url agrees with the canonical URL",
            )
        ]
    href = canonicals[0].href or ""
    relative = canonical_problem(href) == "relative"
    canonical = _resolved(ctx, href) if relative else href
    redirects = (ctx.receipt,)
    result = compare_urls(og_url, canonical, redirects=redirects)
    note = (
        " (the canonical is relative, so it was resolved against the page's URL first)"
        if relative
        else ""
    )
    if result.outcome is UrlMatch.IDENTICAL:
        summary = f"og:url and the canonical URL are identical{note}."
    elif result.outcome is UrlMatch.EQUIVALENT:
        reasons = ", ".join(result.reasons)
        if result.receipt_id is not None:
            reasons += f", receipt {result.receipt_id}"
        summary = f"og:url and the canonical URL are equivalent ({reasons}){note}."
    else:
        summary = f"og:url ({og_url}) and the canonical URL ({canonical}) are different{note}."
    return [ctx.observed(check_id, summary, evidence, defect=result.outcome is UrlMatch.DIFFERENT)]


def lang(ctx: _Context) -> list[Finding]:
    """``peri.lang``: the ``<html lang>`` value, or its absence.

    Defect when the attribute is missing or empty: WCAG 2 success criterion
    3.1.1 (Language of Page, Level A) requires the page's default language
    to be programmatically determinable. Whether a value is a valid
    language tag is not checked.

    :param ctx: The check context.
    :return: One finding.
    """
    value = ctx.page.lang
    if value is None:
        evidence = [ctx.evidence("<html>", None, "a lang attribute")]
        summary = (
            "The page does not declare a language (no lang attribute on <html>); "
            f"{WCAG_LANGUAGE} requires one."
        )
    elif not value.strip():
        evidence = [ctx.evidence("html lang", value)]
        summary = f"The page's lang attribute is empty; {WCAG_LANGUAGE} requires a language."
    else:
        evidence = [ctx.evidence("html lang", value)]
        summary = f"The page declares its language as {value!r}."
    defect = value is None or not value.strip()
    return [ctx.observed("peri.lang", summary, evidence, defect=defect)]


def jsonld_parses(ctx: _Context) -> list[Finding]:
    """``peri.jsonld.parses``: each JSON-LD block's ``@type``, one finding per block.

    Defect when a block fails to parse as JSON (an empty block included).

    :param ctx: The check context.
    :return: One finding per block, or one recording that there are none.
    """
    blocks = ctx.page.json_ld
    if not blocks:
        evidence = [ctx.evidence(WHOLE_DOCUMENT, None, '<script type="application/ld+json">')]
        return [ctx.observed("peri.jsonld.parses", "The page has no JSON-LD blocks.", evidence)]
    findings: list[Finding] = []
    for block in blocks:
        number = block.index + 1
        location = f'script[type="application/ld+json"] #{number}'
        if block.parsed:
            if not block.types:
                summary = f"JSON-LD block {number} parses and declares no @type."
            elif len(block.types) == 1:
                summary = f"JSON-LD block {number} parses; its @type is {block.types[0]}."
            else:
                summary = f"JSON-LD block {number} parses; its @types are {', '.join(block.types)}."
        else:
            summary = f"JSON-LD block {number} does not parse: {block.error}."
        findings.append(
            ctx.observed(
                "peri.jsonld.parses",
                summary,
                [ctx.evidence(location, block.raw)],
                target=f"block {number}",
                defect=not block.parsed,
            )
        )
    return findings


def title(ctx: _Context) -> list[Finding]:
    """``peri.title``: the ``<title>`` and its length. Never a defect.

    :param ctx: The check context.
    :return: One finding.
    """
    titles = ctx.page.titles
    if not titles:
        evidence = [ctx.evidence("head", None, "a <title> element")]
        return [ctx.observed("peri.title", "The page has no <title>.", evidence)]
    length = len(normalize_text(titles[0]))
    if len(titles) > 1:
        summary = f"The page has {len(titles)} titles; the first is {length} characters long."
    elif length == 0:
        summary = "The page's title is empty."
    else:
        summary = f"The page's title is {length} characters long."
    return [ctx.observed("peri.title", summary, [ctx.evidence("head > title", t) for t in titles])]


CHECK_FUNCTIONS: tuple[tuple[str, Callable[[_Context], list[Finding]]], ...] = (
    ("peri.canonical.present", canonical_present),
    ("peri.canonical.single", canonical_single),
    ("peri.canonical.absolute", canonical_absolute),
    ("peri.meta.description", meta_description),
    ("peri.og.core", og_core),
    ("peri.og.url_matches_canonical", og_url_matches_canonical),
    ("peri.lang", lang),
    ("peri.jsonld.parses", jsonld_parses),
    ("peri.title", title),
)
"""Every peritext check, in DESIGN.md order."""


def peritext_findings(
    page: ParsedPage,
    receipt: Receipt,
    *,
    subject_url: str,
    site: SiteType | None,
    new_id: NewId,
) -> list[Finding]:
    """Run every peritext check over a page Cernis read whole.

    :param page: The parsed page.
    :param receipt: The receipt it was read from (its redirect chain counts
        for URL comparison).
    :param subject_url: The audited URL.
    :param site: The page's site type, declared or detected, for actors.
    :param new_id: The run's finding id source.
    :return: The findings, in DESIGN.md order.
    """
    ctx = _Context(page, receipt, subject_url, site, new_id)
    findings: list[Finding] = []
    for _, run in CHECK_FUNCTIONS:
        findings.extend(run(ctx))
    return findings
