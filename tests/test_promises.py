"""Tests for the no-promise rule (DESIGN.md principle 3).

Recommendation text may say what to change and why, never what will happen as
a result. These tests make that rule a build failure.
"""

import importlib
import pkgutil
from collections.abc import Iterator

import pytest

import cernis
from cernis.checks.recommendations import TEMPLATES, RecommendationTemplate
from cernis.checks.registry import CHECKS
from cernis.promises import FORBIDDEN_PHRASES, find_outcome_language


def discover_templates() -> Iterator[RecommendationTemplate]:
    """Yield every RecommendationTemplate defined at module level in the package."""
    for info in pkgutil.walk_packages(cernis.__path__, prefix="cernis."):
        if info.name == "cernis.__main__":
            continue
        module = importlib.import_module(info.name)
        for value in vars(module).values():
            if isinstance(value, RecommendationTemplate):
                yield value
            elif isinstance(value, tuple | list):
                yield from (v for v in value if isinstance(v, RecommendationTemplate))
            elif isinstance(value, dict):
                yield from (v for v in value.values() if isinstance(v, RecommendationTemplate))


def test_checker_catches_ranking_promise() -> None:
    """The checker flags the canonical example of a forbidden promise."""
    assert find_outcome_language("this will improve rankings") != ()


@pytest.mark.parametrize(
    "text",
    [
        "This Will Increase AI citations.",
        "Adding a description could boost click-through.",
        "It'll improve how the page ranks.",
        "It\u2019ll improve how the page ranks.",
        "Expect more traffic from search.",
        "The post would rank higher.",
        "It will significantly increase citations.",
        "This will very likely raise its position.",
        "This change\nwill   help readers find it.",
    ],
)
def test_checker_catches_outcome_language(text: str) -> None:
    """Outcome language is caught regardless of case, spacing, or contraction."""
    assert find_outcome_language(text) != ()


@pytest.mark.parametrize(
    "text",
    [
        "Set canonical_url in the DEV front matter to the original URL.",
        'Remove the second <link rel="canonical"> element.',
        "The HTML standard expects one canonical link per page.",
    ],
)
def test_checker_passes_action_language(text: str) -> None:
    """Plain actions and citations of a standard pass."""
    assert find_outcome_language(text) == ()


def test_every_phrase_is_caught_by_itself() -> None:
    """Each phrase in the list matches when it appears in a sentence."""
    for phrase in FORBIDDEN_PHRASES:
        assert find_outcome_language(f"Doing so {phrase} it.") != (), phrase


def test_package_has_at_least_one_template() -> None:
    """The template scan has something to scan, so it cannot pass vacuously."""
    assert len(TEMPLATES) >= 1


def test_every_template_is_registered() -> None:
    """Templates live in TEMPLATES, so the no-promise scan sees all of them."""
    for template in discover_templates():
        assert template in TEMPLATES, template.id


def test_no_template_contains_outcome_language() -> None:
    """No recommendation template in the package predicts an outcome."""
    for template in discover_templates():
        for text in (template.action, template.rationale):
            assert find_outcome_language(text) == (), f"{template.id}: {text!r}"


def test_template_ids_are_unique_and_checks_exist() -> None:
    """Template ids are unique and each names a registered check."""
    check_ids = {check.id for check in CHECKS}
    template_ids = [template.id for template in TEMPLATES]
    assert len(template_ids) == len(set(template_ids))
    for template in TEMPLATES:
        assert template.check_id in check_ids, template.id
