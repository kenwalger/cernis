"""Recommendation templates.

Every template the package uses is registered in :data:`TEMPLATES`. The test
suite scans the whole package for templates, fails on any that is not
registered, and runs the no-promise checker (:mod:`cernis.promises`) over
every one.

Templates use :meth:`str.format` placeholders. Values filled in from a page
are not checked for outcome language, since an article may say anything; the
template text around them is. Only template text is ever used as a format
string; page content is passed as an argument, never formatted itself.

A defect whose actor is ``UNKNOWN`` is one Cernis cannot tell the author
controls, so its recommendation must not assume they do (Session 7). Each
template such a defect can reach has a conditional wording, registered here
as its own template with ``variant_of`` naming the base: "If you control X,
change it; if a theme or platform writes it, the change is theirs to make."
:func:`template_for` chooses it. A wording for one site type (DEV, where the
condition can name the front matter) is chosen over the wording for any site.
"""

from dataclasses import dataclass

from cernis.model import Actor
from cernis.parse.extractors import SiteType


@dataclass(frozen=True, kw_only=True)
class RecommendationTemplate:
    """The text of one kind of recommendation.

    :param id: Template id, unique across the package.
    :param check_id: The registered check whose findings it is based on.
    :param action: What to change, phrased as an action.
    :param rationale: Why, citing a published standard or the author's
        stated intent. Never what will happen as a result.
    :param variant_of: Empty for a base template. For a conditional wording,
        the id of the base template it replaces when the defect's actor is
        ``UNKNOWN``; the recommendation keeps the base id in its target, so
        its key does not change with the wording.
    :param site_type: For a conditional wording, the site type it is for, or
        ``None`` for any site.
    """

    id: str
    check_id: str
    action: str
    rationale: str
    variant_of: str = ""
    site_type: SiteType | None = None


TEMPLATES: tuple[RecommendationTemplate, ...] = (
    RecommendationTemplate(
        id="peri.canonical.single.keep-one",
        check_id="peri.canonical.single",
        action=(
            "Remove the extra canonical links so that the page declares one canonical URL, "
            "the page's preferred URL."
        ),
        rationale=(
            "The page declares {count} canonical links that name different URLs ({urls}). "
            "RFC 6596 defines the canonical link relation as naming one preferred URL for "
            "a page; links that disagree leave that URL undeclared."
        ),
    ),
    RecommendationTemplate(
        id="peri.canonical.absolute.make-absolute",
        check_id="peri.canonical.absolute",
        action="Change the canonical URL {href} to an absolute URL, such as {resolved}.",
        rationale=(
            "A relative canonical URL is resolved against the URL the page is served from, "
            "so it names a different URL wherever the page is served or copied; an "
            "absolute URL names one page wherever it appears."
        ),
    ),
    RecommendationTemplate(
        id="peri.canonical.absolute.add-href",
        check_id="peri.canonical.absolute",
        action=(
            "Give the canonical link an href naming the page's preferred URL as an "
            "absolute URL, or remove the link."
        ),
        rationale=(
            "A canonical link with no href declares no URL; RFC 6596 defines the link's "
            "target as the preferred URL."
        ),
    ),
    RecommendationTemplate(
        id="peri.canonical.absolute.fix-url",
        check_id="peri.canonical.absolute",
        action="Replace the canonical URL {href} with an absolute http or https URL.",
        rationale=(
            "The canonical link names the page's preferred URL, and {href} is not an "
            "absolute http or https URL."
        ),
    ),
    RecommendationTemplate(
        id="peri.og.core.add-required",
        check_id="peri.og.core",
        action=(
            'Add {prop} to the page\'s <head> as <meta property="{prop}" content="...">, '
            "giving the page's {meaning}."
        ),
        rationale=(
            "The Open Graph protocol (ogp.me) requires og:title, og:type, og:image, and "
            "og:url on every page that uses it; this page declares og: properties, but "
            "{prop} {state}."
        ),
    ),
    RecommendationTemplate(
        id="peri.lang.add-lang",
        check_id="peri.lang",
        action=(
            "Add a lang attribute to the <html> element declaring the page's language, "
            'such as lang="en".'
        ),
        rationale=(
            "WCAG 2 success criterion 3.1.1 (Language of Page, Level A) requires a page's "
            "default human language to be programmatically determinable, and this page's "
            "<html> element {state}."
        ),
    ),
    RecommendationTemplate(
        id="peri.og.url_matches_canonical.align",
        check_id="peri.og.url_matches_canonical",
        action=("Set og:url and the canonical link to the same URL: the page's preferred URL."),
        rationale=(
            "The Open Graph protocol defines og:url as the canonical URL of the object; "
            "here og:url is {og_url} and the canonical URL is {canonical}."
        ),
    ),
    RecommendationTemplate(
        id="peri.jsonld.parses.fix-json",
        check_id="peri.jsonld.parses",
        action="Correct JSON-LD block {number} so that it is valid JSON.",
        rationale=(
            "JSON-LD (W3C JSON-LD 1.1) is a JSON format, and block {number} is not valid "
            "JSON: {error}."
        ),
    ),
    RecommendationTemplate(
        id="epi.pair.canonical.set-copy-canonical",
        check_id="epi.pair.canonical",
        action="Set the copy's canonical URL to {original_url}.",
        rationale=(
            "You declared {original_url} as the original; the copy's canonical "
            "points at {copy_canonical}, which contradicts that pairing."
        ),
    ),
    RecommendationTemplate(
        id="epi.pair.canonical.set-dev-canonical-url",
        check_id="epi.pair.canonical",
        action="Set canonical_url in the copy's DEV front matter to {original_url}.",
        rationale=(
            "You declared {original_url} as the original; the copy's canonical "
            "{copy_state}, which contradicts that pairing. On DEV, the copy's canonical "
            "link comes from canonical_url in its front matter."
        ),
    ),
    RecommendationTemplate(
        id="epi.pair.canonical.add-copy-canonical",
        check_id="epi.pair.canonical",
        action="Add a canonical link to the copy naming the original, {original_url}.",
        rationale=(
            "You declared {original_url} as the original, and the copy declares no "
            "canonical URL, so nothing on the copy names its original (RFC 6596)."
        ),
    ),
    RecommendationTemplate(
        id="epi.pair.canonical.set-original-canonical",
        check_id="epi.pair.canonical",
        action="Set the original's canonical URL to its own URL, {original_url}.",
        rationale=(
            "You declared {original_url} as the original, and its canonical names "
            "{original_canonical}, a different URL, which contradicts that pairing."
        ),
    ),
    RecommendationTemplate(
        id="epi.canonical.resolves.fix-canonical",
        check_id="epi.canonical.resolves",
        action="Change the canonical URL {url} to the URL of a page that exists.",
        rationale=(
            "A canonical URL names the preferred URL for the page (RFC 6596), and {url} "
            "answers {status}, so it names no page."
        ),
    ),
    RecommendationTemplate(
        id="epi.og.image.resolves.fix-image",
        check_id="epi.og.image.resolves",
        action="Set og:image to the URL of an image that exists.",
        rationale=(
            "The Open Graph protocol defines og:image as an image URL representing the "
            "object, and {url} {problem}."
        ),
    ),
    RecommendationTemplate(
        id="epi.links.resolve.fix-link",
        check_id="epi.links.resolve",
        action="Update or remove the article's link to {url}.",
        rationale=(
            "The link names {url}, which answers {status}: HTTP defines 404 as no "
            "current representation of the resource and 410 as gone (RFC 9110)."
        ),
    ),
    RecommendationTemplate(
        id="epi.sitemap.listed.add-page",
        check_id="epi.sitemap.listed",
        action="Add {url} to the site's sitemap.",
        rationale=(
            "The sitemaps protocol (sitemaps.org) lists the URLs on a site that are "
            "available for crawling, and the site's sitemap lists {count} other pages "
            "under {section} but not {url}."
        ),
    ),
    # Conditional wordings, for a defect whose actor is UNKNOWN (Session 7).
    # Each keeps its base template's rationale, which cites the standard and
    # assumes nothing about who controls the page.
    RecommendationTemplate(
        id="peri.canonical.single.keep-one.if-unknown",
        check_id="peri.canonical.single",
        variant_of="peri.canonical.single.keep-one",
        action=(
            "If you control the page's canonical links, remove the extra ones so that the "
            "page declares one canonical URL, the page's preferred URL; if a theme, plugin, "
            "or platform writes them, the change is theirs to make."
        ),
        rationale=(
            "The page declares {count} canonical links that name different URLs ({urls}). "
            "RFC 6596 defines the canonical link relation as naming one preferred URL for "
            "a page; links that disagree leave that URL undeclared."
        ),
    ),
    RecommendationTemplate(
        id="peri.canonical.absolute.make-absolute.if-unknown",
        check_id="peri.canonical.absolute",
        variant_of="peri.canonical.absolute.make-absolute",
        action=(
            "If you control the page's canonical link, change {href} to an absolute URL, "
            "such as {resolved}; if a theme, plugin, or platform writes it, the change is "
            "theirs to make."
        ),
        rationale=(
            "A relative canonical URL is resolved against the URL the page is served from, "
            "so it names a different URL wherever the page is served or copied; an "
            "absolute URL names one page wherever it appears."
        ),
    ),
    RecommendationTemplate(
        id="peri.canonical.absolute.add-href.if-unknown",
        check_id="peri.canonical.absolute",
        variant_of="peri.canonical.absolute.add-href",
        action=(
            "If you control the page's canonical link, give it an href naming the page's "
            "preferred URL as an absolute URL, or remove it; if a theme, plugin, or "
            "platform writes it, the change is theirs to make."
        ),
        rationale=(
            "A canonical link with no href declares no URL; RFC 6596 defines the link's "
            "target as the preferred URL."
        ),
    ),
    RecommendationTemplate(
        id="peri.canonical.absolute.fix-url.if-unknown",
        check_id="peri.canonical.absolute",
        variant_of="peri.canonical.absolute.fix-url",
        action=(
            "If you control the page's canonical link, replace {href} with an absolute "
            "http or https URL; if a theme, plugin, or platform writes it, the change is "
            "theirs to make."
        ),
        rationale=(
            "The canonical link names the page's preferred URL, and {href} is not an "
            "absolute http or https URL."
        ),
    ),
    RecommendationTemplate(
        id="peri.og.core.add-required.if-unknown",
        check_id="peri.og.core",
        variant_of="peri.og.core.add-required",
        action=(
            "If you control the page's Open Graph tags, add {prop} to its <head> as "
            '<meta property="{prop}" content="...">, giving the page\'s {meaning}; if a '
            "theme, plugin, or platform writes them, the change is theirs to make."
        ),
        rationale=(
            "The Open Graph protocol (ogp.me) requires og:title, og:type, og:image, and "
            "og:url on every page that uses it; this page declares og: properties, but "
            "{prop} {state}."
        ),
    ),
    RecommendationTemplate(
        id="peri.og.core.add-required.if-unknown-dev",
        check_id="peri.og.core",
        variant_of="peri.og.core.add-required",
        site_type=SiteType.DEV,
        action=(
            "If the post has a cover image, check cover_image in its DEV front matter, "
            "which DEV uses for {prop}; if DEV generates {prop} for the post, only DEV can "
            "change it."
        ),
        rationale=(
            "The Open Graph protocol (ogp.me) requires og:title, og:type, og:image, and "
            "og:url on every page that uses it; this page declares og: properties, but "
            "{prop} {state}. On DEV, og:image is the post's cover image when one is set, "
            "and otherwise an image DEV generates; the page does not say which."
        ),
    ),
    RecommendationTemplate(
        id="peri.lang.add-lang.if-unknown",
        check_id="peri.lang",
        variant_of="peri.lang.add-lang",
        action=(
            "If you control the page's <html> element, add a lang attribute declaring the "
            'page\'s language, such as lang="en"; if a theme, plugin, or platform writes '
            "it, the change is theirs to make."
        ),
        rationale=(
            "WCAG 2 success criterion 3.1.1 (Language of Page, Level A) requires a page's "
            "default human language to be programmatically determinable, and this page's "
            "<html> element {state}."
        ),
    ),
    RecommendationTemplate(
        id="peri.og.url_matches_canonical.align.if-unknown",
        check_id="peri.og.url_matches_canonical",
        variant_of="peri.og.url_matches_canonical.align",
        action=(
            "If you control both og:url and the canonical link, set them to the same URL: "
            "the page's preferred URL; if a theme, plugin, or platform writes either, the "
            "change is theirs to make."
        ),
        rationale=(
            "The Open Graph protocol defines og:url as the canonical URL of the object; "
            "here og:url is {og_url} and the canonical URL is {canonical}."
        ),
    ),
    RecommendationTemplate(
        id="peri.jsonld.parses.fix-json.if-unknown",
        check_id="peri.jsonld.parses",
        variant_of="peri.jsonld.parses.fix-json",
        action=(
            "If you control JSON-LD block {number}, correct it so that it is valid JSON; "
            "if a theme, plugin, or platform generates it, the change is theirs to make."
        ),
        rationale=(
            "JSON-LD (W3C JSON-LD 1.1) is a JSON format, and block {number} is not valid "
            "JSON: {error}."
        ),
    ),
    RecommendationTemplate(
        id="peri.jsonld.parses.fix-json.if-unknown-dev",
        check_id="peri.jsonld.parses",
        variant_of="peri.jsonld.parses.fix-json",
        site_type=SiteType.DEV,
        action=(
            "If the text that breaks JSON-LD block {number} comes from the post's DEV front "
            "matter, such as its title, correct it there; if DEV generates it, only DEV "
            "can correct it."
        ),
        rationale=(
            "JSON-LD (W3C JSON-LD 1.1) is a JSON format, and block {number} is not valid "
            "JSON: {error}. On DEV, the JSON-LD mixes the post's title and the author's "
            "name with DEV's own dates and publisher."
        ),
    ),
    RecommendationTemplate(
        id="epi.canonical.resolves.fix-canonical.if-unknown",
        check_id="epi.canonical.resolves",
        variant_of="epi.canonical.resolves.fix-canonical",
        action=(
            "If you control the page's canonical link, change {url} to the URL of a page "
            "that exists; if a theme, plugin, or platform writes it, the change is theirs "
            "to make."
        ),
        rationale=(
            "A canonical URL names the preferred URL for the page (RFC 6596), and {url} "
            "answers {status}, so it names no page."
        ),
    ),
    RecommendationTemplate(
        id="epi.og.image.resolves.fix-image.if-unknown",
        check_id="epi.og.image.resolves",
        variant_of="epi.og.image.resolves.fix-image",
        action=(
            "If you chose the page's og:image, set it to the URL of an image that exists; "
            "if a theme, plugin, or platform chooses it, the change is theirs to make."
        ),
        rationale=(
            "The Open Graph protocol defines og:image as an image URL representing the "
            "object, and {url} {problem}."
        ),
    ),
    RecommendationTemplate(
        id="epi.og.image.resolves.fix-image.if-unknown-dev",
        check_id="epi.og.image.resolves",
        variant_of="epi.og.image.resolves.fix-image",
        site_type=SiteType.DEV,
        action=(
            "If this image is the post's cover image, replace cover_image in its DEV front "
            "matter with the URL of an image that exists; if DEV generated it, only DEV "
            "can change it."
        ),
        rationale=(
            "The Open Graph protocol defines og:image as an image URL representing the "
            "object, and {url} {problem}. On DEV, og:image is the post's cover image when "
            "one is set, and otherwise an image DEV generates; the page does not say which."
        ),
    ),
    RecommendationTemplate(
        id="epi.links.resolve.fix-link.if-unknown",
        check_id="epi.links.resolve",
        variant_of="epi.links.resolve.fix-link",
        action=(
            "If you control the article's text, update or remove its link to {url}; if a "
            "theme, plugin, or platform adds the link, the change is theirs to make."
        ),
        rationale=(
            "The link names {url}, which answers {status}: HTTP defines 404 as no "
            "current representation of the resource and 410 as gone (RFC 9110)."
        ),
    ),
    RecommendationTemplate(
        id="epi.sitemap.listed.add-page.if-unknown",
        check_id="epi.sitemap.listed",
        variant_of="epi.sitemap.listed.add-page",
        action=(
            "If you control the site's sitemap, add {url} to it; if a plugin or platform "
            "generates the sitemap, the change is theirs to make."
        ),
        rationale=(
            "The sitemaps protocol (sitemaps.org) lists the URLs on a site that are "
            "available for crawling, and the site's sitemap lists {count} other pages "
            "under {section} but not {url}."
        ),
    ),
)
"""Every recommendation template in the package."""


TEMPLATES_BY_ID: dict[str, RecommendationTemplate] = {t.id: t for t in TEMPLATES}
"""TEMPLATES, by id."""


_UNKNOWN_WORDINGS: dict[tuple[str, SiteType | None], RecommendationTemplate] = {
    (t.variant_of, t.site_type): t for t in TEMPLATES if t.variant_of
}


def template_for(template_id: str, actor: Actor, site: SiteType | None) -> RecommendationTemplate:
    """Choose the wording of a recommendation for a defect's actor and site.

    :param template_id: The base template.
    :param actor: The actor of the defect the recommendation rests on.
    :param site: The page's site type.
    :return: The base template, unless the actor is ``UNKNOWN``; then its
        conditional wording for the site type, else for any site.
    :raises KeyError: When an ``UNKNOWN`` defect reaches a template with no
        conditional wording, so an unconditional instruction is never given
        for something the author may not control. The test suite renders
        every reachable template, so this is a programming error.
    """
    if actor is not Actor.UNKNOWN:
        return TEMPLATES_BY_ID[template_id]
    wording = _UNKNOWN_WORDINGS.get((template_id, site)) or _UNKNOWN_WORDINGS.get(
        (template_id, None)
    )
    if wording is None:
        raise KeyError(f"{template_id} has no conditional wording for an UNKNOWN defect")
    return wording
