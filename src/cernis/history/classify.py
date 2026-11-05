"""Change classification between two stored runs (DESIGN.md section 5).

Pure functions over stored records; nothing here fetches.

**Matching.** Runs are compared by normalized subject URL, findings by
``key``, never by finding id or receipt id, which differ in every run. A
page's snapshot in a run is the one taken from the page's last successful
receipt (a ``2xx``, or a ``304`` with its cached body) in that run.

**Page changes.** ``CHECKER`` first: the Cernis version, the classifier
version, or the extractor id or version differs. Then, by what changed:
``AUTHOR_CONTENT`` (``content_sha256``); ``AUTHOR_METADATA`` (only ``AUTHOR``
head fields); ``AUTHOR_FRAME`` (content unchanged, and the frame changed,
alone or with ``AUTHOR`` head fields, on a ``wordpress`` page, or an ``owned``
one if it ever has a body; Session 6e); ``PLATFORM_RENDERING`` (content
unchanged, and only ``PLATFORM`` head fields, or the frame of a ``dev``
page); and ``UNCLASSIFIED`` for anything else: an ``UNKNOWN`` field, a missing
``content_sha256`` (so every owned page today), a frame change on a
``generic`` page, a head hash change with no head field change, more than one
class at once (content with the frame included), a head change involving a
snapshot without per-field values, or a page with no snapshot in a run.
``AUTHOR_FRAME`` names who controls the frame (DESIGN.md section 3), not who
made the change: on WordPress the frame includes readers' comments and the
site's widgets.

**Finding changes.** A key that appears, disappears, or changes ``status``,
``defect``, ``reason_code``, or evidence values. Evidence is compared on its
locations and values only, never on receipt ids or fetch times. A key whose
``check_version`` differs is a ``CHECKER`` change.

**Causes** (decision 3): ``CHECKER`` (the check version, the classifier
version, or the Cernis version differs, or the evidence is from the page and
its extractor changed); ``PAGE`` (the evidence is from the page's own receipt,
and the page changed; it carries the page change's class); ``RESOURCE`` (the
evidence is from another receipt, and the receipt it cites differs between the
runs in status, final URL, body hash, or error kind, a ``304`` that validated
a cached ``200`` counting as that ``200``; the resource is named); and
``UNKNOWN`` (nothing above can be shown, including a resource whose receipts
are identical or that was fetched in only one run, page evidence when the
page did not change, and more than one shown change at once).
"""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from cernis.history.fields import HISTORY_VERSION, HeadFieldControl, head_field_control, site_of
from cernis.model import Actor, ChangeClass
from cernis.store.base import StoredEntry
from cernis.urls import normalize_url

Record = Mapping[str, object]
"""A stored record, as the JSON report writes it."""

RECEIPT_FIELDS = ("status_code", "final_url", "body_sha256", "error_kind")
"""What a resource's receipt is compared on."""

FINDING_FIELDS = ("status", "defect", "reason_code")
"""The finding fields compared besides evidence."""

_FRAME_CLASS = {
    "wordpress": ChangeClass.AUTHOR_FRAME,
    "owned": ChangeClass.AUTHOR_FRAME,
    "dev": ChangeClass.PLATFORM_RENDERING,
}
"""Who a frame change is, by site type (Session 6e); a generic page's frame is nobody's known."""


class Cause(StrEnum):
    """Why a finding changed between two runs (DESIGN.md section 5, decision 3)."""

    CHECKER = "CHECKER"
    """The check's version, or the classifier's, differs between the runs."""
    PAGE = "PAGE"
    """The evidence is from the page itself, which changed."""
    RESOURCE = "RESOURCE"
    """The evidence is from another resource, whose receipt changed."""
    UNKNOWN = "UNKNOWN"
    """None of the above can be shown."""


class DiffError(ValueError):
    """Raised when two runs cannot be chosen for a URL.

    :param message: What is wrong.
    :param usage: Whether it is the caller's choice of run that is wrong
        (a usage error), not the store's contents.
    """

    def __init__(self, message: str, *, usage: bool = False) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True, kw_only=True)
class RunView:
    """One complete stored run, indexed for comparison.

    :param run_id: The run's id.
    :param record: The run record.
    :param receipts: Receipt records, by receipt id, in run order.
    :param snapshots: Snapshot records, by the id of the receipt they were taken of.
    :param findings: Finding records, by finding key.
    """

    run_id: str
    record: Record
    receipts: Mapping[str, Record]
    snapshots: Mapping[str, Record]
    findings: Mapping[str, Record]

    def text(self, name: str) -> str:
        """Read a text field of the run record.

        :param name: The field.
        :return: Its value, or an empty string.
        """
        value = self.record.get(name)
        return value if isinstance(value, str) else ""

    def subjects(self) -> list[str]:
        """List the run's subjects, normalized.

        :return: The normalized subject URLs.
        """
        subjects = self.record.get("subjects")
        if not isinstance(subjects, list):
            return []
        return [normalize_url(s) for s in subjects if isinstance(s, str)]


@dataclass(frozen=True, kw_only=True)
class FieldChange:
    """One head field that changed.

    :param name: The field's name.
    :param control: Who controls it on the page's site type.
    :param source: Why, from the control file.
    :param before: Its values in the earlier run.
    :param after: Its values in the later run.
    """

    name: str
    control: Actor
    source: str
    before: tuple[str, ...]
    after: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class PageChange:
    """How a page changed between two runs, and the evidence for its class.

    :param change_class: The class.
    :param reasons: Why it has that class, in sentences.
    :param hashes: The snapshot hashes that changed.
    :param fields: The head fields that changed, with their control.
    :param shown: Whether a difference between the runs' snapshots was
        observed; ``False`` when neither run has one, so nothing shows the
        page changed, and it cannot be a finding change's cause.
    """

    change_class: ChangeClass
    reasons: tuple[str, ...]
    hashes: tuple[str, ...] = ()
    fields: tuple[FieldChange, ...] = ()
    shown: bool = True


@dataclass(frozen=True, kw_only=True)
class FindingChange:
    """One finding key that changed between two runs.

    :param key: The finding key.
    :param check_id: The check.
    :param target: The finding's target.
    :param kind: ``appeared``, ``disappeared``, or ``changed``.
    :param changed: For ``changed``, the fields that differ: ``status``,
        ``defect``, ``reason_code``, ``evidence``, ``check_version``.
    :param cause: Why it changed.
    :param detail: The cause in words.
    :param page_class: For ``PAGE``, the page change's class.
    :param resource_url: For ``RESOURCE``, the resource that changed.
    :param before: The finding in the earlier run, or ``None``.
    :param after: The finding in the later run, or ``None``.
    """

    key: str
    check_id: str
    target: str
    kind: str
    changed: tuple[str, ...]
    cause: Cause
    detail: str
    page_class: ChangeClass | None = None
    resource_url: str | None = None
    before: Record | None = None
    after: Record | None = None


@dataclass(frozen=True, kw_only=True)
class RunDiff:
    """What changed for one URL between two runs.

    :param url: The URL, as asked for.
    :param before: The earlier run.
    :param after: The later run.
    :param classifier_version: The version of the classifier that made the diff.
    :param page_change: The page change, or ``None`` if the page did not change.
    :param finding_changes: The finding changes, by key.
    """

    url: str
    before: RunView
    after: RunView
    classifier_version: str
    page_change: PageChange | None
    finding_changes: tuple[FindingChange, ...]

    @property
    def empty(self) -> bool:
        """Whether nothing changed between the runs."""
        return self.page_change is None and not self.finding_changes


def run_views(entries: Sequence[StoredEntry]) -> list[RunView]:
    """Gather the complete runs in a store, in the order they were recorded.

    :param entries: Every entry, verified, in sequence order.
    :return: One view per run with a run record.
    """
    receipts: dict[str, dict[str, Record]] = {}
    snapshots: dict[str, dict[str, Record]] = {}
    findings: dict[str, dict[str, Record]] = {}
    records: list[tuple[str, Record]] = []
    for entry in entries:
        record = entry.record
        if entry.kind == "receipt":
            receipts.setdefault(entry.run_id, {})[str(record.get("id"))] = record
        elif entry.kind == "snapshot":
            snapshots.setdefault(entry.run_id, {})[str(record.get("receipt_id"))] = record
        elif entry.kind == "finding":
            findings.setdefault(entry.run_id, {})[str(record.get("key"))] = record
        else:
            records.append((entry.run_id, record))
    return [
        RunView(
            run_id=run_id,
            record=record,
            receipts=receipts.get(run_id, {}),
            snapshots=snapshots.get(run_id, {}),
            findings=findings.get(run_id, {}),
        )
        for run_id, record in records
    ]


def _choose(
    views: Sequence[RunView], url: str, before: str | None, after: str | None
) -> tuple[RunView, RunView]:
    """Choose the two runs to compare.

    :param views: Every complete run, oldest first.
    :param url: The URL.
    :param before: The earlier run's id, or ``None``.
    :param after: The later run's id, or ``None``.
    :return: The earlier run and the later run.
    :raises DiffError: If fewer than two runs audited the URL, or, as a
        usage error naming the runs that did, a run given did not audit it, or
        ``before`` is not stored before ``after``.
    """
    wanted = normalize_url(url)
    with_url = [view for view in views if wanted in view.subjects()]
    ids = [view.run_id for view in with_url]
    for given in (before, after):
        if given is not None and given not in ids:
            listed = ", ".join(ids) or "none"
            raise DiffError(
                f"run {given} did not audit {url}; the runs that did: {listed}", usage=True
            )
    if len(with_url) < 2 and (before is None or after is None):
        raise DiffError(f"fewer than two stored runs audited {url}: {', '.join(ids) or 'none'}")
    by_id = {view.run_id: view for view in with_url}
    if before is not None and after is not None:
        if ids.index(before) >= ids.index(after):
            raise DiffError(
                f"run {before} must be stored before run {after}: --from names the earlier "
                f"of two different runs; the runs that audited {url}, oldest first: "
                + ", ".join(ids),
                usage=True,
            )
        return by_id[before], by_id[after]
    if after is not None:
        earlier = [view for view in with_url[: ids.index(after)]]
        if not earlier:
            raise DiffError(f"no stored run of {url} came before {after}", usage=True)
        return earlier[-1], by_id[after]
    if before is not None:
        later = with_url[ids.index(before) + 1 :]
        if not later:
            raise DiffError(f"no stored run of {url} came after {before}", usage=True)
        return by_id[before], later[-1]
    return with_url[-2], with_url[-1]


def diff_runs(
    entries: Sequence[StoredEntry],
    url: str,
    *,
    before: str | None = None,
    after: str | None = None,
    control: HeadFieldControl | None = None,
) -> RunDiff:
    """Compare two stored runs for one URL.

    :param entries: Every entry, verified, in sequence order.
    :param url: The URL.
    :param before: The earlier run's id; by default, the second most recent
        run that audited the URL (or the one before ``after``).
    :param after: The later run's id; by default, the most recent run that
        audited the URL.
    :param control: The head field control; the shipped file if ``None``.
    :return: The diff.
    """
    first, second = _choose(run_views(entries), url, before, after)
    return diff_views(first, second, url, control=control)


def diff_views(
    before: RunView, after: RunView, url: str, *, control: HeadFieldControl | None = None
) -> RunDiff:
    """Compare two runs for one URL.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The URL.
    :param control: The head field control; the shipped file if ``None``.
    :return: The diff.
    """
    rules = control or head_field_control()
    page = _page_change(before, after, url, rules)
    return RunDiff(
        url=url,
        before=before,
        after=after,
        classifier_version=f"{HISTORY_VERSION}+h{rules.version}",
        page_change=page,
        finding_changes=_finding_changes(before, after, url, page),
    )


def _same_url(a: object, b: str) -> bool:
    """Tell whether a stored URL is a normalized URL.

    :param a: A URL from a record.
    :param b: A normalized URL.
    :return: Whether they are the same after normalization.
    """
    if not isinstance(a, str) or not a:
        return False
    try:
        return normalize_url(a) == b
    except ValueError:
        return False


def _receipts_for(view: RunView, url: str) -> list[str]:
    """List the ids of a run's receipts requested at a URL, in run order.

    :param view: The run.
    :param url: The URL, normalized.
    :return: The receipt ids.
    """
    return [rid for rid, r in view.receipts.items() if _same_url(r.get("requested_url"), url)]


def _page_snapshot(view: RunView, url: str) -> Record | None:
    """Find a page's snapshot: the one of its last successful receipt in the run.

    :param view: The run.
    :param url: The page's URL, normalized.
    :return: The snapshot record, or ``None`` if the run read no whole page.
    """
    with_snapshot = [rid for rid in _receipts_for(view, url) if rid in view.snapshots]
    return view.snapshots[with_snapshot[-1]] if with_snapshot else None


def _values(fields: object) -> dict[str, tuple[str, ...]]:
    """Group a snapshot's head fields by name.

    :param fields: The stored ``head_fields``: a list of ``[name, value]`` pairs.
    :return: Each name's values, sorted.
    """
    grouped: dict[str, list[str]] = {}
    for pair in fields if isinstance(fields, list) else []:
        if isinstance(pair, list) and len(pair) == 2:
            grouped.setdefault(str(pair[0]), []).append(str(pair[1]))
    return {name: tuple(sorted(values)) for name, values in grouped.items()}


def _checker_reasons(
    before: RunView, after: RunView, first: Record | None, second: Record | None
) -> list[str]:
    """Say what about the checker differs between two runs, if anything.

    :param before: The earlier run.
    :param after: The later run.
    :param first: The page's snapshot in the earlier run, if any.
    :param second: The page's snapshot in the later run, if any.
    :return: One sentence per difference.
    """
    reasons = []
    for name, what in (
        ("cernis_version", "Cernis version"),
        ("classifier_version", "classifier version"),
    ):
        if before.record.get(name) != after.record.get(name):
            reasons.append(
                f"the {what} changed ({before.record.get(name)} to {after.record.get(name)})"
            )
    if first is not None and second is not None:
        for name, what in (
            ("extractor_id", "extractor"),
            ("extractor_version", "extractor version"),
        ):
            if first.get(name) != second.get(name):
                reasons.append(f"the {what} changed ({first.get(name)} to {second.get(name)})")
    return reasons


def _field_changes(
    first: Record, second: Record, control: HeadFieldControl
) -> tuple[str, tuple[FieldChange, ...]]:
    """List the head fields that changed, with who controls each.

    :param first: The earlier snapshot, with head fields.
    :param second: The later snapshot, with head fields.
    :param control: The head field control.
    :return: The page's site type, and the fields that changed, by name.
    """
    site = site_of(str(second.get("extractor_id")), str(second.get("extractor_selection")))
    old, new = _values(first.get("head_fields")), _values(second.get("head_fields"))
    changes = []
    for name in sorted(set(old) | set(new)):
        if old.get(name, ()) != new.get(name, ()):
            actor, source = control.control(site, name)
            changes.append(
                FieldChange(
                    name=name,
                    control=actor,
                    source=source,
                    before=old.get(name, ()),
                    after=new.get(name, ()),
                )
            )
    return site, tuple(changes)


def _page_change(
    before: RunView, after: RunView, url: str, control: HeadFieldControl
) -> PageChange | None:
    """Classify the page change for a URL.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The URL.
    :param control: The head field control.
    :return: The page change, or ``None`` if the page did not change.
    """
    wanted = normalize_url(url)
    first, second = _page_snapshot(before, wanted), _page_snapshot(after, wanted)
    hashes: tuple[str, ...] = ()
    if first is not None and second is not None:
        hashes = tuple(
            name
            for name in ("content_sha256", "head_sha256", "frame_sha256")
            if first.get(name) != second.get(name)
        )
    checker = _checker_reasons(before, after, first, second)
    if checker:
        if first is not None and second is not None and not hashes:
            checker.append("no snapshot hash changed")
        return PageChange(change_class=ChangeClass.CHECKER, reasons=tuple(checker), hashes=hashes)
    if first is None and second is None:
        return PageChange(
            change_class=ChangeClass.UNCLASSIFIED,
            reasons=(
                f"runs {before.run_id} and {after.run_id} both have no snapshot of the page "
                "(it was not read whole in either), so whether it changed cannot be determined",
            ),
            shown=False,
        )
    if first is None or second is None:
        missing = before.run_id if first is None else after.run_id
        return PageChange(
            change_class=ChangeClass.UNCLASSIFIED,
            reasons=(f"run {missing} has no snapshot of the page (it was not read whole)",),
        )
    if not hashes:
        return None
    if first.get("content_sha256") is None or second.get("content_sha256") is None:
        evidence: tuple[FieldChange, ...] = ()
        if (
            "head_sha256" in hashes
            and isinstance(first.get("head_fields"), list)
            and isinstance(second.get("head_fields"), list)
        ):
            evidence = _field_changes(first, second, control)[1]
        return PageChange(
            change_class=ChangeClass.UNCLASSIFIED,
            reasons=(
                "a snapshot has no content_sha256 (no article body was found), "
                "so the change cannot be placed",
            ),
            hashes=hashes,
            fields=evidence,
        )
    classes: dict[ChangeClass, list[str]] = {}
    fields: tuple[FieldChange, ...] = ()
    if "content_sha256" in hashes:
        classes[ChangeClass.AUTHOR_CONTENT] = ["content_sha256 changed: the article body's text"]
    if "head_sha256" in hashes:
        if not isinstance(first.get("head_fields"), list) or not isinstance(
            second.get("head_fields"), list
        ):
            return PageChange(
                change_class=ChangeClass.UNCLASSIFIED,
                reasons=("head_sha256 changed, but a snapshot has no head fields to say which",),
                hashes=hashes,
            )
        site, fields = _field_changes(first, second, control)
        if not fields:
            return PageChange(
                change_class=ChangeClass.UNCLASSIFIED,
                reasons=(
                    "head_sha256 changed, but no head field did, so the change cannot be placed",
                ),
                hashes=hashes,
            )
        unknown = [f.name for f in fields if f.control is Actor.UNKNOWN]
        if unknown:
            return PageChange(
                change_class=ChangeClass.UNCLASSIFIED,
                reasons=(
                    f"head fields whose control is UNKNOWN on {site} pages changed: "
                    + ", ".join(unknown),
                ),
                hashes=hashes,
                fields=fields,
            )
        if any(f.control is Actor.AUTHOR for f in fields):
            classes[ChangeClass.AUTHOR_METADATA] = ["head fields the author controls changed"]
        if any(f.control is Actor.PLATFORM for f in fields):
            classes[ChangeClass.PLATFORM_RENDERING] = ["head fields the platform controls changed"]
    if "frame_sha256" in hashes:
        site = site_of(str(second.get("extractor_id")), str(second.get("extractor_selection")))
        frame_class = _FRAME_CLASS.get(site)
        if frame_class is None:
            return PageChange(
                change_class=ChangeClass.UNCLASSIFIED,
                reasons=(
                    f"frame_sha256 changed, and who controls the frame of {site} pages is unknown",
                ),
                hashes=hashes,
                fields=fields,
            )
        if frame_class is ChangeClass.AUTHOR_FRAME and ChangeClass.AUTHOR_METADATA in classes:
            # One actor controls both (Session 6e): the metadata is evidence, not a class.
            classes[ChangeClass.AUTHOR_FRAME] = classes.pop(ChangeClass.AUTHOR_METADATA)
        classes.setdefault(frame_class, []).append(
            "frame_sha256 changed: the page around the article"
        )
    if len(classes) > 1:
        names = ", ".join(sorted(classes))
        return PageChange(
            change_class=ChangeClass.UNCLASSIFIED,
            reasons=(
                f"more than one class at once ({names})",
                *(reason for reasons in classes.values() for reason in reasons),
            ),
            hashes=hashes,
            fields=fields,
        )
    ((change_class, reasons),) = classes.items()
    return PageChange(
        change_class=change_class, reasons=tuple(reasons), hashes=hashes, fields=fields
    )


_RECEIPT_WORDS = {
    "status_code": "status",
    "final_url": "final URL",
    "body_sha256": "body hash",
    "error_kind": "error kind",
}


def _evidence_receipts(finding: Record | None) -> list[str]:
    """List the receipt ids a finding's evidence names.

    :param finding: The finding record, or ``None``.
    :return: The receipt ids, in order.
    """
    items = finding.get("evidence") if finding is not None else None
    return [
        str(item.get("receipt_id"))
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict) and item.get("receipt_id")
    ]


@dataclass(frozen=True, kw_only=True)
class _Cited:
    """A resource a finding's evidence names, and the receipts it cites in each run.

    :param requested: The resource's URL, as requested.
    :param before: The receipt ids cited in the earlier run, in order.
    :param after: The receipt ids cited in the later run, in order.
    """

    requested: str
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


def _compared_receipt(view: RunView, url: str, cited: tuple[str, ...]) -> Record | None:
    """Choose the receipt of a resource to compare in one run.

    :param view: The run.
    :param url: The resource's URL, normalized.
    :param cited: The receipts the finding cites in that run.
    :return: The last cited receipt; if none is cited (the finding is absent
        from that run), the run's last receipt of the URL; ``None`` if the
        run never fetched it.
    """
    if cited:
        return view.receipts[cited[-1]]
    ids = _receipts_for(view, url)
    return view.receipts[ids[-1]] if ids else None


def _receipt_value(receipt: Record, name: str) -> object:
    """Read a compared receipt field, a ``304`` that validated a cached ``200`` as that ``200``.

    The fetcher caches only ``200`` responses and records a ``304`` with the
    cached body's hash, so a ``304`` with a body hash is the same response,
    revalidated, and the body hash says whether it is the same body.

    :param receipt: The receipt record.
    :param name: The field, one of :data:`RECEIPT_FIELDS`.
    :return: The value compared.
    """
    value = receipt.get(name)
    if name == "status_code" and value == 304 and receipt.get("body_sha256"):
        return 200
    return value


def _resource_change(
    before: RunView, after: RunView, url: str, cited: _Cited
) -> tuple[bool, str] | None:
    """Say whether a resource's receipt differs between the runs.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The resource's URL, normalized.
    :param cited: What the finding cites of it.
    :return: ``(True, what changed)`` for a shown change, ``(False, why not)``
        when it was fetched in only one run (nothing to compare), or ``None``
        when the receipts compared are the same.
    """
    old = _compared_receipt(before, url, cited.before)
    new = _compared_receipt(after, url, cited.after)
    if old is None or new is None:
        missing = before.run_id if old is None else after.run_id
        return False, f"the resource {cited.requested} was not fetched in run {missing}"
    for name in RECEIPT_FIELDS:
        if _receipt_value(old, name) != _receipt_value(new, name):
            word = _RECEIPT_WORDS[name]
            return True, f"its {word} changed ({old.get(name)} to {new.get(name)})"
    return None


def _evidence_sources(
    before: RunView, after: RunView, url: str, old: Record | None, new: Record | None
) -> tuple[bool, dict[str, _Cited]]:
    """Sort a finding's evidence into the page's own receipts and other resources.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The page's URL, normalized.
    :param old: The finding in the earlier run, or ``None``.
    :param new: The finding in the later run, or ``None``.
    :return: Whether any evidence is from the page, and the other resources,
        by normalized URL, with the receipts cited in each run.
    """
    from_page = False
    resources: dict[str, _Cited] = {}
    for earlier, view, finding in ((True, before, old), (False, after, new)):
        for rid in _evidence_receipts(finding):
            requested = view.receipts.get(rid, {}).get("requested_url")
            if _same_url(requested, url):
                from_page = True
            elif isinstance(requested, str) and requested:
                key = normalize_url(requested)
                cited = resources.get(key, _Cited(requested=requested))
                if earlier:
                    cited = dataclasses.replace(cited, before=(*cited.before, rid))
                else:
                    cited = dataclasses.replace(cited, after=(*cited.after, rid))
                resources[key] = cited
    return from_page, resources


def _cause(
    before: RunView,
    after: RunView,
    url: str,
    old: Record | None,
    new: Record | None,
    page: PageChange | None,
) -> tuple[Cause, str, ChangeClass | None, str | None]:
    """Say why a finding changed.

    The cause must be shown: a change is attributed to the page or to a
    resource only when exactly one of them is shown to have changed.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The page's URL, normalized.
    :param old: The finding in the earlier run, or ``None``.
    :param new: The finding in the later run, or ``None``.
    :param page: The page change, if any.
    :return: The cause, its detail, the page class for ``PAGE``, and the
        resource for ``RESOURCE``.
    """
    for name, what in (
        ("classifier_version", "classifier version"),
        ("cernis_version", "Cernis version"),
    ):
        if before.record.get(name) != after.record.get(name):
            return Cause.CHECKER, f"the {what} changed between the runs", None, None
    present = new if new is not None else old
    assert present is not None
    if old is not None and new is not None:
        if old.get("check_version") != new.get("check_version"):
            versions = f"{old.get('check_version')} to {new.get('check_version')}"
            return Cause.CHECKER, f"the check version changed ({versions})", None, None
    else:
        other = before if old is None else after
        seen = {
            f.get("check_version")
            for f in other.findings.values()
            if f.get("check_id") == present.get("check_id")
        }
        if seen and present.get("check_version") not in seen:
            return Cause.CHECKER, "the check's version differs between the runs", None, None
    from_page, resources = _evidence_sources(before, after, url, old, new)
    if from_page and page is not None and page.change_class is ChangeClass.CHECKER:
        detail = "from the page, whose extractor changed: " + "; ".join(page.reasons)
        return Cause.CHECKER, detail, None, None
    shown: list[tuple[Cause, str, ChangeClass | None, str | None]] = []
    if from_page and page is not None and page.shown:
        detail = f"from the page itself, which changed ({page.change_class})"
        shown.append((Cause.PAGE, detail, page.change_class, None))
    unfetched: list[str] = []
    for resource, cited in resources.items():
        change = _resource_change(before, after, resource, cited)
        if change is None:
            continue
        is_shown, what = change
        if is_shown:
            detail = f"the resource {cited.requested} changed: {what}"
            shown.append((Cause.RESOURCE, detail, None, cited.requested))
        else:
            unfetched.append(what)
    if len(shown) == 1:
        return shown[0]
    if shown:
        named = "; ".join(detail for _, detail, _, _ in shown)
        return (
            Cause.UNKNOWN,
            f"more than one change is shown, so none is the cause: {named}",
            None,
            None,
        )
    if unfetched:
        detail = (
            "; ".join(unfetched)
            + ", so it was fetched in only one run and nothing shows it changed"
        )
        return Cause.UNKNOWN, detail, None, None
    if resources:
        detail = "the resources it rests on have the same receipts in both runs"
        return Cause.UNKNOWN, detail, None, None
    if from_page:
        return Cause.UNKNOWN, "its evidence is from the page, which did not change", None, None
    return Cause.UNKNOWN, "its evidence does not show what changed", None, None


def _about(view: RunView, url: str) -> dict[str, Record]:
    """Select a run's findings about one page.

    :param view: The run.
    :param url: The page's URL, normalized.
    :return: The findings, by key.
    """
    return {k: f for k, f in view.findings.items() if _same_url(f.get("subject_url"), url)}


def _finding_changes(
    before: RunView, after: RunView, url: str, page: PageChange | None
) -> tuple[FindingChange, ...]:
    """List the finding changes for a URL, by key.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The URL.
    :param page: The page change.
    :return: The changes, sorted by check, target, and key.
    """
    wanted = normalize_url(url)
    old_findings, new_findings = _about(before, wanted), _about(after, wanted)
    changes: list[FindingChange] = []
    for key in set(old_findings) | set(new_findings):
        old, new = old_findings.get(key), new_findings.get(key)
        changed: tuple[str, ...] = ()
        if old is None:
            kind = "appeared"
        elif new is None:
            kind = "disappeared"
        else:
            kind = "changed"
            changed = tuple(name for name in FINDING_FIELDS if old.get(name) != new.get(name))
            if _canonical_evidence(old) != _canonical_evidence(new):
                changed += ("evidence",)
            if old.get("check_version") != new.get("check_version"):
                changed += ("check_version",)
            if not changed:
                continue
        present = new if new is not None else old
        assert present is not None
        cause, detail, page_class, resource = _cause(before, after, wanted, old, new, page)
        changes.append(
            FindingChange(
                key=key,
                check_id=str(present.get("check_id")),
                target=str(present.get("target") or ""),
                kind=kind,
                changed=changed,
                cause=cause,
                detail=detail,
                page_class=page_class,
                resource_url=resource,
                before=old,
                after=new,
            )
        )
    return tuple(
        sorted(
            _follow_based_on(before, after, changes), key=lambda c: (c.check_id, c.target, c.key)
        )
    )


def _follow_based_on(
    before: RunView, after: RunView, changes: list[FindingChange]
) -> list[FindingChange]:
    """Give a recommendation whose cause is unknown the cause of a finding it rests on.

    A recommendation carries no evidence of its own, only ``based_on``, so its
    cause is the cause of the changes in the findings it is based on, when
    they all share one shown cause. Bases with different causes leave it
    ``UNKNOWN``, naming them; one is never chosen by list order.

    :param before: The earlier run.
    :param after: The later run.
    :param changes: The finding changes.
    :return: The changes, with those recommendations' causes filled in.
    """
    by_key = {change.key: change for change in changes}
    keys = {
        view.run_id: {str(f.get("id")): k for k, f in view.findings.items()}
        for view in (before, after)
    }
    followed = []
    for change in changes:
        present = change.after if change.after is not None else change.before
        based = present.get("based_on") if present is not None else None
        view = after if change.after is not None else before
        if change.cause is Cause.UNKNOWN and isinstance(based, list):
            bases = [
                basis
                for finding_id in based
                if (basis := by_key.get(keys[view.run_id].get(str(finding_id), ""))) is not None
            ]
            causes = {(b.cause, b.page_class, b.resource_url) for b in bases}
            if len(causes) == 1 and bases[0].cause is not Cause.UNKNOWN:
                basis = bases[0]
                change = dataclasses.replace(
                    change,
                    cause=basis.cause,
                    detail=f"it rests on {basis.check_id}, whose cause is: {basis.detail}",
                    page_class=basis.page_class,
                    resource_url=basis.resource_url,
                )
            elif len(causes) > 1:
                named = "; ".join(f"{b.check_id} ({b.cause})" for b in bases)
                detail = f"it rests on changes with different causes: {named}"
                change = dataclasses.replace(change, detail=detail)
        followed.append(change)
    return followed


def _canonical_evidence(finding: Record) -> str:
    """Serialize a finding's evidence without receipt ids, for comparison.

    :param finding: The finding record.
    :return: Its evidence's locations and values, sorted, as JSON.
    """
    items = finding.get("evidence")
    values = [
        [item.get("location"), item.get("observed"), item.get("searched_for")]
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
    ]
    return json.dumps(sorted(values, key=json.dumps), ensure_ascii=False)
