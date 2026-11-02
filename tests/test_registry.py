"""Tests for the check registry in :mod:`cernis.checks.registry`."""

import pytest

from cernis.checks.registry import CHECKS, check
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
    "peri.robots.directives",
    "epi.pair.canonical",
    "epi.canonical.resolves",
    "epi.og.image.resolves",
    "epi.og.image.shared",
    "epi.robots.access",
    "epi.sitemap.listed",
    "epi.links.resolve",
}

PREFIXES = {Family.PERITEXT: "peri.", Family.EPITEXT: "epi."}
EPITEXT_IMPLEMENTED = {
    "epi.pair.canonical",
    "epi.canonical.resolves",
    "epi.og.image.resolves",
    "epi.og.image.shared",
    "epi.robots.access",
    "epi.sitemap.listed",
    "epi.links.resolve",
}


def test_check_ids_are_unique() -> None:
    """No two checks share an id."""
    ids = [check.id for check in CHECKS]
    assert len(ids) == len(set(ids))


def test_check_ids_match_their_family() -> None:
    """Every id starts with the prefix of its family."""
    for spec in CHECKS:
        assert spec.id.startswith(PREFIXES[spec.family]), spec.id


def test_registry_lists_every_check_in_the_design() -> None:
    """The registry holds exactly the checks planned in DESIGN.md section 4."""
    assert {check.id for check in CHECKS} == DESIGN_CHECK_IDS


def test_every_check_is_implemented() -> None:
    """The ten peritext checks (Sessions 4b and 5b) and six epitext checks (5a and 5b) run.

    Session 4d bumped peri.lang and peri.og.core to version 2, and Session 5a
    peri.og.url_matches_canonical; every other check is still at version 1.
    """
    bumped = {"peri.lang", "peri.og.core", "peri.og.url_matches_canonical"}
    for spec in CHECKS:
        assert spec.version == ("2" if spec.id in bumped else "1"), spec.id
        implemented = spec.family is Family.PERITEXT or spec.id in EPITEXT_IMPLEMENTED
        assert spec.implemented is implemented, spec.id


def test_check_looks_up_by_id() -> None:
    """check() returns the registered spec, and refuses an unknown id."""
    assert check("peri.title").id == "peri.title"
    with pytest.raises(KeyError):
        check("peri.nonexistent")


def test_descriptions_are_one_line() -> None:
    """Every check has a non-blank, single-line description."""
    for spec in CHECKS:
        assert spec.description.strip(), spec.id
        assert "\n" not in spec.description, spec.id
