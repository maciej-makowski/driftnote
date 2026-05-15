# GHCR image versioning, `prod` pin tag, and public package distribution

> Design spec for [issue #18](https://github.com/maciej-makowski/driftnote/issues/18).

## Goal

Move the GHCR image distribution from "build on every master push, tag `latest` and `sha-<full>`, gate behind GitHub auth" to a sustainable pattern:

- Gate every published image on green tests.
- Tag images with a small, memorable, intentional set of identifiers.
- Give the RPi (and any other deploy host) a single rolling tag — `prod` — that always points at the latest tested image.
- Drop the GHCR auth requirement by flipping the package to public.
- Document the version-pinning escape hatch.

## Architecture

Two changes:

1. **CI restructure**: the build-and-push GitHub Actions workflow merges into `ci.yml` as a `publish-container` job that runs only after `test` passes and only on master / git-tag pushes. The standalone `build-image.yml` is deleted. PR builds keep a smoke `build-container` job that builds the Containerfile but doesn't push.
2. **One-time operational task** (not in the PR): flip the GHCR package visibility from private to public via `gh api`.

The `Makefile` `pull-registry` target is parameterised to default to `:prod` with an opt-in `TAG=...` override for pinning. The quadlet (`deploy/driftnote.container`) continues to reference `localhost/driftnote:local` — the install path remains identical regardless of whether the host built locally or pulled from GHCR.

## Tag scheme

On every push to master that passes CI:

| Tag | Mutable? | Purpose |
|---|---|---|
| `latest` | yes (rolling) | Docker convention; bleeding-edge of master |
| `prod` | yes (rolling) | What deploy hosts pull by default; pin override for the user |
| `sha-<short>` | no (immutable) | Emergency pin handle (e.g. `sha-8e38c05`) |

Short SHA is the 7-character `git rev-parse --short HEAD` form — readable, copy-pasteable, no namespace clutter on the GHCR page.

`latest` and `prod` are synonymous *for now*. The separation exists so the user can later decouple them (e.g. `latest` points at a feature branch's prerelease while `prod` stays on a stable release). YAGNI to use that decoupling today; the design accommodates it.

**Semver / git-tag-driven releases are out of scope for this PR** — discussed during brainstorming and dropped as unnecessary overcomplication for a one-user app. The `sha-<short>` immutable tag is the sole pinning handle. If formal releases become useful later, this design can be extended with a `v*.*.*` trigger and an immutable version tag without restructuring.

### Out of scope

- Multi-arch tags (the workflow already builds `linux/arm64` + `linux/amd64` into one manifest list — no change needed).
- Image signing (cosign / sigstore). Deferred per #18.
- Semver / git-tag releases (`v0.1.0`, etc).
- Auto-derived semver from PR labels or commit messages.
- Floating minor/major version tags (`0.1`, `0`).

## GitHub Actions

`.github/workflows/ci.yml` gains a third job, structured to mirror the existing two-job split:

```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

permissions:
  contents: read
  packages: write   # publish-container needs this; safe-default no-op for other jobs

jobs:
  test:
    # ...unchanged...

  build-container:
    # PR-only smoke build (no push).
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v5
      - name: Build container (smoke)
        run: docker build -f Containerfile -t driftnote:ci .

  publish-container:
    # Master-push only, after tests pass.
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/master'
    steps:
      - uses: actions/checkout@v5
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3
      - name: Compute tags
        id: tags
        run: |
          IMAGE="ghcr.io/${{ github.repository_owner }}/driftnote"
          SHORT_SHA=$(git rev-parse --short HEAD)
          echo "tags=$IMAGE:latest,$IMAGE:prod,$IMAGE:sha-$SHORT_SHA" >> "$GITHUB_OUTPUT"
      - name: Build & push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Containerfile
          push: true
          platforms: linux/arm64,linux/amd64
          tags: ${{ steps.tags.outputs.tags }}
```

`.github/workflows/build-image.yml` is deleted.

Key behaviours:

- **`test` always runs**, on PRs and pushes.
- **`build-container` runs on PRs only**, after `test`, builds without pushing. Catches Containerfile breakage in review.
- **`publish-container` runs on master-push only**, after `test`, pushes the three tags.
- **A failing `test` job blocks both build jobs.** No more "broken image lands on `latest` because tests are red."

## Makefile

`Makefile`:

```makefile
# Default to the rolling `prod` tag; override with `make pull-registry TAG=0.1.0`
# to pin to a specific semver release.
TAG            ?= prod
REGISTRY_IMAGE := ghcr.io/maciej-makowski/driftnote:$(TAG)
```

The `pull-registry` target body is unchanged — `podman pull "$(REGISTRY_IMAGE)"` plus `podman tag` to `localhost/driftnote:local`. The user-facing change is the implicit `:prod` default and the new `TAG=...` override.

The `help` text updates to mention this:

```
  pull-registry  Alternative to build: pull from GHCR + retag. Defaults to
                 :prod; override with `make pull-registry TAG=0.1.0`.
```

## Quadlet

`deploy/driftnote.container` is **unchanged**. It continues to reference `localhost/driftnote:local`. The pull-vs-build choice happens at the `make` level; both paths terminate with the same locally-tagged image.

## Retention / cleanup workflow

A new `.github/workflows/cleanup-images.yml` runs weekly (and on-demand) to keep the GHCR package page scannable. Without cleanup, each master push leaves an `sha-<short>`-tagged version behind indefinitely.

**Retention policy: keep the 15 most-recent versions.** That's roughly one month of activity at current pace — generous enough to roll back to anything plausibly useful, aggressive enough that the package page stays readable.

```yaml
name: Clean up old container images
on:
  schedule:
    - cron: "0 3 * * 0"   # Sundays 03:00 UTC
  workflow_dispatch:

permissions:
  packages: write

jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/delete-package-versions@v5
        with:
          package-name: driftnote
          package-type: container
          min-versions-to-keep: 15
          delete-only-untagged-versions: false
          ignore-versions: '^(latest|prod)$'
```

**Behaviour:**

- A GHCR "version" is one image digest (one multi-arch manifest). Each green master push creates one new version. So `min-versions-to-keep: 15` retains the 15 most-recent master-push builds.
- `delete-only-untagged-versions: false` allows deletion of versions whose only remaining tag is `sha-<short>`. Without this, every old version would be retained forever because they each have an immutable sha tag.
- `ignore-versions: '^(latest|prod)$'` is belt-and-braces — versions tagged with those names are the most recent and wouldn't be candidates anyway, but explicit exclusion documents intent and protects against a future change that ages-out the rolling tag.
- Weekly cron is enough; manual `workflow_dispatch` is available if storage ever becomes urgent (it won't for public packages).

**Size context:** the image is ~300–400 MB per version in the registry (compressed multi-arch). With 15 retained, total storage is ~5–6 GB. Public GHCR packages have unlimited storage so this isn't a billing concern — the goal is hygiene, not cost.

## `deploy/README.md` updates

- Drop the "Requires GHCR auth" caveat throughout — the package is public after this lands.
- Add a one-paragraph "Pinning a specific version" subsection under the existing registry-pull description, pointing at `make pull-registry TAG=0.1.0` and noting the `sha-<short>` and semver tags as the immutable handles.

## One-time operational task (not in the PR)

After the PR merges, the user runs once:

```bash
gh api -X PATCH /user/packages/container/driftnote -f visibility=public
```

The PR description documents this as a required post-merge step.

## Files touched

| File | Change |
|---|---|
| `.github/workflows/ci.yml` | Add `publish-container` job; gate existing `build-container` to PRs; add `packages: write` permission |
| `.github/workflows/build-image.yml` | Delete |
| `.github/workflows/cleanup-images.yml` | New — weekly retention pruning |
| `Makefile` | Add `TAG ?= prod`; update `REGISTRY_IMAGE` to interpolate; update help |
| `deploy/README.md` | Drop GHCR auth caveats; add pinning-by-sha subsection |
| `docs/superpowers/specs/2026-05-15-issue-18-ghcr-versioning-design.md` | This spec |

No production code touched. No new tests — the change is workflow + Makefile + docs.

## Verification

- **CI workflow runs on PR**: only `test` + `build-container` (smoke) run, no `publish-container`.
- **CI workflow runs on master push**: `test` runs; if green, `publish-container` builds + pushes three tags (`latest`, `prod`, `sha-<short>`).
- **CI workflow with failing tests**: `test` fails; neither build job runs.
- **GHCR package public**: `podman pull ghcr.io/maciej-makowski/driftnote:prod` from a clean machine (no auth) succeeds.
- **Pin override**: `make pull-registry TAG=sha-abc1234` pulls that specific image and retags it as `localhost/driftnote:local`.
- **Cleanup workflow**: manual `workflow_dispatch` run prunes versions back to the 15-most-recent; verify on the GHCR package page that older `sha-*`-tagged versions disappear and `latest`/`prod` versions are untouched.

The CI workflow changes are exercised on the PR itself (PR-only build path) and on the merge commit to master (push path). The cleanup workflow can be smoke-tested by manually triggering it once after merge.

## Acceptance criteria

- [ ] `publish-container` job pushes `latest` + `prod` + `sha-<short>` on green master push.
- [ ] PR builds run the smoke `build-container` only — no GHCR push.
- [ ] Failing `test` blocks both build jobs.
- [ ] `build-image.yml` is deleted.
- [ ] `cleanup-images.yml` runs weekly + on `workflow_dispatch`, retains 15 most-recent versions, never deletes `latest`/`prod`.
- [ ] `make pull-registry` defaults to `:prod`; `make pull-registry TAG=sha-abc1234` pins to a specific build.
- [ ] `deploy/README.md` no longer mentions GHCR auth requirements; documents pinning by `sha-<short>`.
- [ ] PR body documents the one-time `gh api` visibility flip.

## Risks

**Risk:** The GitHub Actions YAML changes can fail in subtle ways (e.g. `if:` expression typo, permissions mis-scoped). A bad YAML on master could break the build pipeline.
**Mitigation:** PR runs are themselves CI exercises — the workflow file change is validated by the PR's own runs (the new `build-container` PR-only smoke build will fire). The `publish-container` job runs only on the post-merge push, so a syntax error would be caught at PR time. Manual `workflow_dispatch` is available as a fallback.

**Risk:** Visibility flip is a one-way door in practice — once public, image hashes are scraped. If a sensitive layer slips into a future image, the leak is harder to contain.
**Mitigation:** Already mitigated by the architecture — secrets are mounted at runtime, not baked into the image. The Containerfile only `COPY`s the `src/` tree, `pyproject.toml`, and lockfile.

**Risk:** Existing GHCR images under `:sha-<full>` (the current scheme) become orphaned by the tag-naming change to `:sha-<short>`.
**Mitigation:** Cosmetic only — they still pull by full tag. Don't bother deleting them; they age out when retention policy lands (deferred).

**Risk:** `prod` and `latest` being synonymous today encourages future drift where someone re-uses one without the other. Documentation must be clear that `prod` is the user-pin and `latest` is the Docker convention.
**Mitigation:** Spec text + README phrasing makes this explicit. The two tags moving in lockstep is intentional today; decoupling is a future spec.

## Out of scope

- Image signing (cosign / sigstore).
- Semver / git-tag releases — discussed and dropped as unnecessary for current scale.
- Repo-public decision — separate conversation after this lands.
- Branch protection rules (a corollary benefit if repo eventually goes public).
- Auto-derived semver from PR labels.
