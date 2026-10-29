# Session 2: CI and Trusted Publishing

**Date:** 2026-10-29
**Phase:** between 1 and 2 (infrastructure only)
**Version:** 0.1.0.dev0 (unchanged; not built for release, not published)

No product code changed. No fetching, parsing, or network access in Cernis itself.

## Built

- **`.github/workflows/ci.yml`.** On every push and pull request, runs the full check list from `CLAUDE.md` on Python 3.12, 3.13, and 3.14 with `astral-sh/setup-uv`. Workflow permissions are `contents: read`.
- **`.github/workflows/publish.yml`.** Triggered only by a published release. The `build` job checks the release tag against the package version, builds the sdist and wheel with `uv build --no-sources`, and uploads them as the `dist` artifact. The `publish` job runs in the `pypi` environment with `id-token: write` and no other permission, downloads the artifact, and publishes with `pypa/gh-action-pypi-publish` through Trusted Publishing.
- **`docs/RELEASING.md`.** One-time PyPI trusted publisher and GitHub environment setup, then the release steps.

## Decisions

1. **Actions pinned to full commit SHAs**, with the release in a trailing comment: `actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.3.3, `actions/upload-artifact` v7.0.2, `actions/download-artifact` v8.0.2, `pypa/gh-action-pypi-publish` v1.14.3. Each SHA was resolved from the release tag (dereferenced for annotated tags) on 2026-10-29.
2. **`UV_LOCKED=1` in CI**, so a `uv.lock` that is out of date with `pyproject.toml` fails the build instead of being re-resolved.
3. **Every matrix job runs all six checks**, including the isolated Python 3.12 run, so each job is the literal check list. The isolated run repeats work on the 3.12 job; it is cheap.
4. **The tag must be exactly `vX.Y.Z`.** Pre-release and development versions (`0.1.0.dev0`, `0.2.0rc1`) cannot be released by this workflow. The tag is passed to the shell through an environment variable, never interpolated into the script.
5. **No uv cache in the release build** (`enable-cache: false`), so nothing saved by another run can reach the published files. CI keeps the default cache.
6. **`persist-credentials: false`** on every checkout. No job needs to push.
7. **Top-level `permissions: {}` in `publish.yml`**, with each job granting only what it needs. Downloading an artifact from the same run needs no `GITHUB_TOKEN` permission.
8. **Attestations stay on** (the publish action's default), so PyPI receives provenance for each file.
9. **`CHANGELOG.md` is unchanged.** CI and release automation do not change the package.

## Review

The audit-before-commit gate routes this change to `deep` (production deploy and install integrity). The Decision Engine server failed to connect this session, so no external audit ran and the gate is **open**. Self-review covered script injection through the tag, token scope per job, cache poisoning, the artifact handoff, and tag and version drift.

## Deferred

- **Python 3.14 classifier.** CI now tests 3.14, but `pyproject.toml` lists classifiers for 3.12 and 3.13 only. Adding it is a package metadata change for the next release.
- **The one-time PyPI and GitHub environment setup** in `docs/RELEASING.md` is manual and not yet done.
- **Dependabot or Renovate** to keep the pinned SHAs current.

## Session 2b: audit (2026-10-29)

The Decision Engine server was configured for this session but timed out on connect before any request was sent, so the `deep` audit ran as a DE Lite local advisory (run `local_host_a64110b61ed98f45a1399257`, `audit_id: null`). Every finding was reviewed across logic, edge cases, security, performance, and concurrency, and recorded in a validated multi-review ledger. That ledger's decision is `needs-cross-llm-rerun`: a single-model local read is not a cross-vendor audit, so **the gate stays open** until a hosted `deep` run covers this change.

Before the review, every pinned SHA was checked against its release tag with `git ls-remote` (the `pypa/gh-action-pypi-publish` tag dereferenced). All five match.

### Findings

| # | Severity | Dimension | Finding | Disposition |
|---|---|---|---|---|
| 1 | High | logic | `publish.yml` built and uploaded without running the check list, so a commit with failing checks could be released. | Fixed. `ci.yml` gains `workflow_call`; a `checks` job in `publish.yml` calls it, and `build` needs `checks`. Test: `test_publish_builds_only_after_the_check_list_passes`, `test_ci_is_callable_by_the_publish_workflow`. |
| 2 | Medium | security | The tagged commit could be on any branch. The environment's `v*` rule filters tag names, not commits. | Fixed. The build job checks out full history and requires `git merge-base --is-ancestor "$GITHUB_SHA" origin/main`. Test: `test_release_build_has_no_cache_checks_main_and_checks_files`. |
| 3 | Medium | edge cases | The tag pattern accepted leading zeros (`v01.0.0`). PEP 440 normalizes them, so the file names would not match the tag. | Fixed. Each component is `(0\|[1-9][0-9]*)`. The test extracts the pattern from `publish.yml` and checks accepted and rejected tags; three of them failed against the old pattern. |
| 4 | Medium | edge cases | Checking that `dist/` holds one wheel and one sdist for the version was a manual step in `RELEASING.md`. | Fixed. A build step compares the file list (in the C locale) to the two expected names. Checked locally in bash with the right files and with an extra file; asserted by test. |
| 5 | Low | concurrency | The CI group `ci-<ref>` cancelled in-progress runs on `main`, and a release's call to CI would share a group with the push run for the same tag. | Fixed. The group adds the event name, and `cancel-in-progress` is false on `main`. Test: `test_concurrency_never_cancels_main_or_a_publish`. |
| 6 | Low | concurrency | Two releases could publish at once. | Fixed. `publish.yml` has the `publish` concurrency group, never cancelled. Same test. |
| 7 | Low | performance | No job had `timeout-minutes` (the default is 360). | Fixed. 20 minutes for CI, 15 for build and publish. Test: `test_every_runner_job_has_a_timeout`. |
| 8 | Low | performance | A branch with an open pull request runs CI twice (push and pull request). | Not applied. Limiting `push` to `main` would drop CI for branches with no pull request; the extra run costs minutes, not correctness. |
| 9 | Low | security | The uv frontend is unpinned (setup-uv installs the latest), and the `uv_build` backend is resolved at build time within `>=0.8.4,<0.9.0` without hashes. Local uv is 0.8.4. | Deferred. Pinning without automation to update the pins leaves them stale; this goes with the Dependabot or Renovate item below. The backend range is bounded, and Trusted Publishing attestations record what was built. |

The session also added `tests/test_workflows.py`, which reads the workflows as text with no new dependency. Beyond the findings above, it locks the Session 2 decisions: every remote action pinned to a 40-character SHA with a `# vX.Y.Z` comment, no `${{ }}` inside a `run:` script, no `pull_request_target`, `persist-credentials: false` on every checkout, CI read-only with `UV_LOCKED`, CI running the `CLAUDE.md` check list in order, `publish.yml` triggered only by a published release, top-level `permissions: {}` with `id-token: write` only in the `publish` job, and `RELEASING.md` naming the same workflow file and environment as the trusted publisher. To show the tests can fail, they were run against reconstructions of the old workflows (the old tag pattern, no `needs: checks`, no `workflow_call`, no timeout, and a changed check-list command): 7 failed. With the current files, all 31 workflow tests pass.

`docs/RELEASING.md` now describes the three jobs, the main-branch and file checks, and what to do when the `checks` job fails or the release commit is not on `main`.

### Supersedes

- Decision 3 still holds; the same six checks now also run as the first job of every release.
- Decision 4: the tag is `vX.Y.Z` with no leading zeros in any component.
- The Review section above: the self-review is replaced by the findings here. The gate is still open, now pending a hosted cross-vendor `deep` run.

### Checks

All six commands from `CLAUDE.md` pass: ruff check, ruff format check, mypy strict (15 files), pydoclint, pytest (198 passed), and the isolated Python 3.12 pytest (198 passed). Both workflows also parse with PyYAML in a throwaway environment outside the project.

### Deferred (2b)

- **A hosted `deep` audit** of this change once the Decision Engine connects. This closes the gate.
- **Pin the uv version** in the release build, along with the SHA update automation.
- **Repository state.** Commit `d81ad98` has the message "Add CI and PyPI Trusted Publishing workflows", but it only deletes `.idea/` files. `.github/`, `docs/RELEASING.md`, and this record are still untracked, so the message for this change covers them.

## Session 2c: Decision Engine audit (2026-10-29)

The Decision Engine connected this session, and the hosted `deep` audit that Session 2b left open ran on the four files as committed in `f2157bc`: `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `tests/test_workflows.py`, and `docs/RELEASING.md` (test docstrings elided for size).

- **audit_id:** `aud_FA4JzuTPbq` (the run ID; the result carries no separate `audit_id` field)
- **Mode:** `deep`, stakes `high`, intent `prescriptive`, tier `reasoning`
- **Submission canonical SHA:** `0e11e04b0017487d8df9f807ffb647cc55dbe71c2ae2c539f54311f5cb5fc430`
- **Panel:** five auditors from five vendors, here Voice 1 to Voice 5. All five completed, with no partial failures and no fallbacks.
- **Verdicts:** 5/5 `has-serious-issues`. 30 findings (2, 8, 10, 4, 6 by voice), 5 flagged blocking: V1 f1, V2 f1, V2 f2, V5 f1, V5 f2.

### Adjudication

Each finding was checked against current evidence before it was classified; panel majority decided nothing. Duplicates are merged into 22 rows. The table passes `validate_audit_adjudication.py` (accepted 11, rejected 9, needs-user-decision 2).

Of the five blocking findings, four were disproved by direct evidence (A1, A3, A10): a documented GitHub context value, a uv command run on this machine, and the release step itself run under bash. The fifth (A11) is an Owner decision.

| finding | decision | action | verification |
|---|---|---|---|
| A1. V2 f1, V5 f1 (critical, blocking), publish.yml on-main step: on a release event `GITHUB_SHA` is the default-branch tip, so the ancestor check is tautological and the build packages main, not the tag. | rejected | Premise is wrong: GitHub documents `GITHUB_SHA` for `release` as "Last commit in the tagged release" and `GITHUB_REF` as `refs/tags/<tag_name>`, which `actions/checkout` checks out. Hardened anyway: the step now peels `refs/tags/$TAG^{commit}`, requires `HEAD` to equal it, and tests that commit against `origin/main`, so the gate no longer relies on `GITHUB_SHA`. | GitHub docs "Events that trigger workflows", release row (fetched 2026-10-29). New tests run the step in bash on a local repo: tag on main passes; tag off main, checkout other than the tag, and missing tag fail. |
| A2. V5 f3 (major), RELEASING.md claims checks and build run "against the tagged commit" and reject off-main tags. | accepted | Runbook now states the exact predicate (checked-out commit equals the peeled tag commit, which is on `main`), which the hardened step implements. | `test_release_commit_gate_*` (4 tests) pass; doc text reviewed against publish.yml. |
| A3. V2 f2 (major, blocking), publish.yml and RELEASING.md: `uv version` does not exist. | rejected | `uv version` is the project-version command in uv 0.7 and later. | `uv version --short` prints `0.1.0.dev0`, exit 0, on uv 0.8.4. |
| A4. V2 f3 (major), ci.yml: setup-uv has no `python-version` input, so 3.13 and 3.14 never run. | rejected | The input exists at the pinned SHA and sets `UV_PYTHON`. | `astral-sh/setup-uv@68559e9` action.yml: "The version of Python to set UV_PYTHON to." |
| A5. V2 f5 (minor), V2 f4 part 1, V4 f1 (major): version comments name nonexistent releases, and the pin test checks only the comment format. | rejected | The pins are correct. The pin test cannot resolve SHAs, because CLAUDE.md forbids network access in tests. SHA-to-tag checks stay with the deferred Dependabot or Renovate item. | `git ls-remote` on 2026-10-29: all five SHAs equal their tags (annotated tag dereferenced). |
| A6. V2 f6 (minor), RELEASING.md step 8: `uvx cernis@X.Y.Z` is invalid syntax. | rejected | `uvx` reads `pkg@X.Y.Z` as `pkg==X.Y.Z`. Corrected the expected output to `cernis X.Y.Z`. | `uvx --offline nosuchpkg-cernis-test@1.2.3` reports "you require nosuchpkg-cernis-test==1.2.3". |
| A7. V2 f7 (minor), publish.yml build job lacks `UV_LOCKED`. | rejected | `uv build` builds in an isolated environment from `[build-system] requires`, not from `uv.lock`, so `UV_LOCKED` would not constrain it. The real gap is the unhashed backend, already deferred as Session 2b finding 9. | Session 2b finding 9; `pyproject.toml` build-system range `uv_build>=0.8.4,<0.9.0`. |
| A8. V2 f8 (minor), ci.yml: `cancel-in-progress` is true for tag refs. | accepted | `cancel-in-progress` is now false for `refs/heads/main` and every `refs/tags/` ref. | `test_concurrency_never_cancels_main_a_release_or_a_publish` passes. |
| A9. V4 f3 (minor), ci.yml: `--isolated` ignores `UV_LOCKED`, so the floor run can re-resolve a stale lock. | rejected | `--isolated` on `uv run` isolates the environment; it does not drop `UV_*` variables. | With a stale lock in a scratch copy, `UV_LOCKED=1 uv run --offline --isolated --python 3.12` exits 2: "lockfile ... needs to be updated, but --locked was provided". |
| A10. V5 f2 (critical, blocking), publish.yml tag step: `'$TAG'` in `echo` lets a quoted tag break out and run code. | rejected | Bash does not re-parse an expanded variable. The single quotes sit inside a double-quoted string and are literal characters. Regression test added. | `test_release_tag_gate_never_runs_the_tag` (3 hostile tags) runs the real step in bash: exit 1, no file created. |
| A11. V1 f1 (major, blocking), V3 f3 part, RELEASING.md: the release approver can approve their own release. | needs-user-decision | Runbook now says: enable Prevent self-review once there are two maintainers; turn off admin bypass; with one maintainer the approval is a deliberate pause, not an independent review. Decision actor: the Owner (kenwalger). Question: add a second release reviewer before the first release, or accept single-maintainer approval? Blocked action: relying on the `pypi` environment approval as an independent review. | Owner's choice recorded in a later session record; live `pypi` environment settings inspected by the Owner (not reachable from this session). |
| A12. V3 f3, V4 f4 (major/minor), RELEASING.md: the gate relies on unstated branch and tag protections, and the approver has nothing concrete to check. | accepted | Added "Repository rules" (main ruleset: no force push or deletion, plus a PR requirement with two or more maintainers; `v*` tag ruleset restricting create, update, and delete). The build writes the commit and SHA-256 of each file to the run summary. Step 7 compares that commit with `git rev-parse "vX.Y.Z^{commit}"`. | `test_release_build_runs_every_gate_in_order` includes the summary step; the step ran locally in bash and wrote the commit and two hashes. Live rulesets are an Owner setup task. |
| A13. V5 f6 (major), RELEASING.md: revoking legacy PyPI tokens is optional. | accepted | Deleting every token that can upload to `cernis` is now a required setup step. | Doc reviewed. Token state on PyPI is an Owner check. |
| A14. V3 f1 (major), publish.yml: the built wheel is never installed or run before the irreversible upload. | accepted | New step "Check the wheel installs and runs" runs `uv run --isolated --no-project --with dist/<wheel> cernis --version` and requires `cernis $version`, before upload. | Ran locally against a fresh build: printed `cernis 0.1.0.dev0`. `test_release_wheel_is_run_from_an_isolated_environment` and the step-order test pass. |
| A15. V1 f2, V2 f4 parts 2-3, V3 f2, V3 f5, V4 f2, V5 f4 (major/minor), tests/test_workflows.py: tests check strings and can pass vacuously. | accepted | Glob covers `*.yaml`. `_run_blocks` reads every block scalar header (with a self-test). `workflow_run` is forbidden. CI run blocks must equal the check list exactly. `persist-credentials` is checked per checkout step. No `if:` or `continue-on-error`. The only `write` in publish.yml is `id-token`. The build steps are in exact order. The tag, commit, and dist gates are executed in bash instead of re-implemented in Python. The YAML-loader suggestion (V4 f2) is not adopted, to avoid a new dependency. | RED: 7 failures before the workflow edits. Mutations to publish.yml are each caught: inverted ancestor check (2 failures), `continue-on-error` (1), version comparison removed (1), dist comparison removed (3). |
| A16. V3 f4 (major), publish.yml: gh-action-pypi-publish runs a GHCR image pulled by tag, not digest, in the job holding `id-token: write`. | needs-user-decision | Verified that at the pinned SHA the image is `docker://ghcr.io/pypa/gh-action-pypi-publish:<ref>`, where the ref is the pinned SHA. GHCR tags are still mutable. Decision actor: the Owner. Question: accept this residual risk (recorded as deferred), or replace the action with a digest-pinned image or hash-pinned upload tooling? Blocked action: none in this session; recorded under Deferred. | `create-docker-action.py` at `7245906`: `return f'docker://ghcr.io/{repo}:{docker_ref}'`. |
| A17. V3 f6 (minor), RELEASING.md: "a version can never be uploaded twice" is wrong, and there is no partial-upload path. | accepted | Reworded to "a file name can never be uploaded twice". Added a partial or cancelled publish entry: re-run the failed jobs from the same run, and compare PyPI hashes with the summary. | Doc reviewed. |
| A18. V3 f7 (minor), RELEASING.md: setup assumes the PyPI project already exists. | accepted | Added the pending-publisher path for the first release, and noted that the name is claimed only on the first successful publish. | Doc reviewed. |
| A19. V3 f8 (minor), publish.yml concurrency: a newer pending run replaces an older one, and approval waits hold the group. | accepted | Workflow comment reworded; step 7 says to approve or reject each release before publishing the next. | Doc and comment reviewed. |
| A20. V3 f9 (minor), RELEASING.md: a hand-edited post-release version leaves `uv.lock` stale under `UV_LOCKED`. | accepted | Steps 1 and the post-release step use `uv version`, which updates `pyproject.toml` and `uv.lock` together; commit both. | `uv version` behavior on 0.8.4; doc reviewed. |
| A21. V3 f10 (nit), ci.yml: the isolated 3.12 run repeats in every matrix leg. | rejected | Session 2 Decision 3 makes each matrix job the literal check list; the extra run is cheap. | SESSION-02.md Decision 3 and Session 2b finding 8 rationale. |
| A22. V5 f5 (major), RELEASING.md: recovery steps omit publishing a new release, and yank does not stop pinned installs or contain a compromise. | accepted | Off-main recovery restarts from step 5, including a new GitHub release. The bad-release entry says yank does not stop pinned installs; a compromised file needs PyPI deletion, a report to PyPI security, and notice to users. Added a "built wheel does not run" entry. | Doc reviewed. |

### Agreement with the 2b local advisory

- **2b finding 1 (checks before build).** No voice disputed it.
- **2b finding 2 (commit on `main`).** Voices 2 and 5 said the 2b fix was tautological because `GITHUB_SHA` is the main tip. That is wrong (A1). The engine still found a gap 2b missed: nothing tied the checked-out commit to the tag. The step now peels the tag and requires `HEAD` to be that commit.
- **2b finding 3 (tag pattern).** No voice disputed the pattern. Voice 3 noted that the tests ran it through Python `re`, not bash. The tag gate now runs in bash, and every 2b case still behaves as before.
- **2b finding 4 (dist file check).** Agreed and extended. A file-name check does not show that the wheel works (A14), and the old test checked that the step existed, not that it rejected anything (A15).
- **2b findings 5 and 6 (concurrency).** Extended to release tags (A8) and to GitHub's one-pending-run rule (A19), both missed by 2b.
- **2b finding 7 (timeouts).** No comment.
- **2b finding 8 (duplicate CI runs, not applied).** No voice raised it. A21 is a related duplication, rejected on the same reasoning.
- **2b finding 9 (uv and `uv_build` unpinned).** A7 is the same root, still deferred. The engine found a risk 2b missed: the publish action's container image is pulled by tag (A16).
- **Pinned SHAs.** 2b found all five correct. Voices 2 and 4 doubted the version labels; a fresh `git ls-remote` confirms 2b (A5).
- **Missed by 2b entirely.** The runbook's governance gaps (A11, A12, A13, A18), the recovery paths (A17, A22), the post-release lock refresh (A20), and how weak the workflow tests were (A15).

### Changes

- **`publish.yml`.** The commit step is now "Check the release commit is the tag and is on main": it peels `refs/tags/$TAG^{commit}`, requires `HEAD` to equal it, and requires it to be an ancestor of `origin/main`. Two new steps come before upload. "Check the wheel installs and runs" installs the built wheel alone into a fresh environment and requires `cernis --version` to print `cernis $version`. "Record the release commit and file hashes" writes the commit and SHA-256 values to the run summary for the approver. The concurrency comment now states GitHub's pending-run rule.
- **`ci.yml`.** `cancel-in-progress` is false for `main` and for every tag.
- **`tests/test_workflows.py`.** The tag, commit, and dist gates are taken from `publish.yml` and run under bash (with `uv` stubbed by a shell function, and a local git repository with annotated tags). Structural checks tightened as listed in A15. Python-regex tag tests replaced by the bash runs. The tests need `bash` and fail, rather than skip, without it. 51 workflow tests, up from 31.
- **`docs/RELEASING.md`.** Pending publisher for the first release, required token deletion, environment reviewer rules for one and for two or more maintainers, a new "Repository rules" section, the exact build predicate, an approver check against the run summary, `uv version` for both version bumps, and new recovery entries.

### Supersedes

- 2b finding 2's fix: the gate is now tag-based (`HEAD` equals the peeled tag commit, which is on `main`), not `GITHUB_SHA`-based.
- 2b finding 4's fix: the file-name check stays, and is followed by a wheel run check.
- Decision 4 holds. The tag is still `vX.Y.Z` with no leading zeros, now proven by running the bash test.
- **The gate:** the hosted cross-vendor `deep` audit has now run. Under the one-audit-per-change rule, the remediation is not re-audited. Every blocking finding is either disproved by evidence (A1, A3, A10) or left as an Owner decision (A11). The gate is closed except for the two Owner decisions below.

### Checks (2c)

All six commands from `CLAUDE.md` pass: ruff check, ruff format check, mypy strict (15 files), pydoclint, pytest (217 passed), and the isolated Python 3.12 pytest (217 passed). Both workflows parse with PyYAML in a throwaway environment outside the project. Before the workflow edits, the new tests failed 7 times (RED). After them, mutating `publish.yml` was caught each time: inverted ancestor check, `continue-on-error`, version comparison removed, dist comparison removed.

### Deferred (2c)

- **Owner decision A11:** add a second release reviewer and enable Prevent self-review, or accept single-maintainer approval as a pause, not a review.
- **Owner decision A16:** accept the publish action's tag-pulled container image as residual risk, or replace it with a digest-pinned image or hash-pinned upload tooling.
- **Live settings not checked from this session:** the `pypi` environment's reviewers and admin bypass, the `main` and `v*` rulesets, PyPI API tokens, and whether the `cernis` name is free on PyPI.
- Still open from 2b: pin the uv version and `uv_build` with hashes, and add Dependabot or Renovate for the pinned SHAs (which would also check each SHA against its tag, A5).

## Session 2d: release decisions (2026-10-29)

Docs only. The Owner decided the two open items from Session 2c and corrected one assumption.

### Decisions

1. **A11, the release approver: single-maintainer approval.** Cernis has one maintainer, so **Prevent self-review** stays off. The `pypi` environment approval is a deliberate pause to compare the release commit and file hashes in the run summary, not an independent review. `docs/RELEASING.md` now says so plainly and drops the two-maintainer branches from the environment setup.
2. **A16, the publish action's container image: accepted risk.** `pypa/gh-action-pypi-publish` pulls its image by registry tag, not digest. Accepted because the image is published by PyPA, the same maintainers as the pinned action, and the action produces PyPI attestations that `uv publish` would not. Revisit before 1.0. Recorded under a new "Accepted risks" section in `docs/RELEASING.md`.
3. **Correction: `cernis` already exists on PyPI.** 0.0.1 was uploaded by hand, so the setup adds a trusted publisher to an existing project. The pending-publisher path added in 2c is removed from `docs/RELEASING.md`.

Also fixed in `docs/RELEASING.md` step 7: "one pending run per release" was wrong (the limit is one pending publish run at a time), and the step now says to note each file's SHA-256 for step 8.

### Supersedes

- **Deferred (2c).** The Owner decisions on A11 and A16 are made: A11 is decided (single-maintainer approval) and A16 moves from Deferred to Accepted. Also removed from the deferred list is the check of whether the `cernis` name is free on PyPI, since the project exists. The remaining live-settings checks (the `pypi` environment's reviewers and admin bypass, the `main` and `v*` rulesets, and PyPI API tokens) stay deferred.
- **The gate.** With both Owner decisions made, the audit gate for this change is closed.

### Checks (2d)

All six commands from `CLAUDE.md` pass: ruff check, ruff format check, mypy strict (15 files), pydoclint, pytest (217 passed), and the isolated Python 3.12 pytest (217 passed).

## Session 2e: Windows bash and a single version source (2026-10-29)

### Built

- **A usable bash for the release gate tests (`tests/test_workflows.py`).** From plain PowerShell, `bash` on `PATH` was `C:\Windows\System32\bash.exe`, the WSL launcher, and 18 workflow tests failed. A new finder tries, on Windows, Git for Windows' `bin/bash.exe` and `usr/bin/bash.exe` (under the root given by `git --exec-path`, then `%ProgramFiles%`, `%ProgramFiles(x86)%`, and `%LOCALAPPDATA%\Programs`), then a `bash` on `PATH` that is not in `System32` or `WindowsApps`; elsewhere it uses `shutil.which("bash")`. A session-scoped `bash` fixture runs the finder once and checks the result with `bash -c "echo ok"`. With no usable bash the gate tests skip with the reason, unless `CI` is set (to anything but empty, `0`, or `false`), in which case they fail. The test repository's git commands also run through that bash, so the tests pass even when git is not on the Windows `PATH`. New unit tests cover the WSL exclusion, the candidate order, the `echo ok` check, and skip versus fail by `CI` value.
- **One version source.** `cernis.__version__` reads `importlib.metadata.version("cernis")`, so `pyproject.toml` is the only place the version is written. `test_package_version_matches_pyproject` is replaced by `test_package_version_is_the_installed_distribution_version`. Checked in a scratch copy: after `uv version X.Y.Z`, the next `uv run` reinstalls the project and `cernis --version` prints the new version; a hand edit of `pyproject.toml` fails under `UV_LOCKED`.
- **`docs/RELEASING.md`** is split into **One-time setup** (done once, never a release step) and **Each release** (where the version lives, what the workflow checks, steps, after the release, and recovery). Step 1 now confirms both `uv version --short` and `uv run cernis --version`, and step 4 names the three files to commit.
- **`CLAUDE.md`:** the suite must pass from plain PowerShell as well as from Claude Code's shell.

### Decisions

1. **The gate tests skip locally, but never in CI.** A contributor without Git for Windows can still run the rest of the suite. In CI the same condition fails the run, so the release gate checks cannot disappear unnoticed.
2. **No audit.** This change is test discovery, version sourcing, and docs, with no Gate A surface. Every behavior is settled by tests run in both shells.

### Checks (2e)

All six commands from `CLAUDE.md` pass from Claude Code's shell and from plain PowerShell with `C:\Windows\System32` first on `PATH` (where `bash` resolves to the WSL launcher): ruff check, ruff format check, mypy strict (15 files), pydoclint, pytest (227 passed), and the isolated Python 3.12 pytest (227 passed). Before the fix, the workflow tests failed 18 times under that PowerShell `PATH`. The workflow and CLI tests also pass with `PATH` reduced to `System32` and uv's folder, with no git on it.

A missing bash could not be simulated end to end on this machine: Windows put the real `%ProgramFiles%` back, and the finder found Git for Windows there. The skip and fail paths are covered by `test_missing_bash_skips_locally_and_fails_in_ci`.

### Not touched

- `CHANGELOG.md` has an uncommitted `## [0.0.2] - 2026-10-29` heading that this session did not write. It is left as found.
