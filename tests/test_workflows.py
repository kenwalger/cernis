"""Tests that lock the invariants of the GitHub Actions workflows.

The workflows are read as text, line by line, so no YAML library is needed. Each
test names the rule it protects; the rules come from the Session 2 audits
(``docs/sessions/SESSION-02.md``).

The release gates in ``publish.yml`` are also run: each gate's script is taken from
the workflow and executed under bash against local inputs, so a test fails when a
gate stops rejecting what it should. None of this touches the network.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

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
STEP = re.compile(r"^      - ")
STEP_TITLE = re.compile(r"^      - (?:name|uses): (.+)$")
# A YAML block scalar header: | or >, then an optional indent digit and chomping sign.
BLOCK_SCALAR = re.compile(r"^[|>](?:[1-9][+-]?|[+-][1-9]?)?$")

TAG_STEP = "Check the release tag matches the package version"
COMMIT_STEP = "Check the release commit is the tag and is on main"
DIST_STEP = "Check the distributions"
WHEEL_STEP = "Check the wheel installs and runs"

# Folders of Windows launchers that start WSL instead of running a bash script here.
WSL_LAUNCHER_DIRS = {"system32", "windowsapps"}

ALL_WORKFLOWS = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


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


def _steps(job: list[str]) -> list[list[str]]:
    """Split a job's lines into one block of lines per step.

    :param job: The lines of one job, as returned by :func:`_jobs`.
    :return: The lines of each step, in order.
    """
    steps: list[list[str]] = []
    for line in job:
        if STEP.match(line):
            steps.append([line])
        elif steps and (not line.strip() or line.startswith("        ")):
            steps[-1].append(line)
        elif steps:
            break
    return steps


def _run_blocks_in(lines: list[str]) -> list[str]:
    """Collect the shell script of every ``run:`` key in a block of lines.

    :param lines: Workflow lines.
    :return: One string per ``run:`` key, holding its script.
    """
    blocks: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith(("run:", "- run:")):
            continue
        value = stripped.split("run:", 1)[1].strip()
        if not BLOCK_SCALAR.match(value):
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


def _run_blocks(path: Path) -> list[str]:
    """Collect the shell script of every ``run:`` step in a workflow.

    :param path: The workflow file.
    :return: One string per ``run:`` step, holding its script.
    """
    return _run_blocks_in(_lines(path))


def _build_step(name: str) -> list[str]:
    """Find a named step of the ``build`` job in ``publish.yml``.

    :param name: The step's ``name:`` value.
    :return: The lines of the step.
    :raises AssertionError: If the build job has no step with that name.
    """
    for step in _steps(_jobs(PUBLISH)["build"]):
        if step[0] == f"      - name: {name}":
            return step
    raise AssertionError(f"publish.yml build job has no step named {name!r}")


def _check_list() -> list[str]:
    """Read the numbered check list from the Tests section of ``CLAUDE.md``.

    :return: The commands, in order.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    section = text.split("## Tests", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\s+\d+\.\s+`([^`]+)`", section, flags=re.MULTILINE)


def _git_env(home: Path) -> dict[str, str]:
    """Build an environment where git ignores the user's and the system's config.

    :param home: A directory for an empty global config file.
    :return: The environment.
    """
    config = home / "gitconfig"
    config.touch()
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(config),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }


def _git_for_windows_roots() -> list[Path]:
    """List the folders where Git for Windows may be installed.

    The first is the one the ``git`` on ``PATH`` belongs to, found from
    ``git --exec-path`` (``<root>/mingw64/libexec/git-core``); the rest are the
    standard install locations.

    :return: Candidate install roots, most likely first.
    """
    roots: list[Path] = []
    try:
        exec_path = subprocess.run(
            ["git", "--exec-path"], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        exec_path = ""
    if exec_path and len(Path(exec_path).parents) > 2:
        roots.append(Path(exec_path).parents[2])
    for variable, folder in (
        ("ProgramFiles", "Git"),
        ("ProgramFiles(x86)", "Git"),
        ("LOCALAPPDATA", "Programs/Git"),
    ):
        base = os.environ.get(variable)
        if base:
            roots.append(Path(base) / folder)
    return roots


def _bash_candidates() -> list[str]:
    """List the bash executables worth trying, most likely first.

    On Windows these are Git for Windows' bash, then a ``bash`` on ``PATH`` that is
    not a WSL launcher; elsewhere, the ``bash`` on ``PATH``.

    :return: Candidate paths, not yet checked.
    """
    found = shutil.which("bash")
    if sys.platform != "win32":
        return [found] if found else []
    candidates = [
        str(root / folder / "bash.exe")
        for root in _git_for_windows_roots()
        for folder in ("bin", "usr/bin")
    ]
    if found and PureWindowsPath(found).parent.name.lower() not in WSL_LAUNCHER_DIRS:
        candidates.append(found)
    return candidates


def _bash_works(path: str) -> bool:
    """Check that a bash executable runs a script here.

    :param path: The executable to try.
    :return: Whether ``bash -c "echo ok"`` printed ``ok`` and exited 0.
    """
    try:
        result = subprocess.run(
            [path, "-c", "echo ok"], capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "ok"


def _find_bash() -> str | None:
    """Find a bash that can run the release gates.

    :return: The first candidate that exists and works, or ``None``.
    """
    for candidate in _bash_candidates():
        if Path(candidate).is_file() and _bash_works(candidate):
            return candidate
    return None


def _in_ci() -> bool:
    """Tell whether the tests run in CI, where the ``CI`` variable is set.

    :return: Whether ``CI`` is set to anything but empty, ``0``, or ``false``.
    """
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _require_bash() -> str:
    """Return a usable bash, or skip the test, or fail it in CI.

    Outside CI a missing bash skips the test with the reason. In CI it fails, so
    the release gate tests can never silently stop running.

    :return: The path to a working bash.
    """
    found = _find_bash()
    if found is None:
        reason = (
            "no usable bash for the release gate tests (on Windows, install Git for"
            " Windows; the System32 and WindowsApps bash launchers start WSL)"
        )
        if _in_ci():
            pytest.fail(reason)
        pytest.skip(reason)
    return found


@pytest.fixture(scope="session")
def bash() -> str:
    """Find and check bash once per test session.

    :return: The path to a working bash.
    """
    return _require_bash()


def _run_gate(
    bash: str, name: str, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one release gate from ``publish.yml`` under bash, as GitHub runs it.

    ``uv`` is replaced by a shell function that prints ``$FAKE_VERSION``, so the
    gate sees that as the package version without uv or a project being present.

    :param bash: The bash executable.
    :param name: The step's ``name:`` value.
    :param cwd: The working directory.
    :param env: The environment, including ``TAG`` and ``FAKE_VERSION`` as needed.
    :return: The finished process, with text output captured.
    """
    scripts = _run_blocks_in(_build_step(name))
    assert len(scripts) == 1, f"step {name!r} has {len(scripts)} run scripts"
    script = "uv() { printf '%s\\n' \"$FAKE_VERSION\"; }\n" + scripts[0]
    return subprocess.run(
        [bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_workflows_exist() -> None:
    """Both workflows are present, so the tests below cannot pass vacuously."""
    assert CI in ALL_WORKFLOWS
    assert PUBLISH in ALL_WORKFLOWS


def test_run_blocks_reads_every_block_scalar_style(tmp_path: Path) -> None:
    """The ``run:`` reader sees the body of ``|-``, ``>+``, and ``|2`` scripts too.

    :param tmp_path: A temporary directory.
    """
    workflow = tmp_path / "w.yml"
    workflow.write_text(
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - run: |-\n"
        "          echo one\n"
        "      - run: >+\n"
        "          echo two\n"
        "      - run: |2\n"
        "          echo three\n"
        "      - run: echo four\n",
        encoding="utf-8",
    )
    blocks = [block.strip() for block in _run_blocks(workflow)]
    assert blocks == ["echo one", "echo two", "echo three", "echo four"]


@pytest.mark.parametrize(
    "launcher",
    [
        r"C:\Windows\System32\bash.exe",
        r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\bash.exe",
    ],
)
def test_bash_finder_never_picks_a_wsl_launcher(
    launcher: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows, a WSL launcher found on ``PATH`` is not a candidate.

    :param launcher: A WSL launcher path that ``shutil.which`` might return.
    :param monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda _: launcher)
    monkeypatch.setattr(sys.modules[__name__], "_git_for_windows_roots", lambda: [])
    assert _bash_candidates() == []


def test_bash_finder_tries_git_for_windows_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows, Git for Windows' bash comes before any other ``bash`` on ``PATH``.

    :param monkeypatch: The pytest monkeypatch fixture.
    """
    root = Path("C:/Git")
    other = r"C:\msys64\usr\bin\bash.exe"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda _: other)
    monkeypatch.setattr(sys.modules[__name__], "_git_for_windows_roots", lambda: [root])
    assert _bash_candidates() == [
        str(root / "bin" / "bash.exe"),
        str(root / "usr/bin" / "bash.exe"),
        other,
    ]


def test_bash_finder_uses_path_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside Windows, the ``bash`` on ``PATH`` is the only candidate.

    :param monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/bash")
    assert _bash_candidates() == ["/usr/bin/bash"]


def test_bash_check_rejects_an_executable_that_does_not_run(tmp_path: Path) -> None:
    """A candidate that cannot run ``bash -c "echo ok"`` is not usable.

    :param tmp_path: A temporary directory.
    """
    assert not _bash_works(str(tmp_path / "no-such-bash"))


@pytest.mark.parametrize(
    ("ci", "outcome"),
    [(None, "skip"), ("", "skip"), ("false", "skip"), ("true", "fail"), ("1", "fail")],
)
def test_missing_bash_skips_locally_and_fails_in_ci(
    ci: str | None, outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no usable bash, the gate tests skip, except in CI, where they fail.

    :param ci: The value of the ``CI`` variable, or ``None`` when it is unset.
    :param outcome: ``skip`` or ``fail``.
    :param monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(sys.modules[__name__], "_find_bash", lambda: None)
    if ci is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci)
    expected = pytest.skip.Exception if outcome == "skip" else pytest.fail.Exception
    with pytest.raises(expected, match="no usable bash"):
        _require_bash()


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
@pytest.mark.parametrize("trigger", ["pull_request_target", "workflow_run"])
def test_no_privileged_trigger(workflow: Path, trigger: str) -> None:
    """No workflow uses a trigger that runs with secrets after untrusted code.

    :param workflow: The workflow file under test.
    :param trigger: A privileged trigger that must not appear.
    """
    assert trigger not in workflow.read_text(encoding="utf-8")


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_every_checkout_drops_its_credentials(workflow: Path) -> None:
    """Every checkout step sets ``persist-credentials: false``; no job pushes.

    :param workflow: The workflow file under test.
    """
    checkouts = [
        step
        for job in _jobs(workflow).values()
        for step in _steps(job)
        if "uses: actions/checkout@" in step[0]
    ]
    assert checkouts, f"{workflow.name} has no checkout step"
    for step in checkouts:
        assert any(line.strip() == "persist-credentials: false" for line in step)


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_no_job_or_step_can_be_skipped_or_ignored(workflow: Path) -> None:
    """No ``if:`` condition and no ``continue-on-error`` anywhere.

    Either one could let a failed check be skipped or ignored while ``needs:``
    still reads as a gate.

    :param workflow: The workflow file under test.
    """
    for number, line in enumerate(_lines(workflow), start=1):
        stripped = line.strip().removeprefix("- ")
        assert not stripped.startswith("if:"), f"{workflow.name}:{number}"
        assert "continue-on-error" not in line, f"{workflow.name}:{number}"


@pytest.mark.parametrize("workflow", ALL_WORKFLOWS, ids=lambda p: p.name)
def test_every_runner_job_has_a_timeout(workflow: Path) -> None:
    """Every job that runs on a runner has a ``timeout-minutes`` limit.

    :param workflow: The workflow file under test.
    """
    for job, lines in _jobs(workflow).items():
        if any(line.strip().startswith("runs-on:") for line in lines):
            assert any("timeout-minutes:" in line for line in lines), f"{workflow.name}: {job}"


def test_ci_runs_exactly_the_claude_md_check_list_in_order() -> None:
    """CI runs every command of the ``CLAUDE.md`` check list, in order, and nothing else."""
    expected = _check_list()
    assert len(expected) == 6
    assert _run_blocks(CI) == expected


def test_ci_is_read_only_and_refuses_a_stale_lock() -> None:
    """CI grants only ``contents: read`` and runs uv with ``UV_LOCKED``."""
    text = CI.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text
    assert "write" not in text
    assert 'UV_LOCKED: "1"' in text


def test_ci_is_callable_by_the_publish_workflow() -> None:
    """``ci.yml`` accepts ``workflow_call``, which the publish workflow relies on."""
    assert re.search(r"^  workflow_call:", CI.read_text(encoding="utf-8"), flags=re.MULTILINE)


def test_concurrency_never_cancels_main_a_release_or_a_publish() -> None:
    """CI runs on ``main`` and on tags, and started publishes, are never cancelled.

    The CI group includes the event name, so a release's call to CI cannot cancel,
    or be cancelled by, the push run for the same tag.
    """
    ci = CI.read_text(encoding="utf-8")
    assert "group: ci-${{ github.event_name }}-${{ github.ref }}" in ci
    assert (
        "cancel-in-progress: ${{ github.ref != 'refs/heads/main'"
        " && !startsWith(github.ref, 'refs/tags/') }}"
    ) in ci

    publish = PUBLISH.read_text(encoding="utf-8")
    assert "concurrency:\n  group: publish\n  cancel-in-progress: false\n" in publish


def test_publish_triggers_only_on_a_published_release() -> None:
    """The publish workflow has a single trigger: a published release."""
    text = PUBLISH.read_text(encoding="utf-8")
    trigger = text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert trigger == "  release:\n    types: [published]"


def test_publish_grants_permissions_per_job_only() -> None:
    """``publish.yml`` grants nothing at the top level and ``id-token`` to one job.

    The only write permission in the file is ``id-token: write`` in ``publish``.
    """
    text = PUBLISH.read_text(encoding="utf-8")
    assert "\npermissions: {}\n" in text
    writes = [line for line in _lines(PUBLISH) if re.search(r":\s*write\b", line)]
    assert writes == ["      id-token: write"]

    jobs = _jobs(PUBLISH)
    assert "      id-token: write" in jobs["publish"]
    assert not any("contents:" in line for line in jobs["publish"])
    assert any("environment:" in line for line in jobs["publish"])


def test_publish_builds_only_after_the_check_list_passes() -> None:
    """The build job needs the reusable CI job, and publishing needs the build."""
    jobs = _jobs(PUBLISH)
    assert "    uses: ./.github/workflows/ci.yml" in jobs["checks"]
    assert "    needs: checks" in jobs["build"]
    assert "    needs: build" in jobs["publish"]


def test_release_build_runs_every_gate_in_order() -> None:
    """The build job checks the tag and commit, builds, checks the files, then uploads."""
    titles = [
        match.group(1)
        for line in _jobs(PUBLISH)["build"]
        if (match := STEP_TITLE.match(line)) is not None
    ]
    assert [title.split("@")[0] for title in titles] == [
        "actions/checkout",
        "astral-sh/setup-uv",
        TAG_STEP,
        COMMIT_STEP,
        "Build sdist and wheel",
        DIST_STEP,
        WHEEL_STEP,
        "Record the release commit and file hashes",
        "actions/upload-artifact",
    ]


def test_release_build_has_no_cache_and_full_history() -> None:
    """The release build has no uv cache and fetches every branch and tag."""
    build = "\n".join(_jobs(PUBLISH)["build"])
    assert "enable-cache: false" in build
    assert "fetch-depth: 0" in build
    assert "uv build --no-sources" in build


def test_release_wheel_is_run_from_an_isolated_environment() -> None:
    """The built wheel, not the source tree, is installed and asked for its version."""
    (script,) = _run_blocks_in(_build_step(WHEEL_STEP))
    assert '--isolated --no-project --with "dist/cernis-$version-py3-none-any.whl"' in script
    assert '"cernis $version"' in script


@pytest.mark.parametrize("tag", ["v0.1.0", "v1.0.0", "v10.20.30", "v0.0.0"])
def test_release_tag_gate_accepts(bash: str, tag: str, tmp_path: Path) -> None:
    """A plain ``vX.Y.Z`` tag equal to ``v`` plus the version passes.

    :param bash: A working bash.
    :param tag: A tag that must be accepted.
    :param tmp_path: A temporary directory.
    """
    env = {**os.environ, "TAG": tag, "FAKE_VERSION": tag.removeprefix("v")}
    result = _run_gate(bash, TAG_STEP, tmp_path, env)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "tag",
    ["0.1.0", "v0.1", "v01.0.0", "v1.00.0", "v1.0.00", "v1.0.0rc1", "v0.1.0.dev0", "v1.0.0\nx"],
)
def test_release_tag_gate_rejects_the_form(bash: str, tag: str, tmp_path: Path) -> None:
    """Anything other than a plain ``vX.Y.Z`` tag fails, even when it matches the version.

    Leading zeros are rejected because PEP 440 normalizes them, so the built file
    names would not match the tag.

    :param bash: A working bash.
    :param tag: A tag that must be rejected.
    :param tmp_path: A temporary directory.
    """
    env = {**os.environ, "TAG": tag, "FAKE_VERSION": tag.removeprefix("v")}
    result = _run_gate(bash, TAG_STEP, tmp_path, env)
    assert result.returncode == 1
    assert "is not of the form vX.Y.Z" in result.stdout


def test_release_tag_gate_rejects_a_version_mismatch(bash: str, tmp_path: Path) -> None:
    """A well-formed tag that differs from the package version fails.

    :param bash: A working bash.
    :param tmp_path: A temporary directory.
    """
    env = {**os.environ, "TAG": "v1.0.0", "FAKE_VERSION": "1.0.1"}
    result = _run_gate(bash, TAG_STEP, tmp_path, env)
    assert result.returncode == 1
    assert "does not match package version" in result.stdout


@pytest.mark.parametrize(
    "tag",
    ["v1'; touch pwned; exit 0; echo '", 'v1"; touch pwned; exit 0; echo "', "v$(touch pwned)"],
)
def test_release_tag_gate_never_runs_the_tag(bash: str, tag: str, tmp_path: Path) -> None:
    """A tag carrying shell syntax fails the gate and is never executed.

    :param bash: A working bash.
    :param tag: A hostile tag name.
    :param tmp_path: A temporary directory.
    """
    env = {**os.environ, "TAG": tag, "FAKE_VERSION": tag.removeprefix("v")}
    result = _run_gate(bash, TAG_STEP, tmp_path, env)
    assert result.returncode == 1
    assert not (tmp_path / "pwned").exists()


def _git(bash: str, repo: Path, env: dict[str, str], *args: str) -> None:
    """Run git in a repository through bash, so it is the git the gates will use.

    Git for Windows' ``bin/bash.exe`` puts its own git on ``PATH``, so this works
    even when git is not on the Windows ``PATH``.

    :param bash: The bash executable.
    :param repo: The repository.
    :param env: The environment to run git in.
    :param *args: The git arguments.
    """
    command = [bash, "--noprofile", "--norc", "-c", 'git "$@"', "git", *args]
    subprocess.run(command, cwd=repo, env=env, check=True, capture_output=True)


@pytest.fixture
def release_repo(bash: str, tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Build a repository with ``origin/main``, a side branch, and annotated tags.

    ``v1.0.0`` tags the commit on ``main``; ``v2.0.0`` tags a commit on ``side``,
    which is not on ``main``. ``HEAD`` is left on ``side``.

    :param bash: A working bash.
    :param tmp_path: A temporary directory.
    :return: The repository path and the environment to run git in.
    """
    env = _git_env(tmp_path)
    repo = tmp_path / "repo"

    def git(*args: str) -> None:
        """Run git in the repository.

        :param *args: The git arguments.
        """
        _git(bash, repo, env, *args)

    repo.mkdir()
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "on main")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
    git("checkout", "-q", "-b", "side")
    git("commit", "-q", "--allow-empty", "-m", "off main")
    git("tag", "-a", "v2.0.0", "-m", "v2.0.0")
    return repo, env


def _checkout(bash: str, repo: Path, env: dict[str, str], ref: str) -> None:
    """Check out a ref with a detached ``HEAD``, as ``actions/checkout`` does for a tag.

    :param bash: The bash executable.
    :param repo: The repository.
    :param env: The environment to run git in.
    :param ref: The ref to check out.
    """
    _git(bash, repo, env, "checkout", "-q", "--detach", ref)


def test_release_commit_gate_accepts_a_tag_on_main(
    bash: str,
    release_repo: tuple[Path, dict[str, str]],
) -> None:
    """The checked-out tag commit on ``main`` passes.

    :param bash: A working bash.
    :param release_repo: The test repository and its environment.
    """
    repo, env = release_repo
    _checkout(bash, repo, env, "v1.0.0")
    result = _run_gate(bash, COMMIT_STEP, repo, {**env, "TAG": "v1.0.0"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_commit_gate_rejects_a_tag_off_main(
    bash: str,
    release_repo: tuple[Path, dict[str, str]],
) -> None:
    """A tag whose commit is not on ``main`` fails.

    :param bash: A working bash.
    :param release_repo: The test repository and its environment.
    """
    repo, env = release_repo
    _checkout(bash, repo, env, "v2.0.0")
    result = _run_gate(bash, COMMIT_STEP, repo, {**env, "TAG": "v2.0.0"})
    assert result.returncode == 1
    assert "is not on main" in result.stdout


def test_release_commit_gate_rejects_a_checkout_that_is_not_the_tag(
    bash: str,
    release_repo: tuple[Path, dict[str, str]],
) -> None:
    """A checkout of any commit other than the tag's fails, even if the tag is on ``main``.

    :param bash: A working bash.
    :param release_repo: The test repository and its environment.
    """
    repo, env = release_repo
    _checkout(bash, repo, env, "v2.0.0")
    result = _run_gate(bash, COMMIT_STEP, repo, {**env, "TAG": "v1.0.0"})
    assert result.returncode == 1
    assert "but release tag v1.0.0 is" in result.stdout


def test_release_commit_gate_rejects_a_missing_tag(
    bash: str,
    release_repo: tuple[Path, dict[str, str]],
) -> None:
    """A tag that is not in the checkout fails.

    :param bash: A working bash.
    :param release_repo: The test repository and its environment.
    """
    repo, env = release_repo
    _checkout(bash, repo, env, "v1.0.0")
    result = _run_gate(bash, COMMIT_STEP, repo, {**env, "TAG": "v9.9.9"})
    assert result.returncode == 1
    assert "does not exist" in result.stdout


@pytest.mark.parametrize(
    ("files", "passes"),
    [
        (["cernis-1.2.3-py3-none-any.whl", "cernis-1.2.3.tar.gz"], True),
        (["cernis-1.2.3-py3-none-any.whl"], False),
        (["cernis-1.2.3-py3-none-any.whl", "cernis-1.2.3.tar.gz", "extra.whl"], False),
        (["cernis-1.2.4-py3-none-any.whl", "cernis-1.2.4.tar.gz"], False),
    ],
)
def test_release_dist_gate(bash: str, files: list[str], passes: bool, tmp_path: Path) -> None:
    """``dist/`` passes only with exactly one wheel and one sdist for the version.

    :param bash: A working bash.
    :param files: The file names placed in ``dist/``.
    :param passes: Whether the gate must pass.
    :param tmp_path: A temporary directory.
    """
    (tmp_path / "dist").mkdir()
    for name in files:
        (tmp_path / "dist" / name).touch()
    result = _run_gate(bash, DIST_STEP, tmp_path, {**os.environ, "FAKE_VERSION": "1.2.3"})
    assert (result.returncode == 0) is passes, result.stdout + result.stderr


def test_releasing_doc_matches_the_trusted_publisher() -> None:
    """``RELEASING.md`` names the workflow file and environment that publish."""
    doc = RELEASING.read_text(encoding="utf-8")
    assert f"Workflow name: `{PUBLISH.name}`" in doc
    assert "Environment name: `pypi`" in doc
    assert "      name: pypi" in _jobs(PUBLISH)["publish"]
