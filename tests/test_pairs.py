"""Tests for the pair map format (docs/PAIR-MAP.md)."""

from pathlib import Path

import pytest

from cernis.pairs import PairMapError, load_pair_map, parse_pair_map
from cernis.parse import SiteType

ORIGINAL = "https://blog.example.com/2026/10/a-post/"
COPY = "https://dev.to/example-author/a-post-1a2b"

VALID = f"""
format = 1

[[pair]]
original = {{ url = "{ORIGINAL}", site = "wordpress" }}
copy = {{ url = "{COPY}", site = "dev" }}

[[pair]]
[pair.original]
url = "https://blog.example.com/2026/09/older/"
[pair.copy]
url = "https://dev.to/example-author/older-3c4d"
"""


def test_a_valid_map_is_read_in_order() -> None:
    """Both inline and sub-table spellings are read, and site is optional."""
    loaded = parse_pair_map(VALID)

    first, second = loaded.pairs
    assert (first.original.url, first.original.site) == (ORIGINAL, SiteType.WORDPRESS)
    assert (first.copy.url, first.copy.site) == (COPY, SiteType.DEV)
    assert (second.original.site, second.copy.site) == (None, None)


def test_site_types_are_given_by_normalized_url() -> None:
    """Only declared URLs appear, keyed the way the rest of Cernis compares URLs."""
    assert parse_pair_map(VALID).site_types() == {
        "https://blog.example.com/2026/10/a-post": SiteType.WORDPRESS,
        "https://dev.to/example-author/a-post-1a2b": SiteType.DEV,
    }


def test_the_documented_example_is_valid() -> None:
    """The example in docs/PAIR-MAP.md loads."""
    doc = (Path(__file__).parents[1] / "docs" / "PAIR-MAP.md").read_text(encoding="utf-8")
    example = doc.split("```toml\n", 1)[1].split("```", 1)[0]

    assert len(parse_pair_map(example).pairs) == 2


def test_a_file_is_loaded(tmp_path: Path) -> None:
    """load_pair_map reads UTF-8 from disk."""
    path = tmp_path / "pairs.toml"
    path.write_text(VALID, encoding="utf-8")

    assert len(load_pair_map(path).pairs) == 2


def test_a_missing_file_is_a_pair_map_error(tmp_path: Path) -> None:
    """The caller gets one exception type for every problem."""
    with pytest.raises(PairMapError, match="cannot read"):
        load_pair_map(tmp_path / "missing.toml")


def _pair(original: str, copy: str) -> str:
    """Write a one-pair map.

    :param original: The original table's TOML.
    :param copy: The copy table's TOML.
    :return: The map.
    """
    return f"format = 1\n[[pair]]\noriginal = {original}\ncopy = {copy}\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("format = 1\n[[pair\n", "not valid TOML"),
        ("format = 2\n[[pair]]\n", "format must be 1"),
        ("[[pair]]\n", "format must be 1"),
        ("format = 1\n", "at least one"),
        ("format = 1\npairs = []\n", "unknown top-level key pairs"),
        ('format = 1\n[[pair]]\norginal = { url = "https://a.example/" }\n', "unknown key orginal"),
        (
            _pair(
                '{ url = "https://a.example/" }', '{ url = "https://b.example/", sites = "dev" }'
            ),
            "unknown key sites",
        ),
        (
            _pair('{ url = "https://a.example/" }', '"https://b.example/"'),
            "pair 1, copy: must be a table",
        ),
        (
            _pair('{ site = "dev" }', '{ url = "https://b.example/" }'),
            "pair 1, original: url must be",
        ),
        (
            _pair('{ url = "/relative" }', '{ url = "https://b.example/" }'),
            "url must be an absolute",
        ),
        (
            _pair('{ url = "ftp://a.example/" }', '{ url = "https://b.example/" }'),
            "url must be an absolute",
        ),
        (
            _pair(
                '{ url = "https://a.example/", site = "medium" }', '{ url = "https://b.example/" }'
            ),
            "site must be one of dev, wordpress",
        ),
        (
            _pair('{ url = "https://a.example/x/" }', '{ url = "https://A.example/x" }'),
            "the copy is the same URL",
        ),
    ],
)
def test_every_rule_is_enforced_and_named(text: str, message: str) -> None:
    """Each broken rule fails with a message that says where and what."""
    with pytest.raises(PairMapError, match=message):
        parse_pair_map(text)


def test_one_url_with_two_site_types_is_an_error() -> None:
    """A URL cannot be both a DEV page and a WordPress page."""
    text = (
        _pair(
            '{ url = "https://a.example/", site = "wordpress" }', '{ url = "https://b.example/" }'
        )
        + '[[pair]]\noriginal = { url = "https://A.example" , site = "dev" }\n'
        + 'copy = { url = "https://c.example/" }\n'
    )

    with pytest.raises(
        PairMapError, match=r"pair 2, original: .* as dev here but as wordpress in pair 1"
    ):
        parse_pair_map(text)


def test_one_url_declared_once_and_left_undeclared_once_is_fine() -> None:
    """Declaring a site type once is enough."""
    text = (
        _pair(
            '{ url = "https://a.example/", site = "wordpress" }', '{ url = "https://b.example/" }'
        )
        + '[[pair]]\noriginal = { url = "https://a.example/" }\n'
        + 'copy = { url = "https://c.example/" }\n'
    )

    assert parse_pair_map(text).site_types() == {"https://a.example/": SiteType.WORDPRESS}
