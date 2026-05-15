# Issue #18 — GHCR versioning + `prod` pin + retention

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape GHCR image distribution so every published image is gated on green tests, deploy hosts pull `:prod` by default, and old `sha-*` versions get pruned weekly.

**Architecture:** Three workflow / config touches. (1) Merge the existing `build-image.yml` into `ci.yml` as a `publish-container` job that depends on `test`. (2) Add `.github/workflows/cleanup-images.yml` running weekly via `actions/delete-package-versions@v5`. (3) Update `Makefile` so `pull-registry` defaults to `:prod` with `TAG=...` override; clean up `deploy/README.md` GHCR-auth caveats.

**Tech Stack:** GitHub Actions, `docker/build-push-action@v6`, `docker/login-action@v3`, `actions/delete-package-versions@v5`, Makefile, Podman.

**Spec:** [docs/superpowers/specs/2026-05-15-issue-18-ghcr-versioning-design.md](../specs/2026-05-15-issue-18-ghcr-versioning-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/18

**Branch:** `feat/issue-18-ghcr-versioning` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-18/`)

---

## Working notes for the implementer

- No Python source touched. No new pytest tests. Pre-commit's `pytest (unit, fast)` hook will still run on each commit; it should remain green.
- GitHub Actions workflows can be syntax-validated locally with `uv run python -c 'import yaml; yaml.safe_load(open("PATH"))'`. The PR itself is the integration test — its CI run exercises the rewritten `ci.yml` (PR path) and the merge commit exercises the master-push path.
- Don't try to run the cleanup workflow on a PR — its trigger is cron / `workflow_dispatch` only. Smoke-testing it requires merging to master first.
- After merge the user runs **one** out-of-band command:
  ```
  gh api -X PATCH /user/packages/container/driftnote -f visibility=public
  ```
  The PR description documents this.

---

## Chunk 1: CI workflow restructure

### Task 1.1: Replace `.github/workflows/ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Overwrite `ci.yml` with the consolidated workflow**

Replace the entire contents of `.github/workflows/ci.yml` with:

```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

permissions:
  contents: read
  packages: write   # publish-container needs this; no-op for jobs that don't use the token

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Set up uv
        # Need a uv recent enough to manage a fully-patched Python 3.14.
        # uv 0.5.x predates 3.14 and resolves '.python-version: 3.14' to an
        # incomplete build missing PEP-750 ast nodes (ast.TemplateStr) — mypy
        # crashes on import. setup-uv only publishes major tags up to v7;
        # pin v8.1.0 explicitly.
        uses: astral-sh/setup-uv@v8.1.0
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --frozen

      - name: Lint
        run: uv run ruff check src tests

      - name: Format check
        run: uv run ruff format --check src tests

      - name: Type check
        run: uv run mypy

      - name: Tests (excluding live)
        run: uv run pytest -m "not live" -v --cov=driftnote --cov-report=term-missing

  build-container:
    # PR-only smoke build (no push). Catches Containerfile breakage in review.
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v5
      - name: Build container (smoke)
        run: docker build -f Containerfile -t driftnote:ci .

  publish-container:
    # Master-push only, after tests pass. Publishes :latest, :prod, :sha-<short>.
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

Key shape vs. the current `ci.yml`:
- Workflow-level `permissions:` block expanded with `packages: write` (needed by `publish-container`).
- `build-container` keeps the same body but is now gated `if: github.event_name == 'pull_request'`.
- New `publish-container` job appended with the build-and-push body (lifted from the old `build-image.yml`).

- [ ] **Step 2: Validate YAML syntax**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-18
uv run python -c 'import yaml; yaml.safe_load(open(".github/workflows/ci.yml"))' && echo OK
```

Expected: `OK`.

(No commit yet — Task 1.2 lands in the same commit.)

### Task 1.2: Delete `.github/workflows/build-image.yml`

**Files:**
- Delete: `.github/workflows/build-image.yml`

- [ ] **Step 1: Remove the file**

```bash
git rm .github/workflows/build-image.yml
```

- [ ] **Step 2: Confirm only `ci.yml` and `cleanup-images.yml` (next chunk, doesn't exist yet) will remain**

```bash
ls .github/workflows/
```

Expected: `ci.yml` only. `cleanup-images.yml` will be added in Chunk 2.

- [ ] **Step 3: Commit Tasks 1.1 + 1.2 together**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: gate container publish on tests; drop standalone build-image workflow"
```

(The `git rm` from Step 1 above stages the deletion automatically; both modifications are in the staging area.)

---

## Chunk 2: Cleanup workflow

### Task 2.1: Create `.github/workflows/cleanup-images.yml`

**Files:**
- Create: `.github/workflows/cleanup-images.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/cleanup-images.yml` with this exact content:

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
      - name: Prune old GHCR versions
        uses: actions/delete-package-versions@v5
        with:
          package-name: driftnote
          package-type: container
          min-versions-to-keep: 15
          delete-only-untagged-versions: false
          ignore-versions: '^(latest|prod)$'
```

Notes for the implementer:
- A GHCR "version" is one image digest (one multi-arch manifest). Each green master push creates exactly one version. `min-versions-to-keep: 15` retains the 15 most-recent master builds.
- `delete-only-untagged-versions: false` allows deletion of versions whose only remaining tag is `sha-<short>`. Without this, every old version would be kept forever because every version has an immutable sha tag.
- `ignore-versions: '^(latest|prod)$'` is belt-and-braces — versions tagged `latest`/`prod` are the most recent and wouldn't be candidates anyway, but explicit exclusion documents intent and protects against a future change that ages-out the rolling tag.

- [ ] **Step 2: Validate YAML syntax**

```bash
uv run python -c 'import yaml; yaml.safe_load(open(".github/workflows/cleanup-images.yml"))' && echo OK
```

Expected: `OK`.

- [ ] **Step 3: Confirm directory now has exactly the two intended files**

```bash
ls .github/workflows/
```

Expected: `ci.yml  cleanup-images.yml`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/cleanup-images.yml
git commit -m "ci: weekly GHCR image cleanup; keep last 15 versions"
```

---

## Chunk 3: Makefile + deploy/README

### Task 3.1: Update Makefile — `TAG` variable + `:prod` default

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Update the variable block**

Open `Makefile`. Find the existing line (around line 22-23):

```makefile
LOCAL_IMAGE    := localhost/driftnote:local
REGISTRY_IMAGE := ghcr.io/maciej-makowski/driftnote:latest
```

Replace those two lines with:

```makefile
LOCAL_IMAGE    := localhost/driftnote:local
# Default to the rolling `:prod` tag; override with `make pull-registry TAG=sha-abc1234`
# to pin to a specific build. The TAG= override accepts any GHCR tag verbatim.
TAG            ?= prod
REGISTRY_IMAGE := ghcr.io/maciej-makowski/driftnote:$(TAG)
```

- [ ] **Step 2: Update the help text**

Locate the `help:` target (around line 30-49). Find the help line for `pull-registry`:

```
  pull-registry  Alternative to build: pull from GHCR + retag. Requires GHCR auth.
```

Replace with:

```
  pull-registry  Alternative to build: pull from GHCR + retag. Defaults to :prod;
                 override with `make pull-registry TAG=sha-abc1234`.
```

The `Requires GHCR auth` claim is dropped — the package will be public after merge.

- [ ] **Step 3: Update the existing comment block on the `pull-registry` target**

Around line 83-89, the existing block reads:

```makefile
# Alternative to `build`: pull a prebuilt image from GHCR. Requires the
# package to be public, OR `podman login ghcr.io` on this host. Most
# personal installs are better off with `build`; this target is here for
# anyone who explicitly prefers the registry path.
pull-registry:
	@podman pull "$(REGISTRY_IMAGE)"
	@podman tag "$(REGISTRY_IMAGE)" "$(LOCAL_IMAGE)"
	@echo "✓ pulled $(REGISTRY_IMAGE) and tagged as $(LOCAL_IMAGE)"
```

Replace the comment with:

```makefile
# Alternative to `build`: pull a prebuilt image from GHCR. The package is
# public — no `podman login` required. Defaults to the `:prod` rolling tag;
# pin to a specific build via `make pull-registry TAG=sha-abc1234`.
```

The target body is unchanged.

- [ ] **Step 4: Smoke-test the Makefile parses**

```bash
make -n pull-registry
```

Expected output (the variable interpolates):
```
podman pull "ghcr.io/maciej-makowski/driftnote:prod"
podman tag "ghcr.io/maciej-makowski/driftnote:prod" "localhost/driftnote:local"
echo "✓ pulled ghcr.io/maciej-makowski/driftnote:prod and tagged as localhost/driftnote:local"
```

And with the override:

```bash
make -n pull-registry TAG=sha-abc1234
```

Expected output references `:sha-abc1234` instead of `:prod`.

(No commit yet — Tasks 3.1 + 3.2 land together.)

### Task 3.2: Update `deploy/README.md` — drop auth caveat, add pinning note

**Files:**
- Modify: `deploy/README.md`

- [ ] **Step 1: Replace the registry-pull paragraph**

Open `deploy/README.md`. Find the paragraph around line 152 that currently reads:

```
The default install builds the image locally from the Containerfile in your checkout — no GitHub interaction is needed beyond the initial `git clone` in §3. If you'd rather pull a prebuilt image from GHCR (and have logged in via `podman login ghcr.io`, since the package is private), run `make pull-registry` instead of `make build` (or as a substitute for `make install`'s build step: `make check-prereqs scripts units pull-registry start`).
```

Replace with:

```
The default install builds the image locally from the Containerfile in your checkout — no GitHub interaction is needed beyond the initial `git clone` in §3. If you'd rather pull a prebuilt image from GHCR, run `make pull-registry` instead of `make build` (or as a substitute for `make install`'s build step: `make check-prereqs scripts units pull-registry start`). The GHCR package is public; no `podman login` required.

`make pull-registry` defaults to the `:prod` rolling tag — always the latest build that passed CI. To pin to a specific build (e.g. after a regression on `master`), pass `TAG=sha-<short>` from the GHCR package page:

```bash
make pull-registry TAG=sha-abc1234
make restart
```

`make pull-registry TAG=prod` returns to the rolling tag.
```

(The nested triple-backtick block above is rendered correctly because the surrounding fence is a plain paragraph, not a code block. If your editor's preview struggles, that's just preview rendering — the markdown is well-formed.)

- [ ] **Step 2: Update the rollback paragraph**

Find around line 297:

```
(Or, if you're on the GHCR-pull path: `make pull-registry && make restart`.)
```

Replace with:

```
(Or, if you're on the GHCR-pull path: `make pull-registry TAG=sha-abc1234 && make restart` — substitute the short SHA of a known-good previous build from the GHCR package page.)
```

- [ ] **Step 3: Confirm there are no other "GHCR auth" or "package is private" mentions**

```bash
grep -nE "GHCR auth|package is private|podman login" deploy/README.md
```

Expected: empty (or only matches in unrelated contexts — review each match).

- [ ] **Step 4: Commit Tasks 3.1 + 3.2 together**

```bash
git add Makefile deploy/README.md
git commit -m "deploy: make pull-registry default to :prod; drop auth caveats"
```

---

## Chunk 4: Final verification + PR

### Task 4.1: Verify the full diff

- [ ] **Step 1: Show the diff vs master**

```bash
git log --oneline master..HEAD
git diff --stat master..HEAD
```

Expected: 3 new feature commits on top of the spec + plan commits already on the branch (so 5+ total). Diff stat should touch:
- `.github/workflows/ci.yml` (modified)
- `.github/workflows/build-image.yml` (deleted)
- `.github/workflows/cleanup-images.yml` (created)
- `Makefile` (modified)
- `deploy/README.md` (modified)
- `docs/superpowers/specs/2026-05-15-issue-18-ghcr-versioning-design.md` (created)
- `docs/superpowers/plans/2026-05-15-issue-18-ghcr-versioning.md` (created — this file)

- [ ] **Step 2: Sanity-check the fast suite still passes**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: green. No Python source changed; this is a defensive run to confirm the pre-commit hook history is consistent.

### Task 4.2: Push + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin feat/issue-18-ghcr-versioning
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "ci: GHCR versioning + prod pin + weekly cleanup (#18)" --body "$(cat <<'EOF'
## Summary

Closes #18.

- `publish-container` job in `ci.yml` builds + pushes only after `test` passes. Pushes `:latest`, `:prod`, `:sha-<short>` on master. Standalone `build-image.yml` is deleted.
- PRs run a non-pushing smoke build (`build-container`); failing tests block both build jobs.
- New `cleanup-images.yml` runs weekly (Sundays 03:00 UTC) + on `workflow_dispatch`, retaining the 15 most-recent versions via `actions/delete-package-versions@v5`. `:latest` / `:prod` are protected.
- `make pull-registry` defaults to `:prod`; `make pull-registry TAG=sha-abc1234` pins to a specific build.
- `deploy/README.md` drops the GHCR-auth caveats and documents the pinning workflow.

## Required post-merge step

Flip the GHCR package to public so deploy hosts can pull without auth:

```bash
gh api -X PATCH /user/packages/container/driftnote -f visibility=public
```

Until this runs, `make pull-registry` from a clean RPi will still 401.

## Verification

- [x] `ci.yml` YAML validates (`python -c 'import yaml; yaml.safe_load(...)'`)
- [x] `cleanup-images.yml` YAML validates
- [x] `make -n pull-registry` interpolates `:prod` by default; `TAG=sha-abc1234` overrides correctly
- [x] No remaining "GHCR auth" / "package is private" mentions in `deploy/README.md`
- [x] Fast test suite green (no Python source touched)
- [ ] (Post-merge) Manually trigger `cleanup-images.yml` once via `workflow_dispatch` and confirm old `sha-*` versions disappear while `latest`/`prod` survive
- [ ] (Post-merge) Pull from a clean machine: `podman pull ghcr.io/maciej-makowski/driftnote:prod` should succeed without auth

## Out of scope

- Image signing (cosign / sigstore).
- Semver / git-tag releases — discussed and dropped as unnecessary for current scale.
- Repo-public decision — separate conversation.

## Spec + plan

- Spec: `docs/superpowers/specs/2026-05-15-issue-18-ghcr-versioning-design.md`
- Plan: `docs/superpowers/plans/2026-05-15-issue-18-ghcr-versioning.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
