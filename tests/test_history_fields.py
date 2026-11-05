"""Tests for the head field control file (DESIGN.md section 5, decision 2)."""

import pytest

from cernis.history.fields import (
    HISTORY_VERSION,
    HeadFieldsError,
    classifier_version,
    head_field_control,
    load_head_fields,
    site_of,
)
from cernis.model import Actor, ExtractorSelection


def test_the_shipped_file_loads_with_a_version() -> None:
    """The file in cernis/data parses, and its version is a positive integer."""
    control = head_field_control()

    assert control.version >= 1
    assert set(control.sites) == {"dev", "wordpress", "owned", "generic"}


def test_the_classifier_version_names_the_history_code_and_the_file() -> None:
    """A change to either is a CHECKER change."""
    assert classifier_version() == f"{HISTORY_VERSION}+h{head_field_control().version}"


@pytest.mark.parametrize("site", ["wordpress", "owned"])
def test_every_field_is_the_authors_on_wordpress_and_owned_pages(site: str) -> None:
    """Including fields nobody listed."""
    control = head_field_control()

    for name in ("title", "meta:property:og:url", "meta:name:anything-at-all", "json-ld"):
        assert control.control(site, name)[0] is Actor.AUTHOR


def test_every_field_is_unknown_on_a_generic_page() -> None:
    """No site type, no attribution."""
    control = head_field_control()

    for name in ("title", "canonical", "meta:name:description"):
        assert control.control("generic", name)[0] is Actor.UNKNOWN


@pytest.mark.parametrize(
    ("name", "actor"),
    [
        ("canonical", Actor.AUTHOR),
        ("meta:name:description", Actor.AUTHOR),
        ("meta:property:og:description", Actor.AUTHOR),
        ("meta:property:og:title", Actor.AUTHOR),
        ("meta:property:og:url", Actor.PLATFORM),
        ("meta:property:og:site_name", Actor.PLATFORM),
        ("meta:name:head-cached-at", Actor.PLATFORM),
        ("meta:name:search-script", Actor.PLATFORM),
        ("meta:property:forem:logo", Actor.PLATFORM),
        ("title", Actor.UNKNOWN),
        ("meta:property:og:image", Actor.UNKNOWN),
        ("json-ld", Actor.UNKNOWN),
        ("meta:name:never-seen-before", Actor.UNKNOWN),
    ],
)
def test_dev_fields_follow_the_front_matter_and_the_real_page(name: str, actor: Actor) -> None:
    """Front matter fields are AUTHOR, generated ones PLATFORM, the rest UNKNOWN."""
    assert head_field_control().control("dev", name)[0] is actor


def test_every_dev_entry_names_its_source() -> None:
    """Decision 2: no DEV entry without a reason."""
    dev = head_field_control().sites["dev"]

    assert dev.rules
    assert all(rule.source.strip() for rule in dev.rules)
    assert dev.source.strip()


def test_an_exact_name_wins_over_a_pattern() -> None:
    """A listed field is not overridden by a broader pattern."""
    control = load_head_fields(
        """
version = 3
[site.dev]
default = "UNKNOWN"
source = "unlisted"
[[site.dev.field]]
pattern = "meta:name:*"
control = "PLATFORM"
source = "pattern"
[[site.dev.field]]
name = "meta:name:description"
control = "AUTHOR"
source = "exact"
"""
    )

    assert control.control("dev", "meta:name:description") == (Actor.AUTHOR, "exact")
    assert control.control("dev", "meta:name:other") == (Actor.PLATFORM, "pattern")
    assert control.control("dev", "title") == (Actor.UNKNOWN, "unlisted")


_DEV = 'version = 1\n[site.dev]\ndefault = "AUTHOR"\nsource = "x"\n'
"""A valid start of a control file, for the malformed cases."""


@pytest.mark.parametrize(
    "text",
    [
        "version = 0\n",
        'version = "1"\n',
        'version = 1\n[site.dev]\ndefault = "MAYBE"\nsource = "x"\n',
        'version = 1\n[site.dev]\ndefault = "AUTHOR"\n',
        _DEV + '[[site.dev.field]]\ncontrol = "AUTHOR"\nsource = "x"\n',
        _DEV + '[[site.dev.field]]\nname = "t"\ncontrol = "AUTHOR"\nsource = ""\n',
    ],
    ids=["zero", "text", "bad-control", "no-source", "no-name", "empty-source"],
)
def test_a_malformed_file_is_refused(text: str) -> None:
    """A bad control file never classifies anything."""
    with pytest.raises(HeadFieldsError):
        load_head_fields(text)


@pytest.mark.parametrize(
    ("extractor_id", "selection", "site"),
    [
        ("dev.article", ExtractorSelection.HOST, "dev"),
        ("wordpress.entry", ExtractorSelection.PREFIX, "wordpress"),
        ("generic", ExtractorSelection.DECLARED, "owned"),
        ("generic", ExtractorSelection.PREFIX, "owned"),
        ("generic", ExtractorSelection.GENERIC, "generic"),
    ],
)
def test_a_snapshots_site_comes_from_its_extractor(
    extractor_id: str, selection: ExtractorSelection, site: str
) -> None:
    """Owned pages use the generic extractor, chosen by a declaration or a prefix."""
    assert site_of(extractor_id, selection.value) == site
