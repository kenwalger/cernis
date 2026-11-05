"""Tests for change classification (DESIGN.md section 5): page changes, finding changes, causes."""

import dataclasses
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

import pytest
from fetch_support import respond
from parse_support import DEV_URL, WORDPRESS_URL, fixture
from store_support import START, make_run

from cernis.history.classify import (
    Cause,
    DiffError,
    RunView,
    diff_runs,
    diff_views,
    run_views,
)
from cernis.history.fields import HISTORY_VERSION, load_head_fields
from cernis.history.report import format_diff_markdown
from cernis.model import Actor, ChangeClass, Evidence, Run
from cernis.parse import SiteType
from cernis.store import MemoryStore, StoredEntry

DEV_CANONICAL = "https://blog.example.com/2026/10/a-synthetic-post/"
"""The DEV fixture's canonical, on another host, so it is a resource of its own."""


def stored(*runs: Run) -> list[StoredEntry]:
    """Record runs in a fresh in-memory store and read its entries back.

    :param *runs: The runs, in order.
    :return: The entries.
    """
    store = MemoryStore()
    for run in runs:
        with store.writer() as writer:
            writer.record(run)
    return store.entries()


def views(*runs: Run) -> list[RunView]:
    """Record runs and read them back as views.

    :param *runs: The runs, in order.
    :return: One view per run.
    """
    return run_views(stored(*runs))


def edited(name: str, old: str, new: str) -> bytes:
    """Return a fixture with one exact edit.

    :param name: The fixture.
    :param old: Text that occurs exactly once.
    :param new: Its replacement.
    :return: The edited page.
    """
    text = fixture(name).decode("utf-8")
    assert text.count(old) == 1, old
    return text.replace(old, new).encode("utf-8")


def wordpress(tmp_path: Path, hour: int, body: bytes | None = None) -> Run:
    """Audit the WordPress fixture, declared WordPress.

    :param tmp_path: A directory for the cache.
    :param hour: The hour the run starts, which sets its id.
    :param body: The page, or the fixture unchanged.
    :return: The run.
    """
    return make_run(
        tmp_path,
        START.replace(hour=hour),
        fixture("wordpress-entry") if body is None else body,
        url=WORDPRESS_URL,
        site=SiteType.WORDPRESS,
    )


def dev(tmp_path: Path, hour: int, body: bytes | None = None, canonical: int = 200) -> Run:
    """Audit the DEV fixture, its site type from the host.

    :param tmp_path: A directory for the cache.
    :param hour: The hour the run starts.
    :param body: The page, or the fixture unchanged.
    :param canonical: The status the canonical target answers.
    :return: The run.
    """
    return make_run(
        tmp_path,
        START.replace(hour=hour),
        fixture("dev-article") if body is None else body,
        url=DEV_URL,
        site=None,
        routes={DEV_CANONICAL: respond(canonical, b"<html></html>", {"content-type": "text/html"})},
    )


def page_class(before: Run, after: Run, url: str) -> ChangeClass | None:
    """Classify the page change between two runs.

    :param before: The earlier run.
    :param after: The later run.
    :param url: The page.
    :return: The class, or ``None`` for no change.
    """
    change = diff_runs(stored(before, after), url).page_change
    return None if change is None else change.change_class


def with_record(view: RunView, **changes: object) -> RunView:
    """Change fields of a view's run record.

    :param view: The view.
    :param **changes: The fields to set.
    :return: The changed view.
    """
    return dataclasses.replace(view, record={**view.record, **changes})


def with_snapshot(view: RunView, **changes: object) -> RunView:
    """Change fields of every snapshot in a view.

    :param view: The view.
    :param **changes: The fields to set; ``None`` removes a field.
    :return: The changed view.
    """
    snapshots: dict[str, Mapping[str, object]] = {}
    for receipt_id, snapshot in view.snapshots.items():
        record = {**snapshot, **changes}
        snapshots[receipt_id] = {k: v for k, v in record.items() if v is not None}
    return dataclasses.replace(view, snapshots=snapshots)


def with_finding(view: RunView, key: str, **changes: object) -> RunView:
    """Change fields of one finding in a view, or drop it.

    :param view: The view.
    :param key: The finding's key.
    :param **changes: The fields to set; ``drop=True`` removes the finding.
    :return: The changed view.
    """
    findings = dict(view.findings)
    if changes.pop("drop", False):
        del findings[key]
    else:
        findings[key] = {**findings[key], **changes}
    return dataclasses.replace(view, findings=findings)


def key_of(view: RunView, check_id: str, target: str = "") -> str:
    """Find a finding's key in a view.

    :param view: The view.
    :param check_id: The check.
    :param target: The finding's target.
    :return: The key.
    """
    (key,) = [
        k for k, f in view.findings.items() if f["check_id"] == check_id and f["target"] == target
    ]
    return key


# Page changes


def test_two_runs_of_unchanged_pages_have_no_changes(tmp_path: Path) -> None:
    """C-2 in miniature: identical pages, every id and fetch time different, no change."""
    first = dev(tmp_path, 12)
    second = renumbered(dev(tmp_path, 13))
    assert {r.id for r in first.receipts}.isdisjoint({r.id for r in second.receipts})
    assert {f.id for f in first.findings}.isdisjoint({f.id for f in second.findings})

    diff = diff_runs(stored(first, second), DEV_URL)

    assert diff.page_change is None
    assert diff.finding_changes == ()
    assert diff.empty


def test_an_article_edit_is_author_content(tmp_path: Path) -> None:
    """content_sha256 changed."""
    after = edited("wordpress-entry", "imitates the structure", "copies the structure")

    assert page_class(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after), WORDPRESS_URL) is (
        ChangeClass.AUTHOR_CONTENT
    )


def test_a_wordpress_metadata_edit_is_author_metadata(tmp_path: Path) -> None:
    """Only AUTHOR head fields changed."""
    after = edited(
        "wordpress-entry", 'og:site_name" content="Example Blog"', 'og:site_name" content="Blog"'
    )

    diff = diff_runs(stored(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after)), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.AUTHOR_METADATA
    (field,) = diff.page_change.fields
    assert (field.name, field.control) == ("meta:property:og:site_name", Actor.AUTHOR)
    assert diff.page_change.hashes == ("head_sha256",)


def test_a_wordpress_template_edit_is_author_frame(tmp_path: Path) -> None:
    """Content unchanged, only the frame changed, on a site the author runs (Session 6e)."""
    after = edited("wordpress-entry", "</body>", "<footer>new footer</footer></body>")

    diff = diff_runs(stored(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after)), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.AUTHOR_FRAME
    assert diff.page_change.hashes == ("frame_sha256",)


def test_a_wordpress_metadata_and_frame_edit_together_is_author_frame(tmp_path: Path) -> None:
    """One actor made both changes, so the class is the frame's, with the fields as evidence."""
    after = edited(
        "wordpress-entry", 'og:site_name" content="Example Blog"', 'og:site_name" content="Blog"'
    )
    after = after.replace(b"</body>", b"<footer>new footer</footer></body>")

    diff = diff_runs(stored(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after)), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.AUTHOR_FRAME
    assert [f.name for f in diff.page_change.fields] == ["meta:property:og:site_name"]
    assert diff.page_change.hashes == ("head_sha256", "frame_sha256")


def test_a_dev_template_edit_is_platform_rendering(tmp_path: Path) -> None:
    """On DEV, the frame is DEV's."""
    after = edited("dev-article", '<footer class="crayons-footer">', '<footer class="new-footer">')

    assert page_class(dev(tmp_path, 12), dev(tmp_path, 13, after), DEV_URL) is (
        ChangeClass.PLATFORM_RENDERING
    )


def test_an_owned_template_edit_is_unclassified(tmp_path: Path) -> None:
    """An owned page has no body, so its frame holds its text too: no class can be placed."""
    before = make_run(
        tmp_path, START, fixture("wordpress-entry"), url=WORDPRESS_URL, site=SiteType.OWNED
    )
    after = make_run(
        tmp_path,
        START.replace(hour=13),
        edited("wordpress-entry", "</body>", "<footer>x</footer></body>"),
        url=WORDPRESS_URL,
        site=SiteType.OWNED,
    )

    diff = diff_runs(stored(before, after), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("content_sha256" in reason for reason in diff.page_change.reasons)


def test_a_frame_change_where_nobody_is_known_to_control_the_frame_is_unclassified(
    tmp_path: Path,
) -> None:
    """A generic page's frame is nobody's known, even if a body were found."""
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13))
    first = with_snapshot(first, frame_sha256="f" * 64, extractor_selection="generic")
    second = with_snapshot(second, extractor_id="generic", extractor_selection="generic")
    first = with_snapshot(first, extractor_id="generic")

    diff = diff_views(first, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("frame" in reason for reason in diff.page_change.reasons)


def test_a_diff_across_the_author_frame_classifier_change_is_checker(tmp_path: Path) -> None:
    """Runs recorded under classifier 2+h1 and under this one compare as CHECKER first."""
    after = edited("wordpress-entry", "</body>", "<footer>new footer</footer></body>")
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after))
    first = with_record(first, classifier_version="2+h1")

    diff = diff_views(first, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.CHECKER


def test_a_dev_platform_field_change_is_platform_rendering(tmp_path: Path) -> None:
    """og:site_name is DEV's."""
    after = edited("dev-article", 'content="DEV Community"', 'content="DEV"')

    assert page_class(dev(tmp_path, 12), dev(tmp_path, 13, after), DEV_URL) is (
        ChangeClass.PLATFORM_RENDERING
    )


def test_a_dev_description_change_is_author_metadata(tmp_path: Path) -> None:
    """The front matter description sets the description fields."""
    after = edited(
        "dev-article",
        "A hand-written page that imitates a DEV article, for Cernis's tests.",
        "A new description.",
    )

    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, after)), DEV_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.AUTHOR_METADATA
    assert [f.name for f in diff.page_change.fields] == ["meta:name:description"]


def test_an_unknown_field_change_is_unclassified(tmp_path: Path) -> None:
    """DEV's title element mixes the author's title and DEV's suffix."""
    after = edited("dev-article", "Fixtures - DEV Community", "Fixtures - DEV")

    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, after)), DEV_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("UNKNOWN" in reason for reason in diff.page_change.reasons)


def test_two_classes_at_once_are_unclassified(tmp_path: Path) -> None:
    """Content and metadata changed together: no one cause."""
    after = edited(
        "wordpress-entry", 'imitates a WordPress entry." />', 'copies a WordPress entry." />'
    )
    after = after.replace(b"imitates", b"resembles")

    diff = diff_runs(stored(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after)), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("more than one class" in reason for reason in diff.page_change.reasons)


def test_a_page_without_a_body_is_unclassified_when_it_changes(tmp_path: Path) -> None:
    """The generic extractor finds no body, so a change cannot be placed."""
    before = make_run(tmp_path, START, fixture("wordpress-entry"), url=WORDPRESS_URL, site=None)
    after = make_run(
        tmp_path,
        START.replace(hour=13),
        edited("wordpress-entry", "</body>", "<footer>x</footer></body>"),
        url=WORDPRESS_URL,
        site=None,
    )

    diff = diff_runs(stored(before, after), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("content_sha256" in reason for reason in diff.page_change.reasons)


def test_a_head_change_without_head_fields_is_unclassified(tmp_path: Path) -> None:
    """A snapshot stored before Session 6c has only the head hash."""
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13))
    old = with_snapshot(first, head_fields=None, head_sha256="0" * 64)

    diff = diff_views(old, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("head fields" in reason for reason in diff.page_change.reasons)


def test_a_page_with_no_snapshot_is_unclassified(tmp_path: Path) -> None:
    """A run that could not read the page has nothing to compare."""
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13))
    unread = dataclasses.replace(first, snapshots={})

    diff = diff_views(unread, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("no snapshot" in reason for reason in diff.page_change.reasons)


@pytest.mark.parametrize(
    "change",
    [
        {"record": {"cernis_version": "0.0.9"}},
        {"record": {"classifier_version": "0+h0"}},
        {"snapshot": {"extractor_version": "1+n1"}},
    ],
    ids=["cernis", "classifier", "extractor"],
)
def test_a_checker_change_is_checker_first(
    tmp_path: Path, change: dict[str, dict[str, object]]
) -> None:
    """Even with the content changed too, a checker change is named first."""
    after = edited("wordpress-entry", "imitates the structure", "copies the structure")
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after))
    first = with_record(first, **change.get("record", {}))
    first = with_snapshot(first, **change.get("snapshot", {}))

    diff = diff_views(first, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.CHECKER


# Finding changes


def test_a_finding_that_appears_or_disappears_is_a_change(tmp_path: Path) -> None:
    """A key in one run and not the other."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")

    gone = diff_views(first, with_finding(second, key, drop=True), DEV_URL)
    new = diff_views(with_finding(first, key, drop=True), second, DEV_URL)

    assert [(c.key, c.kind) for c in gone.finding_changes] == [(key, "disappeared")]
    assert [(c.key, c.kind) for c in new.finding_changes] == [(key, "appeared")]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "NOT_DETERMINABLE"),
        ("defect", True),
        ("reason_code", "FETCH_FAILED"),
    ],
)
def test_a_finding_whose_status_defect_or_reason_changed_is_a_change(
    tmp_path: Path, field: str, value: object
) -> None:
    """Each compared field on its own."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")

    diff = diff_views(first, with_finding(second, key, **{field: value}), DEV_URL)

    (change,) = diff.finding_changes
    assert (change.kind, change.changed) == ("changed", (field,))


def test_a_changed_evidence_value_is_a_change_but_receipt_ids_are_not(tmp_path: Path) -> None:
    """Evidence compares values and locations only."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")
    stored_evidence = second.findings[key]["evidence"]
    assert isinstance(stored_evidence, list)
    evidence = [dict(item) for item in stored_evidence]
    renamed = [{**item, "receipt_id": "r-999"} for item in evidence]
    revalued = [{**item, "observed": "Another title"} for item in evidence]

    assert diff_views(first, with_finding(second, key, evidence=renamed), DEV_URL).empty
    (change,) = diff_views(
        first, with_finding(second, key, evidence=revalued), DEV_URL
    ).finding_changes
    assert change.changed == ("evidence",)


def test_a_check_version_change_is_a_checker_change(tmp_path: Path) -> None:
    """Whatever else changed, a new check version is CHECKER."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")

    diff = diff_views(
        first, with_finding(second, key, check_version="9", status="NOT_DETERMINABLE"), DEV_URL
    )

    (change,) = diff.finding_changes
    assert change.cause is Cause.CHECKER
    assert "check_version" in change.changed


# Causes


def test_a_finding_change_from_the_page_is_attributed_to_the_page_change(tmp_path: Path) -> None:
    """PAGE: evidence from the page's own receipt, carrying the page change's class."""
    after = edited(
        "dev-article",
        'property="og:type" content="article"',
        'property="og:type" content="website"',
    )

    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, after)), DEV_URL)

    changes = [c for c in diff.finding_changes if c.check_id == "peri.og.core"]
    assert changes
    assert all(c.cause is Cause.PAGE for c in changes)
    assert all(c.page_class is ChangeClass.PLATFORM_RENDERING for c in changes)


def test_a_finding_change_from_a_changed_resource_names_it(tmp_path: Path) -> None:
    """RESOURCE: the canonical target answered 200, then 404."""
    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, canonical=404)), DEV_URL)

    (change,) = [c for c in diff.finding_changes if c.target == DEV_CANONICAL]
    assert change.cause is Cause.RESOURCE
    assert change.resource_url == DEV_CANONICAL
    assert "status" in change.detail
    assert diff.page_change is None


def test_a_recommendation_follows_the_cause_of_the_finding_it_rests_on(tmp_path: Path) -> None:
    """A recommendation has no evidence of its own, only based_on."""
    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, canonical=404)), DEV_URL)

    (advice,) = [
        c for c in diff.finding_changes if c.target.startswith("epi.canonical.resolves.fix")
    ]
    assert (advice.kind, advice.cause, advice.resource_url) == (
        "appeared",
        Cause.RESOURCE,
        DEV_CANONICAL,
    )


def test_a_finding_change_with_unchanged_resources_has_an_unknown_cause(tmp_path: Path) -> None:
    """The resource's receipts are identical, so its change is not shown to be the cause."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "epi.canonical.resolves", DEV_CANONICAL)

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    (change,) = diff.finding_changes
    assert change.cause is Cause.UNKNOWN


def test_a_page_finding_change_with_no_page_change_has_an_unknown_cause(tmp_path: Path) -> None:
    """Evidence from the page, but the page did not change: nothing to attribute it to."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    (change,) = diff.finding_changes
    assert change.cause is Cause.UNKNOWN


def test_a_classifier_version_change_makes_every_finding_change_checker(tmp_path: Path) -> None:
    """The classifier changed between the runs, so it is named first."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")
    first = with_record(first, classifier_version="0+h0")

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    assert [c.cause for c in diff.finding_changes] == [Cause.CHECKER]


# Choosing runs


def test_the_default_is_the_two_most_recent_runs_with_the_url(tmp_path: Path) -> None:
    """Older runs, and runs of other pages, are passed over."""
    runs = [dev(tmp_path, 12), wordpress(tmp_path, 13), dev(tmp_path, 14), dev(tmp_path, 15)]

    diff = diff_runs(stored(*runs), DEV_URL)

    assert (diff.before.run_id, diff.after.run_id) == (runs[2].id, runs[3].id)


def test_fewer_than_two_runs_is_an_error(tmp_path: Path) -> None:
    """Nothing to compare."""
    with pytest.raises(DiffError, match="fewer than two"):
        diff_runs(stored(dev(tmp_path, 12), wordpress(tmp_path, 13)), DEV_URL)


def test_a_run_that_did_not_audit_the_url_is_an_error_naming_those_that_did(
    tmp_path: Path,
) -> None:
    """The message lists the runs to choose from."""
    runs = [dev(tmp_path, 12), wordpress(tmp_path, 13), dev(tmp_path, 14)]

    with pytest.raises(DiffError) as raised:
        diff_runs(stored(*runs), DEV_URL, before=runs[1].id)

    assert raised.value.usage
    assert runs[0].id in str(raised.value)
    assert runs[2].id in str(raised.value)


def test_chosen_runs_are_compared_in_the_order_given(tmp_path: Path) -> None:
    """--from and --to pick the pair."""
    runs = [dev(tmp_path, 12), dev(tmp_path, 13), dev(tmp_path, 14)]

    diff = diff_runs(stored(*runs), DEV_URL, before=runs[0].id, after=runs[2].id)

    assert (diff.before.run_id, diff.after.run_id) == (runs[0].id, runs[2].id)


# A run with new ids, for C-2 in miniature


def renumbered(run: Run) -> Run:
    """Give every receipt and finding a new id, and every fetch a later time.

    :param run: The run.
    :return: The same observations under other ids and times.
    """
    receipt_ids = {r.id: f"r-{100 + n}" for n, r in enumerate(run.receipts)}
    finding_ids = {f.id: f"f-{100 + n}" for n, f in enumerate(run.findings)}
    receipts = tuple(
        dataclasses.replace(r, id=receipt_ids[r.id], fetched_at=r.fetched_at + timedelta(hours=1))
        for r in run.receipts
    )
    snapshots = tuple(
        dataclasses.replace(s, receipt_id=receipt_ids[s.receipt_id]) for s in run.snapshots
    )
    findings = tuple(
        dataclasses.replace(
            f,
            id=finding_ids[f.id],
            evidence=tuple(
                Evidence(
                    receipt_id=receipt_ids[e.receipt_id],
                    location=e.location,
                    observed=e.observed,
                    searched_for=e.searched_for,
                )
                for e in f.evidence
            ),
            based_on=tuple(finding_ids[b] for b in f.based_on),
        )
        for f in run.findings
    )
    return dataclasses.replace(run, receipts=receipts, snapshots=snapshots, findings=findings)


# The Session 6c audit (aud_ZoO0lIpLnb)


def receipt_ids(view: RunView, url: str) -> list[str]:
    """List a view's receipts requested at a URL.

    :param view: The view.
    :param url: The URL, as requested.
    :return: The receipt ids, in run order.
    """
    return [rid for rid, r in view.receipts.items() if r["requested_url"] == url]


def with_receipt(view: RunView, receipt_id: str, **changes: object) -> RunView:
    """Change fields of one receipt in a view, or drop it.

    :param view: The view.
    :param receipt_id: The receipt.
    :param **changes: The fields to set; ``drop=True`` removes the receipt.
    :return: The changed view.
    """
    receipts = dict(view.receipts)
    if changes.pop("drop", False):
        del receipts[receipt_id]
    else:
        receipts[receipt_id] = {**receipts[receipt_id], **changes}
    return dataclasses.replace(view, receipts=receipts)


@pytest.mark.parametrize("order", ["reversed", "equal"])
def test_explicit_runs_must_be_two_in_stored_order(tmp_path: Path, order: str) -> None:
    """--from later than --to, or the same run twice, is a usage error, not a diff."""
    runs = [dev(tmp_path, 12), dev(tmp_path, 13)]
    before, after = (runs[1].id, runs[0].id) if order == "reversed" else (runs[0].id, runs[0].id)

    with pytest.raises(DiffError) as raised:
        diff_runs(stored(*runs), DEV_URL, before=before, after=after)

    assert raised.value.usage


def test_one_run_named_twice_is_not_a_diff(tmp_path: Path) -> None:
    """A single stored run cannot be compared with itself."""
    run = dev(tmp_path, 12)

    with pytest.raises(DiffError):
        diff_runs(stored(run), DEV_URL, before=run.id, after=run.id)


def test_one_sided_choices_pick_the_neighboring_runs(tmp_path: Path) -> None:
    """--to alone takes the run before it; --from alone takes the most recent run."""
    runs = [dev(tmp_path, 12), dev(tmp_path, 13), dev(tmp_path, 14)]
    entries = stored(*runs)

    to_only = diff_runs(entries, DEV_URL, after=runs[1].id)
    from_only = diff_runs(entries, DEV_URL, before=runs[0].id)

    assert (to_only.before.run_id, to_only.after.run_id) == (runs[0].id, runs[1].id)
    assert (from_only.before.run_id, from_only.after.run_id) == (runs[0].id, runs[2].id)
    with pytest.raises(DiffError, match="came before"):
        diff_runs(entries, DEV_URL, after=runs[0].id)
    with pytest.raises(DiffError, match="came after"):
        diff_runs(entries, DEV_URL, before=runs[2].id)


def test_a_cernis_version_change_alone_is_checker_and_says_the_page_did_not_change(
    tmp_path: Path,
) -> None:
    """The page change is CHECKER, and a finding from the page is CHECKER, never PAGE."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")
    first = with_record(first, cernis_version="0.0.9")

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.CHECKER
    assert diff.page_change.hashes == ()
    assert any("no snapshot hash changed" in r for r in diff.page_change.reasons)
    (change,) = diff.finding_changes
    assert change.cause is Cause.CHECKER


def test_an_extractor_change_makes_a_page_finding_change_checker(tmp_path: Path) -> None:
    """A new extractor version is the checker, not the page."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")
    first = with_snapshot(first, extractor_version="1+n1")

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    (change,) = diff.finding_changes
    assert (change.cause, change.page_class) == (Cause.CHECKER, None)


def test_an_appeared_finding_whose_check_version_differs_is_checker(tmp_path: Path) -> None:
    """The earlier run's findings of the same check have another version."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "peri.title")
    sibling = {**first.findings[key], "key": "sibling", "target": "x"}
    kept = {k: f for k, f in first.findings.items() if k != key}
    before = dataclasses.replace(first, findings={**kept, "sibling": sibling})

    diff = diff_views(before, with_finding(second, key, check_version="9"), DEV_URL)

    (change,) = [c for c in diff.finding_changes if c.key == key]
    assert (change.kind, change.cause) == ("appeared", Cause.CHECKER)


def test_a_resource_fetched_in_only_one_run_is_not_shown_to_have_changed(tmp_path: Path) -> None:
    """No receipt in one run means nothing to compare: UNKNOWN, with the reason."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "epi.canonical.resolves", DEV_CANONICAL)
    for rid in receipt_ids(first, DEV_CANONICAL):
        first = with_receipt(first, rid, drop=True)

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    (change,) = diff.finding_changes
    assert change.cause is Cause.UNKNOWN
    assert "fetched in only one run" in change.detail


def test_the_receipt_a_finding_cites_is_compared_not_the_last_fetch(tmp_path: Path) -> None:
    """A later, uncited fetch of the same URL is not the finding's evidence."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "epi.canonical.resolves", DEV_CANONICAL)
    (cited,) = receipt_ids(second, DEV_CANONICAL)
    extra = {**second.receipts[cited], "id": "r-extra", "status_code": 500}
    second = dataclasses.replace(second, receipts={**second.receipts, "r-extra": extra})

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    (change,) = diff.finding_changes
    assert change.cause is Cause.UNKNOWN


def test_a_304_with_the_same_body_is_not_a_resource_change(tmp_path: Path) -> None:
    """Revalidation is not a change: the cached body's hash is the same."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    key = key_of(first, "epi.canonical.resolves", DEV_CANONICAL)
    (rid,) = receipt_ids(second, DEV_CANONICAL)
    second = with_receipt(second, rid, status_code=304)

    diff = diff_views(first, with_finding(second, key, defect=True), DEV_URL)

    (change,) = diff.finding_changes
    assert change.cause is Cause.UNKNOWN


def test_a_page_and_a_resource_both_changed_is_unknown_naming_both(tmp_path: Path) -> None:
    """Two shown candidates are not one cause."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13, canonical=404))
    second = with_snapshot(second, frame_sha256="f" * 64)
    key = key_of(second, "epi.canonical.resolves", DEV_CANONICAL)
    (page_receipt,) = receipt_ids(second, DEV_URL)
    stored_evidence = second.findings[key]["evidence"]
    assert isinstance(stored_evidence, list)
    from_page = {"receipt_id": page_receipt, "location": "page", "observed": "x"}
    second = with_finding(second, key, evidence=[*stored_evidence, from_page])

    diff = diff_views(first, second, DEV_URL)

    (change,) = [c for c in diff.finding_changes if c.key == key]
    assert change.cause is Cause.UNKNOWN
    assert DEV_CANONICAL in change.detail
    assert "PLATFORM_RENDERING" in change.detail


def test_a_recommendation_resting_on_changes_with_different_causes_is_unknown(
    tmp_path: Path,
) -> None:
    """One cause is not chosen from several by list order."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13, canonical=404))
    title = key_of(second, "peri.title")
    second = with_finding(second, title, defect=True)
    (advice_key,) = [
        k
        for k, f in second.findings.items()
        if str(f["target"]).startswith("epi.canonical.resolves.fix")
    ]
    based = second.findings[advice_key]["based_on"]
    assert isinstance(based, list)
    second = with_finding(second, advice_key, based_on=[*based, second.findings[title]["id"]])

    diff = diff_views(first, second, DEV_URL)

    (advice,) = [c for c in diff.finding_changes if c.key == advice_key]
    assert advice.cause is Cause.UNKNOWN


def test_no_snapshot_in_either_run_names_both_runs(tmp_path: Path) -> None:
    """Nothing was read whole in either run; the reason says so of both."""
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13))
    first = dataclasses.replace(first, snapshots={})
    second = dataclasses.replace(second, snapshots={})

    diff = diff_views(first, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    (reason,) = diff.page_change.reasons
    assert first.run_id in reason
    assert second.run_id in reason


def test_a_head_hash_change_with_no_field_change_is_unclassified(tmp_path: Path) -> None:
    """A stored hash that disagrees with its fields is placed nowhere, without failing."""
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13))
    first = with_snapshot(first, head_sha256="0" * 64)

    diff = diff_views(first, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED


def test_the_diff_names_the_version_of_the_control_it_used(tmp_path: Path) -> None:
    """A control file given by the caller is the one the version names."""
    first, second = views(dev(tmp_path, 12), dev(tmp_path, 13))
    sites = ("dev", "wordpress", "owned", "generic")
    control = load_head_fields(
        "version = 7\n"
        + "".join(f'[site.{site}]\ndefault = "UNKNOWN"\nsource = "x"\n' for site in sites)
    )

    diff = diff_views(first, second, DEV_URL, control=control)

    assert diff.classifier_version == f"{HISTORY_VERSION}+h7"


def test_a_page_supplied_field_name_is_escaped_in_markdown(tmp_path: Path) -> None:
    """A meta name is the page's text, so it cannot write Markdown into the diff."""
    after = edited(
        "wordpress-entry",
        'og:site_name" content="Example Blog"',
        'og:site_name" content="Example Blog" /><meta name="*x*" content="y"',
    )

    diff = diff_runs(stored(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after)), WORDPRESS_URL)

    assert "Head field meta:name:\\*x\\*" in format_diff_markdown(diff)


# The Session 6e audit (aud_1vdgpbq7t4)


def test_a_dev_platform_field_and_frame_change_give_both_reasons(tmp_path: Path) -> None:
    """One class, PLATFORM_RENDERING, but each contributing change is named."""
    after = edited("dev-article", 'content="DEV Community"', 'content="DEV"')
    after = after.replace(b'<footer class="crayons-footer">', b'<footer class="new-footer">')

    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, after)), DEV_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.PLATFORM_RENDERING
    assert any("platform controls" in r for r in diff.page_change.reasons)
    assert any("frame_sha256" in r for r in diff.page_change.reasons)


def test_a_head_hash_change_with_no_field_change_is_unclassified_with_a_frame_change(
    tmp_path: Path,
) -> None:
    """The anomaly is not hidden by a frame change on an author-controlled site."""
    after = edited("wordpress-entry", "</body>", "<footer>new footer</footer></body>")
    first, second = views(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after))
    first = with_snapshot(first, head_sha256="0" * 64)

    diff = diff_views(first, second, WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("no head field did" in r for r in diff.page_change.reasons)


def test_a_wordpress_content_and_frame_edit_together_is_unclassified(tmp_path: Path) -> None:
    """An article edit is never folded into a frame change (Session 6e, decision 3)."""
    after = edited("wordpress-entry", "imitates the structure", "copies the structure")
    after = after.replace(b"</body>", b"<footer>new footer</footer></body>")

    diff = diff_runs(stored(wordpress(tmp_path, 12), wordpress(tmp_path, 13, after)), WORDPRESS_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("more than one class" in r for r in diff.page_change.reasons)


def test_a_dev_unknown_field_and_frame_change_is_unclassified(tmp_path: Path) -> None:
    """An UNKNOWN field decides first, whatever else changed."""
    after = edited("dev-article", "Fixtures - DEV Community", "Fixtures - DEV")
    after = after.replace(b'<footer class="crayons-footer">', b'<footer class="new-footer">')

    diff = diff_runs(stored(dev(tmp_path, 12), dev(tmp_path, 13, after)), DEV_URL)

    assert diff.page_change is not None
    assert diff.page_change.change_class is ChangeClass.UNCLASSIFIED
    assert any("UNKNOWN" in r for r in diff.page_change.reasons)
