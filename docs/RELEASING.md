# Releasing Cernis

Cernis is published to PyPI by `.github/workflows/publish.yml` using Trusted Publishing. The workflow holds no tokens or secrets: PyPI trusts a short-lived OpenID Connect token that GitHub issues to that workflow, in that repository, running in the `pypi` environment.

## One-time setup

### PyPI trusted publisher

1. Sign in to PyPI as an owner of the `cernis` project.
2. Open **Your projects**, then **cernis**, then **Manage**, then **Publishing**.
3. Under **Add a new publisher**, choose **GitHub** and enter:
   - Owner: `kenwalger`
   - Repository name: `cernis`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
4. Save. Any API token previously created for this project can then be revoked.

All four values must match exactly. A publish from any other workflow file, repository, or environment is rejected by PyPI.

### GitHub environment

1. In the `kenwalger/cernis` repository, open **Settings**, then **Environments**, then **New environment**, and name it `pypi`.
2. Under **Deployment protection rules**, enable **Required reviewers** and add yourself (and any other maintainer allowed to release).
3. Under **Deployment branches and tags**, choose **Selected branches and tags** and add a tag rule `v*`, so only a release tag can deploy to this environment.
4. Add no secrets or variables to the environment. Trusted Publishing does not use them.

## Releasing a version

The workflow runs three jobs in order, and each must pass before the next starts:

1. `checks` runs `ci.yml`, the full check list from `CLAUDE.md` on every supported Python, against the tagged commit.
2. `build` checks that the tag is `vX.Y.Z` with no leading zeros and equals `v` plus the version in `pyproject.toml`, checks that the tagged commit is on `main`, builds the sdist and wheel, and checks that `dist/` holds exactly `cernis-X.Y.Z-py3-none-any.whl` and `cernis-X.Y.Z.tar.gz`.
3. `publish` waits for approval on the `pypi` environment, then uploads.

1. **Bump the version.** Set the release version in `pyproject.toml`, for example with `uv version 0.1.0`, and confirm with `uv version --short`. Run `uv lock` so `uv.lock` records the new version.
2. **Update the changelog.** In `CHANGELOG.md`, rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD` and start a new empty `[Unreleased]` section above it.
3. **Run the full check list** from `CLAUDE.md` and confirm everything passes.
4. **Commit** the version, lock file, and changelog: `git commit -m "Release X.Y.Z"`, then push to `main`. Tag only a commit that is on `main`; the build job rejects any other.
5. **Tag** the release commit and push the tag:

   ```sh
   git tag -a vX.Y.Z -m "Cernis X.Y.Z"
   git push origin vX.Y.Z
   ```

6. **Publish a GitHub release.** On GitHub, open **Releases**, then **Draft a new release**, choose the `vX.Y.Z` tag, paste the changelog section as the notes, and click **Publish release**. Publishing (not drafting or saving) starts the workflow.
7. **Approve the deployment.** The `checks` and `build` jobs run first, and the `publish` job then waits for approval on the `pypi` environment. Open the workflow run under **Actions**, check that both jobs passed and that the `dist` artifact is present, then click **Review deployments**, select `pypi`, and approve.
8. **Verify** that `https://pypi.org/project/cernis/X.Y.Z/` exists and that `uvx cernis@X.Y.Z --version` prints `X.Y.Z`.

After the release, set the version in `pyproject.toml` to the next development version (for example `0.2.0.dev0`) in a separate commit.

## If something goes wrong

- **A check fails in the `checks` job.** Nothing is built or published. Delete the GitHub release and the tag, fix the problem on `main`, and start again from step 3.
- **Release commit is not on `main`.** The build job fails and nothing is published. Delete the GitHub release and the tag, and tag the commit on `main` instead.
- **Tag and version do not match.** The build job fails and nothing is published. Delete the GitHub release and the tag (`git push origin :refs/tags/vX.Y.Z`), fix the version, and start again from step 1.
- **Publish rejected by PyPI.** Check that the trusted publisher values in PyPI match the workflow file name and environment name exactly.
- **A bad release reached PyPI.** A version number can never be uploaded twice. Yank the release on PyPI and publish a new patch version.
