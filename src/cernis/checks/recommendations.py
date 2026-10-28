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
