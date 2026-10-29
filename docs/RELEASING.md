# Releasing Cernis

Cernis is published to PyPI by `.github/workflows/publish.yml` using Trusted Publishing. The workflow holds no tokens or secrets: PyPI trusts a short-lived OpenID Connect token that GitHub issues to that workflow, in that repository, running in the `pypi` environment.

This document has two parts. **One-time setup** configures PyPI and GitHub once for the project; it is not repeated for a release. **Each release** is followed in full for every version.

## One-time setup

Do these once. None of them is a release step.

### PyPI trusted publisher

The `cernis` project already exists on PyPI (0.0.1 was uploaded by hand), so the trusted publisher is added to that project:

1. Sign in to PyPI as an owner of the `cernis` project.
2. Open **Your projects**, then **cernis**, then **Manage**, then **Publishing**.
3. Under **Add a new publisher**, choose **GitHub** and enter:
   - Owner: `kenwalger`
   - Repository name: `cernis`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
4. Save.

All values must match exactly. A publish from any other workflow file, repository, or environment is rejected by PyPI.

Then delete every API token that can upload to `cernis`, under **Account settings**, then **API tokens**, and confirm none is left. A remaining token can upload any version without passing a single check in this workflow.

### GitHub environment

1. In the `kenwalger/cernis` repository, open **Settings**, then **Environments**, then **New environment**, and name it `pypi`.
2. Under **Deployment protection rules**, enable **Required reviewers** and add yourself. Turn off **Allow administrators to bypass configured protection rules**.
3. Leave **Prevent self-review** off. Cernis has one maintainer, who both publishes the release and approves the upload, so that setting would block every release. The approval is therefore not an independent review. It is a deliberate pause to compare the release commit and the file hashes in the run summary before anything reaches PyPI (step 7 of each release).
4. Under **Deployment branches and tags**, choose **Selected branches and tags** and add a tag rule `v*`, so only a release tag can deploy to this environment.
5. Add no secrets or variables to the environment. Trusted Publishing does not use them.

### Repository rules

The build job's check that the release commit is on `main` is only as strong as the rules on `main` and on release tags. Under **Settings**, then **Rules**, then **Rulesets**:

1. Add a branch ruleset for `main` that blocks force pushes and deletions. With two or more maintainers, also require a pull request before merging.
2. Add a tag ruleset for `v*` that restricts creations, updates, and deletions, with only the maintainers in the bypass list.

## Each release

Follow every step below for every version, in order.

### Where the version lives

`pyproject.toml` is the only place the version is written. `cernis.__version__`, and so `cernis --version`, reads it from the installed package's metadata, so there is nothing else to edit. `uv version X.Y.Z` sets it in `pyproject.toml` and updates `uv.lock`, and the next `uv run` reinstalls the project with the new version.

### What the workflow checks

The workflow runs three jobs in order, and each must pass before the next starts:

1. `checks` runs `ci.yml`, the full check list from `CLAUDE.md` on every supported Python, against the tagged commit.
2. `build` checks that the tag is `vX.Y.Z` with no leading zeros and equals `v` plus the version in `pyproject.toml`; checks that the checked-out commit is the commit the tag names and that this commit is on `main`; builds the sdist and wheel; checks that `dist/` holds exactly `cernis-X.Y.Z-py3-none-any.whl` and `cernis-X.Y.Z.tar.gz`; installs the wheel into a fresh environment and checks that `cernis --version` prints `cernis X.Y.Z`; and writes the commit and the SHA-256 of each file to the run summary.
3. `publish` waits for approval on the `pypi` environment, then uploads.

### Steps

1. **Set the version.** Run `uv version X.Y.Z`, then confirm that `uv version --short` and `uv run cernis --version` both show `X.Y.Z`.
2. **Update the changelog.** In `CHANGELOG.md`, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and start a new empty `[Unreleased]` section above it.
3. **Run the full check list** from `CLAUDE.md` and confirm everything passes.
4. **Commit** `pyproject.toml`, `uv.lock`, and `CHANGELOG.md`: `git commit -m "Release X.Y.Z"`, then push to `main`. Tag only a commit that is on `main`; the build job rejects any other.
5. **Tag** the release commit and push the tag:

   ```sh
   git tag -a vX.Y.Z -m "Cernis X.Y.Z"
   git push origin vX.Y.Z
   ```

6. **Publish a GitHub release.** On GitHub, open **Releases**, then **Draft a new release**, choose the `vX.Y.Z` tag, paste the changelog section as the notes, and click **Publish release**. Publishing (not drafting or saving) starts the workflow.
7. **Approve the deployment.** The `checks` and `build` jobs run first, and the `publish` job then waits for approval on the `pypi` environment. Open the workflow run under **Actions** and check that both jobs passed. In the run summary, check that the commit equals the output of `git rev-parse "vX.Y.Z^{commit}"` on your machine and is the `Release X.Y.Z` commit you pushed, and note the SHA-256 of each file for step 8. Then click **Review deployments**, select `pypi`, and approve. Approve or reject each release before publishing the next one: GitHub keeps only one pending publish run at a time, so a third release published while one waits for approval and another is queued cancels the queued one.
8. **Verify** that `https://pypi.org/project/cernis/X.Y.Z/` lists the two files with the SHA-256 values from the run summary, and that `uvx cernis@X.Y.Z --version` prints `cernis X.Y.Z`.

### After the release

Run `uv version 0.2.0.dev0` (or the next development version), which updates `pyproject.toml` and `uv.lock` together, and commit both in a separate commit. Editing `pyproject.toml` by hand leaves `uv.lock` stale, and CI then fails on every run.

### If something goes wrong

- **A check fails in the `checks` job.** Nothing is built or published. Delete the GitHub release and the tag, fix the problem on `main`, and start again from step 3.
- **Release commit is not on `main`, or is not the tagged commit.** The build job fails and nothing is published. Delete the GitHub release and the tag, tag the release commit on `main`, and start again from step 5, including publishing a new GitHub release. Pushing a tag alone does not start the workflow.
- **Tag and version do not match.** The build job fails and nothing is published. Delete the GitHub release and the tag (`git push origin :refs/tags/vX.Y.Z`), fix the version, and start again from step 1.
- **The built wheel does not run.** The build job fails and nothing is published. Fix the packaging on `main`, delete the GitHub release and the tag, and start again from step 3.
- **Publish rejected by PyPI.** Check that the trusted publisher values in PyPI match the workflow file name and environment name exactly.
- **The publish job failed partway, or the run shows as cancelled.** Check which files PyPI already holds for the version. Re-run the failed jobs from the same workflow run, so the same `dist` artifact is uploaded; do not start a new release for the same version. If a file PyPI holds does not match the SHA-256 in the run summary, treat it as a bad release.
- **A bad release reached PyPI.** A file name can never be uploaded twice, so a fix needs a new version. Yank the release on PyPI and publish a new patch version. Yanking does not stop installs that pin the exact version. If a file is compromised rather than merely broken, also delete the release on PyPI, report it to PyPI security (`security@pypi.org`), and tell known users.

## Accepted risks

- **The publish action's container image is pulled by tag.** `pypa/gh-action-pypi-publish` is pinned to a commit, but at that commit it runs `docker://ghcr.io/pypa/gh-action-pypi-publish:<ref>`, a registry tag rather than an image digest, in the only job that holds `id-token: write`. Accepted (Session 2d): the image is published by PyPA, the same maintainers as the pinned action, and the action produces PyPI attestations that `uv publish` would not. Revisit before 1.0.
