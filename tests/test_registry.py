"""Tests for the check registry in :mod:`cernis.checks.registry`."""

from cernis.checks.registry import CHECKS
from cernis.model import Family

DESIGN_CHECK_IDS = {
    "peri.canonical.present",
    "peri.canonical.single",
    "peri.canonical.absolute",
    "peri.meta.description",
    "peri.og.core",
    "peri.og.url_matches_canonical",
    "peri.lang",
    "peri.jsonld.parses",
    "peri.title",
    "epi.pair.canonical",
    "epi.canonical.resolves",
    "epi.og.image.resolves",
    "epi.robots.access",
    "epi.sitemap.listed",
    "epi.links.resolve",
}

PREFIXES = {Family.PERITEXT: "peri.", Family.EPITEXT: "epi."}


def test_check_ids_are_unique() -> None:
    """No two checks share an id."""
    ids = [check.id for check in CHECKS]
    assert len(ids) == len(set(ids))


def test_check_ids_match_their_family() -> None:
    """Every id starts with the prefix of its family."""
    for check in CHECKS:
        assert check.id.startswith(PREFIXES[check.family]), check.id


def test_registry_lists_every_check_in_the_design() -> None:
    """The registry holds exactly the checks planned in DESIGN.md section 4."""
    assert {check.id for check in CHECKS} == DESIGN_CHECK_IDS


def test_planned_checks_are_version_one_and_unimplemented() -> None:
    """Session 1 registers checks without implementing any of them."""
    for check in CHECKS:
        assert check.version == "1", check.id
        assert check.implemented is False, check.id


def test_descriptions_are_one_line() -> None:
    """Every check has a non-blank, single-line description."""
    for check in CHECKS:
        assert check.description.strip(), check.id
        assert "\n" not in check.description, check.id
