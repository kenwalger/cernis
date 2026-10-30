"""Recommendation templates.

Every template the package uses is registered in :data:`TEMPLATES`. The test
suite scans the whole package for templates, fails on any that is not
registered, and runs the no-promise checker (:mod:`cernis.promises`) over
every one.

Templates use :meth:`str.format` placeholders. Values filled in from a page
are not checked for outcome language, since an article may say anything; the
template text around them is. Only template text is ever used as a format
string; page content is passed as an argument, never formatted itself.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class RecommendationTemplate:
    """The text of one kind of recommendation.

    :param id: Template id, unique across the package.
    :param check_id: The registered check whose findings it is based on.
    :param action: What to change, phrased as an action.
    :param rationale: Why, citing a published standard or the author's
        stated intent. Never what will happen as a result.
    """

    id: str
    check_id: str
    action: str
    rationale: str


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
)
"""Every recommendation template in the package."""


TEMPLATES_BY_ID: dict[str, RecommendationTemplate] = {t.id: t for t in TEMPLATES}
"""TEMPLATES, by id."""
