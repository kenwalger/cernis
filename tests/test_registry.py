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
    for spec in CHECKS:
        assert spec.id.startswith(PREFIXES[spec.family]), spec.id


def test_registry_lists_every_check_in_the_design() -> None:
    """The registry holds exactly the checks planned in DESIGN.md section 4."""
    assert {check.id for check in CHECKS} == DESIGN_CHECK_IDS


def test_peritext_checks_are_implemented_and_epitext_checks_are_not_yet() -> None:
    """Session 4b implements the nine peritext checks; epitext checks are Phase 4."""
    for spec in CHECKS:
        assert spec.version == "1", spec.id
        assert spec.implemented is (spec.family is Family.PERITEXT), spec.id


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
