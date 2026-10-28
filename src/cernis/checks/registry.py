"""The registry of every check Cernis runs or plans to run (DESIGN.md section 4).

A check's id and version travel with every finding it produces, so a change
to a check shows up as a ``CHECKER`` change rather than a change to the page.
Bump ``version`` whenever a check's behavior changes.
"""

from dataclasses import dataclass

from cernis.model import Family


@dataclass(frozen=True, kw_only=True)
class CheckSpec:
    """The registered identity of one check.

    :param id: Dotted id, prefixed ``peri.`` or ``epi.`` to match the family.
    :param version: The check's version, recorded on every finding.
    :param family: Peritext (on the page) or epitext (around it).
    :param description: What the check looks at, in one line.
    :param implemented: Whether the check can run yet.
    """

    id: str
    version: str
    family: Family
    description: str
    implemented: bool


def _peri(id: str, description: str) -> CheckSpec:
    """Register a planned peritext check at version 1.

    :param id: The check id.
    :param description: The one-line description.
    :return: The check spec.
    """
    return CheckSpec(
        id=id, version="1", family=Family.PERITEXT, description=description, implemented=False
    )


def _epi(id: str, description: str) -> CheckSpec:
    """Register a planned epitext check at version 1.

    :param id: The check id.
    :param description: The one-line description.
    :return: The check spec.
    """
    return CheckSpec(
        id=id, version="1", family=Family.EPITEXT, description=description, implemented=False
    )


CHECKS: tuple[CheckSpec, ...] = (
    _peri("peri.canonical.present", 'A <link rel="canonical"> exists on the page.'),
    _peri("peri.canonical.single", "The page declares exactly one canonical URL."),
    _peri("peri.canonical.absolute", "The canonical URL is absolute and well formed."),
    _peri("peri.meta.description", "A meta description exists; its length is reported."),
    _peri("peri.og.core", "og:title, og:description, og:image, and og:url are present."),
    _peri("peri.og.url_matches_canonical", "og:url agrees with the canonical URL."),
    _peri("peri.lang", "The <html> element sets a lang attribute."),
    _peri("peri.jsonld.parses", "JSON-LD blocks parse as JSON; their @type is reported."),
    _peri("peri.title", "The <title> and its length are reported."),
    _epi(
        "epi.pair.canonical",
        "A copy's canonical points at its original; the original's, at itself.",
    ),
    _epi("epi.canonical.resolves", "The canonical URL returns 200 without a redirect chain."),
    _epi("epi.og.image.resolves", "The og:image URL returns an image."),
    _epi("epi.robots.access", "What robots.txt allows for this URL, for general and AI crawlers."),
    _epi("epi.sitemap.listed", "The URL appears in the site's sitemap."),
    _epi("epi.links.resolve", "Links in the article body resolve."),
)
"""Every registered check, peritext first, in DESIGN.md order."""
