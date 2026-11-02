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

    # Two pairs with one copy each, and one with two copies (Session 5b).
    assert len(parse_pair_map(example).pairs) == 4


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
            "site must be one of dev, wordpress, owned",
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


# [[site]] prefix rules (Session 4d)

SITES = """
format = 1

[[site]]
prefix = "https://www.kenwalger.com/blog/"
type = "wordpress"

[[site]]
prefix = "https://dev.to/"
type = "dev"
"""


def test_site_rules_are_read_in_order_and_a_map_may_have_only_sites() -> None:
    """[[site]] entries become prefix rules; pairs are optional when there are sites."""
    loaded = parse_pair_map(SITES)

    assert loaded.pairs == ()
    assert [(rule.prefix, rule.site) for rule in loaded.sites] == [
        ("https://www.kenwalger.com/blog/", SiteType.WORDPRESS),
        ("https://dev.to/", SiteType.DEV),
    ]


def test_sites_and_pairs_together() -> None:
    """A map can declare pairs and prefix rules."""
    loaded = parse_pair_map(VALID + SITES.replace("format = 1\n", ""))

    assert (len(loaded.pairs), len(loaded.sites)) == (2, 2)


def _site(body: str) -> str:
    """Write a map with one [[site]].

    :param body: The site table's lines.
    :return: The map.
    """
    return f"format = 1\n[[site]]\n{body}\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("format = 1\n", r"at least one \[\[pair\]\] or \[\[site\]\]"),
        ('format = 1\nsite = "https://a.example/"\n', "site must be an array"),
        (
            _site('prefix = "https://a.example/"\ntype = "dev"\nkind = "x"'),
            "site 1: unknown key kind",
        ),
        (_site('type = "dev"'), "site 1: prefix must be an absolute"),
        (_site('prefix = "/blog/"\ntype = "dev"'), "prefix must be an absolute"),
        (_site('prefix = "https://a.example/?x=1"\ntype = "dev"'), "query or a fragment"),
        (_site('prefix = "https://a.example/#x"\ntype = "dev"'), "query or a fragment"),
        (
            _site('prefix = "https://a.example/"'),
            "site 1, type: must be one of dev, wordpress, owned",
        ),
        (
            _site('prefix = "https://a.example/"\ntype = "medium"'),
            "must be one of dev, wordpress, owned",
        ),
        (
            _site('prefix = "https://a.example/blog/"\ntype = "dev"')
            + '[[site]]\nprefix = "https://A.example/blog"\ntype = "wordpress"\n',
            "site 2: .* type wordpress here but dev in site 1",
        ),
    ],
)
def test_every_site_rule_is_enforced_and_named(text: str, message: str) -> None:
    """Each broken [[site]] rule fails with a message that says where."""
    with pytest.raises(PairMapError, match=message):
        parse_pair_map(text)


def test_one_prefix_given_the_same_type_twice_is_fine() -> None:
    """Repeating a rule is redundant, not wrong."""
    text = (
        _site('prefix = "https://a.example/"\ntype = "dev"')
        + '[[site]]\nprefix = "https://a.example"\ntype = "dev"\n'
    )

    assert len(parse_pair_map(text).sites) == 2


# The owned site type (Session 5a)


def test_owned_is_a_site_type_in_pairs_and_prefix_rules() -> None:
    """An owned page can be declared on a pair URL or by a prefix rule."""
    text = """
format = 1

[[site]]
prefix = "https://notes.example/"
type = "owned"

[[pair]]
original = { url = "https://notes.example/post/" }
copy = { url = "https://mirror.example/post/", site = "owned" }
"""

    parsed = parse_pair_map(text)

    assert [(rule.prefix, rule.site) for rule in parsed.sites] == [
        ("https://notes.example/", SiteType.OWNED)
    ]
    assert parsed.site_types() == {"https://mirror.example/post": SiteType.OWNED}


# One original, several copies (Session 5b)


def test_copies_give_one_pair_each_sharing_the_original() -> None:
    """DEV and CoderLegion copies of one original."""
    text = """
format = 1

[[pair]]
original = { url = "https://www.kenwalger.com/blog/a-post/", site = "wordpress" }
copies = [
  { url = "https://dev.to/kenwalger/a-post-1a2b" },
  { url = "https://coderlegion.com/123/a-post" },
]
"""

    loaded = parse_pair_map(text)

    assert [(p.original.url, p.copy.url) for p in loaded.pairs] == [
        ("https://www.kenwalger.com/blog/a-post/", "https://dev.to/kenwalger/a-post-1a2b"),
        ("https://www.kenwalger.com/blog/a-post/", "https://coderlegion.com/123/a-post"),
    ]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("", "exactly one of copy or copies"),
        (
            'copy = { url = "https://b.example/" }\ncopies = [{ url = "https://c.example/" }]\n',
            "exactly one of copy or copies",
        ),
        ("copies = []\n", "non-empty array"),
        ('copies = [{ url = "https://a.example/x" }]\n', "copy 1 is the same URL"),
        (
            'copies = [{ url = "https://b.example/" }, { url = "https://B.example" }]\n',
            "listed as a copy twice",
        ),
        ('copies = [{ url = "/relative" }]\n', "pair 1, copy 1: url must be an absolute"),
    ],
)
def test_copies_rules_are_enforced(body: str, message: str) -> None:
    """Each mistake is named, with where it is."""
    text = f'format = 1\n[[pair]]\noriginal = {{ url = "https://a.example/x" }}\n{body}'
    with pytest.raises(PairMapError, match=message):
        parse_pair_map(text)
