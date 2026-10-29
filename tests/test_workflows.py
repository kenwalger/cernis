"""Tests that lock the invariants of the GitHub Actions workflows.

The workflows are read as text, line by line, so no YAML library is needed. Each
test names the rule it protects; the rules come from the Session 2 audit
(``docs/sessions/SESSION-02.md``).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
PUBLISH = WORKFLOWS / "publish.yml"
RELEASING = ROOT / "docs" / "RELEASING.md"
CLAUDE_MD = ROOT / "CLAUDE.md"

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s+#\s+v\d+\.\d+\.\d+$")
JOB = re.compile(r"^  ([\w-]+):\s*$")
TAG_TEST = re.compile(r'\[\[ ! "\$TAG" =~ (\S+) \]\]')


def _lines(path: Path) -> list[str]:
    """Read a file as a list of lines.

    :param path: The file to read.
    :return: The lines, without line endings.
    """
    return path.read_text(encoding="utf-8").splitlines()


def _jobs(path: Path) -> dict[str, list[str]]:
    """Split a workflow's ``jobs:`` section into one block of lines per job.

    :param path: The workflow file.
    :return: A mapping of job id to the lines of that job.
    """
    jobs: dict[str, list[str]] = {}
    current: list[str] | None = None
    in_jobs = False
    for line in _lines(path):
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        match = JOB.match(line)
        if match:
            current = jobs.setdefault(match.group(1), [])
        elif current is not None:
            current.append(line)
    return jobs


def _run_blocks(path: Path) -> list[str]:
    """Collect the shell script of every ``run:`` step in a workflow.

    :param path: The workflow file.
    :return: One string per ``run:`` step, holding its script.
    """
    blocks: list[str] = []
    lines = _lines(path)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith(("run:", "- run:")):
            continue
        value = stripped.split("run:", 1)[1].strip()
        if value not in ("|", ">"):
            blocks.append(value)
            continue
        indent = len(line) - len(stripped)
        body: list[str] = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        blocks.append("\n".join(body))
    return blocks


def _check_list() -> list[str]:
    """Read the numbered check list from the Tests section of ``CLAUDE.md``.

    :return: The commands, in order.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    section = text.split("## Tests", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\s+\d+\.\s+`([^`]+)`", section, flags=re.MULTILINE)


def _tag_pattern() -> re.Pattern[str]:
    """Extract the release tag pattern that ``publish.yml`` tests in bash.

    The pattern is a plain extended regular expression, which Python reads the
    same way.

    :return: The compiled pattern.
    """
    match = TAG_TEST.search(PUBLISH.read_text(encoding="utf-8"))
    assert match is not None, "publish.yml no longer tests the tag against a pattern"
    return re.compile(match.group(1))


ALL_WORKFLOWS = sorted(WORKFLOWS.glob("*.yml"))


def test_workflows_exist() -> None:
    """Both workflows are present, so the tests below cannot pass vacuously."""
    assert CI in ALL_WORKFLOWS
    assert PUBLISH in ALL_WORKFLOWS


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_remote_actions_are_pinned_to_a_commit_with_a_version_comment(workflow: Path) -> None:
    """Every remote action is pinned to a full commit SHA and names its release.

    :param workflow: The workflow file under test.
    """
    for number, line in enumerate(_lines(workflow), start=1):
        match = USES.match(line)
        if match is None or match.group(1).startswith("./"):
            continue
        where = f"{workflow.name}:{number}"
        assert PINNED.match(match.group(1)), f"{where} is not pinned to a commit SHA"
        assert VERSION_COMMENT.match(match.group(2)), f"{where} has no '# vX.Y.Z' comment"


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_no_expression_is_interpolated_into_a_script(workflow: Path) -> None:
    """No ``${{ }}`` expression appears inside a ``run:`` script.

    Values reach scripts through ``env:``, so a crafted tag or branch name cannot
    become shell code.

    :param workflow: The workflow file under test.
    """
    for block in _run_blocks(workflow):
        assert "${{" not in block, f"{workflow.name} interpolates an expression: {block!r}"


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_no_privileged_pull_request_trigger(workflow: Path) -> None:
    """No workflow runs untrusted pull request code with a privileged token.

    :param workflow: The workflow file under test.
    """
    assert "pull_request_target" not in workflow.read_text(encoding="utf-8")


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_every_checkout_drops_its_credentials(workflow: Path) -> None:
    """Every checkout sets ``persist-credentials: false``; no job pushes.

    :param workflow: The workflow file under test.
    """
    text = workflow.read_text(encoding="utf-8")
    checkouts = text.count("uses: actions/checkout@")
    assert text.count("persist-credentials: false") == checkouts


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_every_runner_job_has_a_timeout(workflow: Path) -> None:
    """Every job that runs on a runner has a ``timeout-minutes`` limit.

    :param workflow: The workflow file under test.
    """
    for job, lines in _jobs(workflow).items():
        if any(line.strip().startswith("runs-on:") for line in lines):
            assert any("timeout-minutes:" in line for line in lines), f"{workflow.name}: {job}"


def test_ci_runs_the_claude_md_check_list_in_order() -> None:
    """CI runs every command of the ``CLAUDE.md`` check list, in the same order."""
    expected = _check_list()
    assert len(expected) == 6
    assert [block for block in _run_blocks(CI) if block in expected] == expected


def test_ci_is_read_only_and_refuses_a_stale_lock() -> None:
    """CI grants only ``contents: read`` and runs uv with ``UV_LOCKED``."""
    text = CI.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text
    assert "write" not in text
    assert 'UV_LOCKED: "1"' in text


def test_ci_is_callable_by_the_publish_workflow() -> None:
    """``ci.yml`` accepts ``workflow_call``, which the publish workflow relies on."""
    assert re.search(r"^  workflow_call:", CI.read_text(encoding="utf-8"), flags=re.MULTILINE)


def test_concurrency_never_cancels_main_or_a_publish() -> None:
    """CI runs on ``main`` and started publishes are never cancelled.

    The CI group includes the event name, so a release's call to CI cannot cancel,
    or be cancelled by, the push run for the same tag.
    """
    ci = CI.read_text(encoding="utf-8")
    assert "group: ci-${{ github.event_name }}-${{ github.ref }}" in ci
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}" in ci

    publish = PUBLISH.read_text(encoding="utf-8")
    assert "concurrency:\n  group: publish\n  cancel-in-progress: false\n" in publish


def test_publish_triggers_only_on_a_published_release() -> None:
    """The publish workflow has a single trigger: a published release."""
    text = PUBLISH.read_text(encoding="utf-8")
    trigger = text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert trigger == "  release:\n    types: [published]"


def test_publish_grants_permissions_per_job_only() -> None:
    """``publish.yml`` grants nothing at the top level and ``id-token`` to one job."""
    text = PUBLISH.read_text(encoding="utf-8")
    assert "\npermissions: {}\n" in text

    jobs = _jobs(PUBLISH)
    holders = [job for job, lines in jobs.items() if any("id-token:" in x for x in lines)]
    assert holders == ["publish"]
    assert "      id-token: write" in jobs["publish"]
    assert not any("contents:" in line for line in jobs["publish"])
    assert any("environment:" in line for line in jobs["publish"])


def test_publish_builds_only_after_the_check_list_passes() -> None:
    """The build job needs the reusable CI job, and publishing needs the build."""
    jobs = _jobs(PUBLISH)
    assert "    uses: ./.github/workflows/ci.yml" in jobs["checks"]
    assert "    needs: checks" in jobs["build"]
    assert "    needs: build" in jobs["publish"]


def test_release_build_has_no_cache_checks_main_and_checks_files() -> None:
    """The release build has no cache, checks main, and checks the built files."""
    build = "\n".join(_jobs(PUBLISH)["build"])
    assert "enable-cache: false" in build
    assert "fetch-depth: 0" in build
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in build
    assert 'expected="cernis-$version-py3-none-any.whl cernis-$version.tar.gz"' in build
    assert build.index("uv build --no-sources") < build.index("actions/upload-artifact@")


@pytest.mark.parametrize("tag", ["v0.1.0", "v1.0.0", "v10.20.30", "v0.0.0"])
def test_release_tag_pattern_accepts(tag: str) -> None:
    """A plain ``vX.Y.Z`` tag passes the release tag check.

    :param tag: A tag that must be accepted.
    """
    assert _tag_pattern().search(tag)


@pytest.mark.parametrize(
    "tag",
    ["0.1.0", "v0.1", "v01.0.0", "v1.00.0", "v1.0.00", "v1.0.0rc1", "v0.1.0.dev0", "v1.0.0\nx"],
)
def test_release_tag_pattern_rejects(tag: str) -> None:
    """Anything other than a plain ``vX.Y.Z`` tag fails the release tag check.

    Leading zeros are rejected because PEP 440 normalizes them, so the built file
    names would not match the tag.

    :param tag: A tag that must be rejected.
    """
    assert not _tag_pattern().search(tag)


def test_releasing_doc_matches_the_trusted_publisher() -> None:
    """``RELEASING.md`` names the workflow file and environment that publish."""
    doc = RELEASING.read_text(encoding="utf-8")
    assert f"Workflow name: `{PUBLISH.name}`" in doc
    assert "Environment name: `pypi`" in doc
    assert "      name: pypi" in _jobs(PUBLISH)["publish"]
