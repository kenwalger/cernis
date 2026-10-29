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
