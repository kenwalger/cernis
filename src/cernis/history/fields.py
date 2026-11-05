"""Who controls each head field, by site type (DESIGN.md section 5, decision 2).

The control file is ``cernis/data/head_fields.toml``. For each site type
(``dev``, ``wordpress``, ``owned``, ``generic``) it gives a default control and
a list of fields, each by exact ``name`` or by an ``fnmatch`` ``pattern``, with
its control (``AUTHOR``, ``PLATFORM``, or ``UNKNOWN``) and its source. An exact
name wins over a pattern, a pattern over the default, and patterns are tried
in file order.

The file's ``version`` is part of the classifier's version
(:func:`classifier_version`), recorded in every run record and every diff, so
a change to the file is a ``CHECKER`` change.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
from importlib.resources import files

from cernis.model import Actor

HISTORY_VERSION = "1"
"""The version of the history code: matching, classification, and causes."""

SITES = ("dev", "wordpress", "owned", "generic")
"""The site types a snapshot can belong to, as the control file names them."""


class HeadFieldsError(ValueError):
    """Raised when the head field control file is malformed."""


@dataclass(frozen=True, kw_only=True)
class FieldRule:
    """One field's control.

    :param control: Who controls the field.
    :param source: Why: the documentation or observation it rests on.
    :param name: The exact field name, or ``None`` for a pattern.
    :param pattern: An ``fnmatch`` pattern, or ``None`` for an exact name.
    """

    control: Actor
    source: str
    name: str | None = None
    pattern: str | None = None


@dataclass(frozen=True, kw_only=True)
class SiteControl:
    """The controls for one site type.

    :param default: The control of any field no rule names.
    :param source: Why the default is what it is.
    :param rules: The rules, in file order.
    """

    default: Actor
    source: str
    rules: tuple[FieldRule, ...] = ()

    def control(self, field: str) -> tuple[Actor, str]:
        """Say who controls a field, and why.

        :param field: A head field name, such as ``meta:name:description``.
        :return: The control and its source.
        """
        for rule in self.rules:
            if rule.name == field:
                return rule.control, rule.source
        for rule in self.rules:
            if rule.pattern is not None and fnmatchcase(field, rule.pattern):
                return rule.control, rule.source
        return self.default, self.source


@dataclass(frozen=True, kw_only=True)
class HeadFieldControl:
    """The whole control file.

    :param version: The file's version.
    :param sites: The controls, by site type.
    """

    version: int
    sites: Mapping[str, SiteControl]

    def control(self, site: str, field: str) -> tuple[Actor, str]:
        """Say who controls a field on a site type, and why.

        :param site: The site type (:data:`SITES`).
        :param field: The field name.
        :return: The control and its source; ``UNKNOWN`` for a site type the
            file does not describe.
        """
        rules = self.sites.get(site)
        if rules is None:
            return Actor.UNKNOWN, f"the control file does not describe site type {site!r}"
        return rules.control(field)


def _actor(value: object, where: str) -> Actor:
    """Read a control.

    :param value: The value from the file.
    :param where: Where it was, for the message.
    :return: The actor.
    :raises HeadFieldsError: If it is not ``AUTHOR``, ``PLATFORM``, or ``UNKNOWN``.
    """
    if not isinstance(value, str) or value not in Actor.__members__:
        raise HeadFieldsError(
            f"{where}: control must be AUTHOR, PLATFORM, or UNKNOWN, got {value!r}"
        )
    return Actor(value)


def _source(value: object, where: str) -> str:
    """Read a source.

    :param value: The value from the file.
    :param where: Where it was, for the message.
    :return: The source.
    :raises HeadFieldsError: If it is missing or blank.
    """
    if not isinstance(value, str) or not value.strip():
        raise HeadFieldsError(f"{where}: every entry needs a source")
    return value


def load_head_fields(text: str) -> HeadFieldControl:
    """Parse a head field control file.

    :param text: The TOML.
    :return: The controls.
    :raises HeadFieldsError: If the file is malformed: a bad version, an
        unknown control, an entry with no source, or a rule with neither or
        both of ``name`` and ``pattern``.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise HeadFieldsError(f"not TOML: {exc}") from exc
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise HeadFieldsError(f"version must be a positive integer, got {version!r}")
    raw_sites = data.get("site", {})
    if not isinstance(raw_sites, dict):
        raise HeadFieldsError("site must be a table")
    sites: dict[str, SiteControl] = {}
    for site, raw in raw_sites.items():
        where = f"site.{site}"
        if site not in SITES or not isinstance(raw, dict):
            raise HeadFieldsError(f"{where}: unknown site type")
        rules: list[FieldRule] = []
        for number, entry in enumerate(raw.get("field", []), start=1):
            here = f"{where}.field {number}"
            if not isinstance(entry, dict):
                raise HeadFieldsError(f"{here}: must be a table")
            name, pattern = entry.get("name"), entry.get("pattern")
            if (name is None) == (pattern is None) or not all(
                part is None or (isinstance(part, str) and part) for part in (name, pattern)
            ):
                raise HeadFieldsError(f"{here}: give exactly one of name and pattern")
            rules.append(
                FieldRule(
                    control=_actor(entry.get("control"), here),
                    source=_source(entry.get("source"), here),
                    name=name,
                    pattern=pattern,
                )
            )
        sites[site] = SiteControl(
            default=_actor(raw.get("default"), where),
            source=_source(raw.get("source"), where),
            rules=tuple(rules),
        )
    return HeadFieldControl(version=version, sites=sites)


@cache
def head_field_control() -> HeadFieldControl:
    """Load the control file shipped with Cernis, once.

    :return: The controls.
    """
    text = files("cernis.data").joinpath("head_fields.toml").read_text(encoding="utf-8")
    return load_head_fields(text)


def classifier_version() -> str:
    """Name the version of the change classifier.

    :return: ``<history version>+h<control file version>``, such as ``1+h1``.
    """
    return f"{HISTORY_VERSION}+h{head_field_control().version}"


def site_of(extractor_id: str, selection: str) -> str:
    """Say which site type a snapshot belongs to, from how it was extracted.

    An owned page uses the generic extractor, chosen by a declaration or a
    prefix rule; a page with no site type uses it by default.

    :param extractor_id: The snapshot's extractor id.
    :param selection: How the extractor was chosen.
    :return: ``dev``, ``wordpress``, ``owned``, or ``generic``.
    """
    if extractor_id == "dev.article":
        return "dev"
    if extractor_id == "wordpress.entry":
        return "wordpress"
    if selection in ("declared", "prefix"):
        return "owned"
    return "generic"
