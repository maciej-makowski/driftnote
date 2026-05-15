# Issue #34 — Quadlet reflects actual image source

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the installed quadlet's `Image=` line reflect the actual image source (local-build vs GHCR-pull), instead of always saying `localhost/driftnote:local` and silently retagging.

**Architecture:** `deploy/driftnote.container` becomes a template with `Image=__IMAGE__`. The Makefile's `units` target substitutes the placeholder using a target-specific `IMAGE` variable. Two install paths — `make install` (local) and `make install-registry [TAG=...]` (registry) — each set their own `IMAGE` value. `pull-registry` drops its retag.

**Tech Stack:** GNU Make target-specific variables, `sed`, Podman, systemd-quadlet.

**Spec:** [docs/superpowers/specs/2026-05-15-issue-34-quadlet-image-source-design.md](../specs/2026-05-15-issue-34-quadlet-image-source-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/34

**Branch:** `feat/issue-34-quadlet-image-source` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-34/`)

---

## Working notes for the implementer

- No Python source touched. No new pytest tests. Pre-commit's `pytest (unit, fast)` will still run — should remain green throughout.
- Verification is via `make -n <target>` (dry-run) and `git diff` inspection. `make` does NOT need to be run for real (no install on this machine).
- The `units` target gains an `IMAGE=` guard. Calling targets (`install`, `install-registry`) set it; standalone `make units` errors out cleanly.
- `sed` uses `|` as delimiter so the `/` in registry paths doesn't conflict.

---

## Chunk 1: Convert the quadlet to a template

### Task 1.1: Replace the `Image=` line and rewrite the comment block

**Files:**
- Modify: `deploy/driftnote.container`

- [ ] **Step 1: Open the file and locate lines 8-13**

The current content of those lines:

```
[Container]
# `make install` (or `make build`) builds the image locally from the
# Containerfile and tags it as localhost/driftnote:local. If you'd rather
# pull a prebuilt image from GHCR, run `make pull-registry` instead — it
# tags the GHCR image as the same name so this Image= line stays correct.
Image=localhost/driftnote:local
```

- [ ] **Step 2: Replace those 6 lines with**

```
[Container]
# Image= is filled in by the Makefile when the quadlet is installed.
# `make install` substitutes `localhost/driftnote:local` (local build).
# `make install-registry [TAG=...]` substitutes `ghcr.io/maciej-makowski/driftnote:<TAG>`.
# The repo file's __IMAGE__ placeholder is invalid for direct copy — use the Makefile.
Image=__IMAGE__
```

Everything below the `Image=` line (UserNS, Volume, Environment, etc.) is unchanged.

- [ ] **Step 3: Verify the file content**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-34
grep -n "^Image=" deploy/driftnote.container
```

Expected: exactly one match, line containing `Image=__IMAGE__`.

```bash
grep -c "__IMAGE__" deploy/driftnote.container
```

Expected: `1`.

- [ ] **Step 4: Commit**

```bash
git add deploy/driftnote.container
git commit -m "deploy: quadlet template uses __IMAGE__ placeholder"
```

---

## Chunk 2: Makefile — substitution, two install paths, drop retag

### Task 2.1: Replace the `.PHONY` declaration

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Locate the existing `.PHONY` block at lines 29-31**

```makefile
.PHONY: help install uninstall reinstall \
        check-prereqs scripts units build pull-registry \
        start stop restart status logs
```

- [ ] **Step 2: Replace it with**

```makefile
.PHONY: help install install-registry uninstall reinstall reinstall-registry \
        check-prereqs scripts units build pull-registry \
        start stop restart status logs
```

(Added `install-registry` after `install` and `reinstall-registry` after `reinstall`.)

### Task 2.2: Rewrite the `help` target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Locate the existing `help` target at lines 33-52**

It currently looks like:

```makefile
help:
	@echo "Driftnote rootless install (assumes you're in a checkout of the repo)."
	@echo ""
	@echo "Primary targets:"
	@echo "  install      End-to-end: verify prereqs, copy scripts + units, build image, enable services."
	@echo "  uninstall    Stop services and remove installed files. Data in ~/.driftnote/ is KEPT."
	@echo "  reinstall    uninstall + install (handy after editing deploy/* files)."
	@echo ""
	@echo "Operational targets:"
	@echo "  status       systemctl --user status for service + timer."
	@echo "  logs         Tail journalctl --user -u driftnote.service."
	@echo "  restart      systemctl --user restart driftnote.service."
	@echo "  stop / start Stop or (re-)enable the service + backup timer."
	@echo ""
	@echo "Component targets (rarely run directly):"
	@echo "  check-prereqs  Verify ~/.driftnote/{config.toml,driftnote.env} + linger."
	@echo "  scripts        Copy backup.sh + alert-email.py to ~/.local/lib/driftnote/scripts/."
	@echo "  units          Copy quadlet + backup units to ~/.config/, daemon-reload."
	@echo "  build          podman build -f Containerfile -t localhost/driftnote:local . (default)."
	@echo "  pull-registry  Alternative to build: pull from GHCR + retag. Defaults to :prod; override with `make pull-registry TAG=sha-abc1234`."
```

- [ ] **Step 2: Replace the entire `help` target body with**

```makefile
help:
	@echo "Driftnote rootless install (assumes you're in a checkout of the repo)."
	@echo ""
	@echo "Primary targets:"
	@echo "  install              End-to-end LOCAL BUILD: build image, install units, start."
	@echo "  install-registry     End-to-end REGISTRY PULL: pull image, install units, start."
	@echo "                       Override with TAG=, e.g. 'make install-registry TAG=sha-abc1234'."
	@echo "  uninstall            Stop services and remove installed files. ~/.driftnote/ KEPT."
	@echo "  reinstall            uninstall + install (local-build path)."
	@echo "  reinstall-registry   uninstall + install-registry (registry-pull path)."
	@echo ""
	@echo "Operational targets:"
	@echo "  status               systemctl --user status for service + timer."
	@echo "  logs                 Tail journalctl --user -u driftnote.service."
	@echo "  restart              systemctl --user restart driftnote.service."
	@echo "  stop / start         Stop or (re-)enable the service + backup timer."
	@echo ""
	@echo "Component targets (rarely run directly):"
	@echo "  check-prereqs        Verify ~/.driftnote/{config.toml,driftnote.env} + linger."
	@echo "  scripts              Copy backup.sh + alert-email.py to ~/.local/lib/driftnote/scripts/."
	@echo "  units                Copy quadlet + backup units. Requires IMAGE=... set by caller."
	@echo "  build                Build localhost/driftnote:local from Containerfile."
	@echo "  pull-registry        Pull from GHCR (no retag). TAG=prod default."
```

### Task 2.3: Rewrite the `units` target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Locate the existing `units` target (around lines 73-80)**

```makefile
units:
	@install -d "$(QUADLET_DIR)" "$(USER_UNIT_DIR)"
	@install -m 0644 deploy/driftnote.container          "$(QUADLET_DIR)/"
	@install -m 0644 deploy/driftnote-backup.service     "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup-failure.service "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup.timer       "$(USER_UNIT_DIR)/"
	@systemctl --user daemon-reload
	@echo "✓ units installed; systemd reloaded"
```

- [ ] **Step 2: Replace the entire target body with**

```makefile
# IMAGE must be set by the calling target (install / install-registry / reinstall*).
# Standalone `make units IMAGE=localhost/driftnote:local` works as an escape hatch
# when refreshing just the units after editing deploy/*.service files.
units:
	@test -n "$(IMAGE)" || { echo "ERROR: IMAGE must be set. Use 'make install', 'make install-registry', or 'make units IMAGE=...'."; exit 1; }
	@install -d "$(QUADLET_DIR)" "$(USER_UNIT_DIR)"
	@sed 's|__IMAGE__|$(IMAGE)|' deploy/driftnote.container > "$(QUADLET_DIR)/driftnote.container"
	@chmod 0644 "$(QUADLET_DIR)/driftnote.container"
	@install -m 0644 deploy/driftnote-backup.service         "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup-failure.service "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup.timer           "$(USER_UNIT_DIR)/"
	@systemctl --user daemon-reload
	@echo "✓ units installed (Image=$(IMAGE)); systemd reloaded"
```

Three changes vs. the existing target:
1. Added a leading guard that errors if `IMAGE` is unset.
2. Replaced the bare `install -m 0644 deploy/driftnote.container ...` with `sed | > ; chmod 0644` to substitute the placeholder.
3. Updated the final `echo` to surface which `Image=` was installed.

### Task 2.4: Rewrite the `pull-registry` target — drop the retag

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Locate the existing `pull-registry` target (around lines 86-92)**

```makefile
# Alternative to `build`: pull a prebuilt image from GHCR. The package is
# public — no `podman login` required. Defaults to the `:prod` rolling tag;
# pin to a specific build via `make pull-registry TAG=sha-abc1234`.
pull-registry:
	@podman pull "$(REGISTRY_IMAGE)"
	@podman tag "$(REGISTRY_IMAGE)" "$(LOCAL_IMAGE)"
	@echo "✓ pulled $(REGISTRY_IMAGE) and tagged as $(LOCAL_IMAGE)"
```

- [ ] **Step 2: Replace the entire target (comment + body) with**

```makefile
# Pull from GHCR. The package is public — no `podman login` required.
# Defaults to `:prod`; pin via `make pull-registry TAG=sha-abc1234`.
# No retag — the quadlet references the registry image directly when installed
# via `make install-registry`.
pull-registry:
	@podman pull "$(REGISTRY_IMAGE)"
	@echo "✓ pulled $(REGISTRY_IMAGE)"
```

The `podman tag ...` line is gone. The comment is rewritten to reflect the new model.

### Task 2.5: Rewrite the `install` target — reorder prereqs, set IMAGE

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Locate the existing `install` target (around lines 120-124)**

```makefile
install: check-prereqs scripts units build start
	@echo ""
	@echo "Driftnote installed. Verify with:"
	@echo "    make status"
	@echo "    curl -sf https://driftnote.<your-domain>/healthz   # via Cloudflare Access"
```

- [ ] **Step 2: Replace it with**

```makefile
install: IMAGE := $(LOCAL_IMAGE)
install: check-prereqs scripts build units start
	@echo ""
	@echo "Driftnote installed (local build, Image=$(LOCAL_IMAGE)). Verify with:"
	@echo "    make status"
	@echo "    curl -sf https://driftnote.<your-domain>/healthz   # via Cloudflare Access"
```

Two changes:
1. Added the target-specific variable assignment `install: IMAGE := $(LOCAL_IMAGE)` on its own line BEFORE the prereqs line. GNU make propagates this to all prereqs (including `units`, which uses `$(IMAGE)`).
2. Reordered prereqs from `check-prereqs scripts units build start` to `check-prereqs scripts build units start`. `build` now precedes `units`. The image must exist before `systemctl start` (so `start` doesn't fail), and the new ordering makes the dependency obvious.

### Task 2.6: Add the `install-registry` target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Insert the new target immediately after `install`**

After the existing `install` target's closing `@echo` line (which after Task 2.5 ends with `# via Cloudflare Access`), add a blank line then:

```makefile
install-registry: IMAGE := $(REGISTRY_IMAGE)
install-registry: check-prereqs scripts pull-registry units start
	@echo ""
	@echo "Driftnote installed (registry pull, Image=$(REGISTRY_IMAGE)). Verify with:"
	@echo "    make status"
	@echo "    curl -sf https://driftnote.<your-domain>/healthz   # via Cloudflare Access"
```

Same shape as `install`, but `IMAGE := $(REGISTRY_IMAGE)` and the prereq chain has `pull-registry` in `build`'s slot.

### Task 2.7: Add the `reinstall-registry` target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Locate the existing `reinstall` target (around line 135)**

```makefile
reinstall: uninstall install
```

- [ ] **Step 2: Add the new alias on the line below it**

After the `reinstall: uninstall install` line, add:

```makefile
reinstall-registry: uninstall install-registry
```

### Task 2.8: Smoke-test the Makefile with `make -n`

**Files:**
- (Read-only verification of `Makefile`)

- [ ] **Step 1: Dry-run `make -n install`**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-34
make -n install 2>&1 | head -25
```

Expected output (key lines — full output is longer):
- `podman build -f Containerfile -t "localhost/driftnote:local" .` (from `build`)
- `sed 's|__IMAGE__|localhost/driftnote:local|' deploy/driftnote.container > "..."/driftnote.container` (from `units`)
- `systemctl --user start driftnote.service` (from `start`)

Verify the `sed` substitution string has `localhost/driftnote:local` (NOT `__IMAGE__` or `ghcr.io/...`).

- [ ] **Step 2: Dry-run `make -n install-registry`**

```bash
make -n install-registry 2>&1 | head -25
```

Expected key lines:
- `podman pull "ghcr.io/maciej-makowski/driftnote:prod"` (from `pull-registry`)
- `sed 's|__IMAGE__|ghcr.io/maciej-makowski/driftnote:prod|' deploy/driftnote.container > "..."/driftnote.container` (from `units`)

NO `podman tag` line (would prove the retag is gone). NO `podman build` line.

- [ ] **Step 3: Dry-run `make -n install-registry TAG=sha-abc1234`**

```bash
make -n install-registry TAG=sha-abc1234 2>&1 | head -25
```

Expected:
- `podman pull "ghcr.io/maciej-makowski/driftnote:sha-abc1234"`
- `sed 's|__IMAGE__|ghcr.io/maciej-makowski/driftnote:sha-abc1234|' deploy/driftnote.container > "..."`

- [ ] **Step 4: Dry-run `make -n pull-registry` and confirm NO retag**

```bash
make -n pull-registry
```

Expected:
- `podman pull "ghcr.io/maciej-makowski/driftnote:prod"`
- `echo "✓ pulled ghcr.io/maciej-makowski/driftnote:prod"`

Should NOT contain `podman tag`.

- [ ] **Step 5: Bare `make units` triggers the guard**

```bash
make units 2>&1 || true
```

Expected output contains:
- `ERROR: IMAGE must be set. Use 'make install', 'make install-registry', or 'make units IMAGE=...'.`

Exit code is non-zero (the `|| true` keeps the shell happy).

- [ ] **Step 6: Bare `make units IMAGE=localhost/driftnote:local` passes the guard**

```bash
make -n units IMAGE=localhost/driftnote:local 2>&1 | head -10
```

Expected output contains the `sed` line with `localhost/driftnote:local`.

- [ ] **Step 7: Commit Tasks 2.1–2.7 together**

```bash
git add Makefile
git commit -m "deploy: two install paths; quadlet image source via Makefile substitution"
```

---

## Chunk 3: `deploy/README.md` — describe both paths

### Task 3.1: Rewrite §4 (Install)

**Files:**
- Modify: `deploy/README.md`

- [ ] **Step 1: Locate §4 starting around line 142**

The section header is `## 4. Install scripts + systemd units, pull the image, start`.

The content runs from around line 142 through line 198 (just before `## 5. Post-deploy verification`).

- [ ] **Step 2: Replace the entire §4 contents (line 142 through to but not including the `---` separator before §5) with**

```markdown
## 4. Install scripts + systemd units, start

The project ships a `Makefile` that bundles the install + start steps into a single command. Two paths exist, both first-class:

### Path A: Local build (default)

Builds the container image on the RPi from the Containerfile in your checkout.

```bash
make install
```

`make install` runs in order: `check-prereqs` → `scripts` → `build` (`podman build -f Containerfile -t localhost/driftnote:local .`) → `units` (copies the quadlet with `Image=localhost/driftnote:local` substituted in) → `start`.

### Path B: Registry pull

Pulls the prebuilt image from GHCR. The package is public — no `podman login` required.

```bash
make install-registry
```

Defaults to the `:prod` rolling tag — always the latest build that passed CI. The installed quadlet has `Image=ghcr.io/maciej-makowski/driftnote:prod` so podman pulls updates directly from GHCR on every service start.

To pin to a specific build (e.g. after a regression on master):

```bash
make install-registry TAG=sha-abc1234
```

Look up the short SHA on the [GHCR package page](https://github.com/maciej-makowski/driftnote/pkgs/container/driftnote).

### Switching between paths

The two paths produce different quadlets on disk, so switching is a deliberate reinstall:

```bash
make reinstall-registry         # local → registry (default :prod)
make reinstall                  # registry → local
make reinstall-registry TAG=... # pin to / repin
```

### Day-to-day operations

Run `make help` to see every target. Useful day-to-day:

- `make status` — service + timer status
- `make logs` — tail `journalctl --user -u driftnote.service`
- `make pull-registry && make restart` — refresh the registry image (on the registry path) and restart
- `make build && make restart` — rebuild from source (on the local path) and restart
- `make uninstall` — stop services and remove installed files (KEEPS data in `~/.driftnote/`)

### Manual equivalent (if you don't want to use Make)

```bash
# User-local scripts directory.
install -d ~/.local/lib/driftnote/scripts
install -m 0755 scripts/backup.sh scripts/alert-email.py ~/.local/lib/driftnote/scripts/

# User-mode quadlet (substitute __IMAGE__ first) + user-mode systemd units.
install -d ~/.config/containers/systemd ~/.config/systemd/user
sed 's|__IMAGE__|localhost/driftnote:local|' deploy/driftnote.container > ~/.config/containers/systemd/driftnote.container
install -m 0644 deploy/driftnote-backup.service         ~/.config/systemd/user/
install -m 0644 deploy/driftnote-backup-failure.service ~/.config/systemd/user/
install -m 0644 deploy/driftnote-backup.timer           ~/.config/systemd/user/

# Build image locally, reload, start.
podman build -f Containerfile -t localhost/driftnote:local .
systemctl --user daemon-reload
# driftnote.service is quadlet-generated, so we just start it — the
# quadlet's [Install] WantedBy=default.target already auto-starts it
# on boot/login. systemctl enable on a generated unit fails.
systemctl --user start driftnote.service
# The backup timer is a regular unit, so enable it normally.
systemctl --user enable --now driftnote-backup.timer
```

For the registry path, replace the `sed` and `podman build` lines with:

```bash
sed 's|__IMAGE__|ghcr.io/maciej-makowski/driftnote:prod|' deploy/driftnote.container > ~/.config/containers/systemd/driftnote.container
podman pull ghcr.io/maciej-makowski/driftnote:prod
```

The `%h` specifier in the shipped unit files expands to your home directory at unit-load time, so the same files work for any user without editing. The quadlet at `~/.config/containers/systemd/driftnote.container` is translated to `driftnote.service` by the user's systemd manager on `daemon-reload`. The backup timer fires on the 1st at 03:00 (your local timezone, since user-mode units default to the user's timezone).
```

### Task 3.2: Update §7 — clarify it's the local-build path

**Files:**
- Modify: `deploy/README.md`

- [ ] **Step 1: Locate §7 around line 296**

```markdown
## 7. Update path

To upgrade to a newer release: `git pull` in the repo checkout, rebuild the image, then restart.

```bash
git pull
make build && make restart
journalctl --user -u driftnote.service -n 50   # confirm it came back up cleanly
```

(Or, if you're on the GHCR-pull path: `make pull-registry TAG=sha-abc1234 && make restart` — substitute the short SHA of a known-good previous build from the GHCR package page.)

If a future release introduces a database schema change, the release notes will include migration instructions. There is no automated migration tooling.
```

- [ ] **Step 2: Replace the entire §7 body (everything from "To upgrade…" through the migration line) with**

```markdown
The update flow depends on which install path you're on (see §4).

**Local-build path:** `git pull` in the repo checkout, rebuild, restart.

```bash
git pull
make build && make restart
journalctl --user -u driftnote.service -n 50   # confirm it came back up cleanly
```

**Registry-pull path:** the quadlet references `:prod` directly. Pull a fresh image (under the same tag) and restart — no `git pull` required for the deploy itself.

```bash
make pull-registry && make restart
journalctl --user -u driftnote.service -n 50
```

**Rollback** (registry path only): pin to a specific known-good build. Find the short SHA on the [GHCR package page](https://github.com/maciej-makowski/driftnote/pkgs/container/driftnote):

```bash
make reinstall-registry TAG=sha-abc1234
```

`make reinstall-registry` (no `TAG=` arg) returns to rolling `:prod`.

If a future release introduces a database schema change, the release notes will include migration instructions. There is no automated migration tooling.
```

### Task 3.3: Verify no stale references remain

**Files:**
- (Read-only verification of `deploy/README.md`)

- [ ] **Step 1: Grep for now-stale phrases**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-34
grep -nE "tags the GHCR image|podman tag .* localhost/driftnote:local|tags the GHCR image as|substitute for .make install" deploy/README.md
```

Expected: empty. (The Task 3.1 §4 rewrite drops all of these phrases.)

```bash
grep -nE "pull-registry.*&&.*restart" deploy/README.md
```

Expected: at most one or two matches, all in the new §7 ("Registry-pull path: …"), not in §4's old `(If you'd rather pull a prebuilt image)` phrasing.

- [ ] **Step 2: Commit Tasks 3.1–3.2 together**

```bash
git add deploy/README.md
git commit -m "deploy: README describes both install paths + new reinstall flow"
```

---

## Chunk 4: Final verification + PR

### Task 4.1: Full diff review

**Files:**
- (Read-only)

- [ ] **Step 1: Inspect the branch's full diff**

```bash
git log --oneline master..HEAD
git diff --stat master..HEAD
```

Expected: 5 commits on the branch (spec + spec-polish + plan + the 3 feature commits from Chunks 1-3). Diff stat touches:
- `Makefile` (modified)
- `deploy/driftnote.container` (modified)
- `deploy/README.md` (modified)
- `docs/superpowers/specs/2026-05-15-issue-34-quadlet-image-source-design.md` (created earlier)
- `docs/superpowers/plans/2026-05-15-issue-34-quadlet-image-source.md` (created earlier — this file)

- [ ] **Step 2: Sanity-check the fast suite still passes**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: green. No Python source changed.

- [ ] **Step 3: Final dry-run smoke tests**

```bash
make -n install 2>&1 | grep -E "sed |podman build" | head -3
```

Expected: one `sed` line with `localhost/driftnote:local`, one `podman build` line.

```bash
make -n install-registry 2>&1 | grep -E "sed |podman pull|podman tag" | head -3
```

Expected: one `sed` line with `ghcr.io/maciej-makowski/driftnote:prod`, one `podman pull` line, NO `podman tag` line.

### Task 4.2: Push + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin feat/issue-34-quadlet-image-source
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "deploy: quadlet reflects actual image source (#34)" --body "$(cat <<'EOF'
## Summary

Closes #34.

- `deploy/driftnote.container` becomes a template with `Image=__IMAGE__`. The Makefile substitutes the placeholder when installing — the on-disk quadlet always reflects the actual image source.
- Two install paths, both first-class:
  - `make install` (local build): quadlet `Image=localhost/driftnote:local`.
  - `make install-registry [TAG=prod]`: quadlet `Image=ghcr.io/maciej-makowski/driftnote:<TAG>`.
- `make pull-registry` drops the silent `podman tag` retag. It now does only `podman pull`.
- `make reinstall-registry` mirrors `make reinstall` for the registry path.
- `deploy/README.md` §4 rewritten to describe both paths up front, with explicit "switch" and "pin" flows. §7 split between local-build and registry-pull update paths.

## Day-to-day flows (post-merge)

| Goal | Command |
|---|---|
| First-time install, local build | `make install` |
| First-time install, registry pull | `make install-registry` |
| Update to fresh `:prod` (registry path) | `make pull-registry && make restart` |
| Switch local → registry | `make reinstall-registry` |
| Switch registry → local | `make reinstall` |
| Pin to a specific build | `make reinstall-registry TAG=sha-abc1234` |
| Return from pin to rolling `:prod` | `make reinstall-registry` |

## Migration impact

Zero. Existing RPi installs have `Image=localhost/driftnote:local` from the old quadlet; the new `make install` produces the exact same line. Running `make install` on an existing install is idempotent and produces the same result as before. The new `install-registry` path is opt-in.

## Verification

- [x] `make -n install` shows `sed` substituting `localhost/driftnote:local` into the quadlet
- [x] `make -n install-registry` shows `sed` substituting `ghcr.io/maciej-makowski/driftnote:prod`, no `podman tag`
- [x] `make -n install-registry TAG=sha-abc1234` substitutes the pinned tag
- [x] `make units` (bare) errors with the guard message
- [x] `make units IMAGE=...` works as standalone escape hatch
- [x] `make -n pull-registry` shows no `podman tag` line
- [x] Fast test suite green

## Spec + plan

- Spec: `docs/superpowers/specs/2026-05-15-issue-34-quadlet-image-source-design.md`
- Plan: `docs/superpowers/plans/2026-05-15-issue-34-quadlet-image-source.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** every acceptance criterion in the spec maps to a step here (template placeholder → Task 1.1; install/install-registry/reinstall-registry → Tasks 2.5-2.7; pull-registry no retag → Task 2.4; README rewrite → Tasks 3.1-3.2; help text → Task 2.2; .PHONY → Task 2.1).
- **No placeholders:** every step has either concrete code, concrete shell commands, or both.
- **Type/name consistency:** `IMAGE` is the variable name used in the guard, the substitution, and the target-specific assignments. `__IMAGE__` is the placeholder string in the quadlet file and the `sed` pattern. `LOCAL_IMAGE` and `REGISTRY_IMAGE` are pre-existing variables (see Makefile lines 22, 26). `install-registry` and `reinstall-registry` are the new target names; consistent across `.PHONY`, help, and all references.
