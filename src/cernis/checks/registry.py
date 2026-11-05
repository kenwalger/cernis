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


def _peri(id: str, description: str, version: str = "1") -> CheckSpec:
    """Register a peritext check (implemented in Session 4b).

    :param id: The check id.
    :param description: The one-line description.
    :param version: The check's version.
    :return: The check spec.
    """
    return CheckSpec(
        id=id, version=version, family=Family.PERITEXT, description=description, implemented=True
    )


def _epi(id: str, description: str, implemented: bool = False, version: str = "1") -> CheckSpec:
    """Register an epitext check.

    :param id: The check id.
    :param description: The one-line description.
    :param implemented: Whether it can run yet (Sessions 5a and 5b implement them).
    :param version: The check's version.
    :return: The check spec.
    """
    return CheckSpec(
        id=id,
        version=version,
        family=Family.EPITEXT,
        description=description,
        implemented=implemented,
    )


CHECKS: tuple[CheckSpec, ...] = (
    _peri("peri.canonical.present", 'A <link rel="canonical"> exists on the page.'),
    _peri("peri.canonical.single", "The page declares exactly one canonical URL."),
    _peri("peri.canonical.absolute", "The canonical URL is absolute and well formed."),
    _peri("peri.meta.description", "A meta description exists; its length is reported."),
    # Version 2 (Session 4d): reports og:type; a missing required property is a
    # defect on a page that uses Open Graph. Version 3 (Session 6e): actors from
    # head_fields.toml, so og:image on DEV is UNKNOWN (was AUTHOR).
    _peri(
        "peri.og.core",
        "og:title, og:type, og:description, og:image, and og:url are present.",
        version="3",
    ),
    # Version 2 (Session 5a): a DIFFERENT defect cites the Open Graph protocol.
    _peri("peri.og.url_matches_canonical", "og:url agrees with the canonical URL.", version="2"),
    # Version 2 (Session 4d): a missing or empty lang is a defect (WCAG 2 SC 3.1.1).
    _peri("peri.lang", "The <html> element sets a lang attribute.", version="2"),
    # Version 2 (Session 6e) of the next three: actors from head_fields.toml. On
    # DEV, json-ld and title are UNKNOWN (were PLATFORM), and a robots directive
    # under a crawler's name makes peri.robots.directives UNKNOWN.
    _peri(
        "peri.jsonld.parses",
        "JSON-LD blocks parse as JSON; their @type is reported.",
        version="2",
    ),
    _peri("peri.title", "The <title> and its length are reported.", version="2"),
    _peri(
        "peri.robots.directives",
        "Robots meta tags and the X-Robots-Tag header, reported as facts.",
        version="2",
    ),
    _epi(
        "epi.pair.canonical",
        "A copy's canonical points at its original; the original's, at itself.",
        implemented=True,
    ),
    _epi(
        "epi.canonical.resolves",
        "Each canonical URL's status and redirect chain; a defect only for 404 or 410.",
        implemented=True,
    ),
    _epi(
        "epi.og.image.resolves",
        "The og:image URL's status and content type; a defect for 404, 410, or not an image.",
        implemented=True,
        # Version 2 (Session 6e): the actor is og:image's control (UNKNOWN on DEV, was PLATFORM).
        version="2",
    ),
    _epi(
        "epi.og.image.shared",
        "Audited articles on one site that share an og:image URL; a site fact, never a defect.",
        implemented=True,
        # Version 2 (Session 6e): the actor is og:image's control (UNKNOWN on DEV, was PLATFORM).
        version="2",
    ),
    _epi(
        "epi.robots.access",
        "What robots.txt says for this URL, for * and each AI crawler; never a defect.",
        implemented=True,
    ),
    _epi(
        "epi.sitemap.listed",
        "Whether the site's sitemap lists the URL; a defect only if it lists others nearby.",
        implemented=True,
    ),
    _epi(
        "epi.links.resolve",
        "Each article-body link's status; a defect only for 404 or 410.",
        implemented=True,
    ),
)
"""Every registered check, peritext first, in DESIGN.md order."""


SITE_LEVEL: frozenset[str] = frozenset({"epi.og.image.shared"})
"""Checks whose findings are about a set of audited articles, not one page.

Reports show them in their own "Site" section. Each finding still names one
subject (the first article of the set, in run order) so its key is stable."""

_BY_ID = {spec.id: spec for spec in CHECKS}


def check(check_id: str) -> CheckSpec:
    """Look up a registered check.

    :param check_id: The check id.
    :return: Its spec.
    :raises KeyError: If no check has that id.
    """
    try:
        return _BY_ID[check_id]
    except KeyError:
        raise KeyError(f"no registered check {check_id!r}") from None
