# Quadlet reflects actual image source

> Design spec for [issue #34](https://github.com/maciej-makowski/driftnote/issues/34).

## Goal

Make the installed `~/.config/containers/systemd/driftnote.container` quadlet reflect the actual image source. Today the file always says `Image=localhost/driftnote:local` regardless of how the image got there, and `make pull-registry` retags GHCR pulls under that local name. The retag is opaque — looking at the quadlet on the RPi tells you nothing about provenance. After this change the quadlet says exactly where the image came from, and switching paths is a deliberate reinstall.

## Architecture

`deploy/driftnote.container` becomes a **template** with `Image=__IMAGE__` as a placeholder. The Makefile's `units` target substitutes the placeholder when copying to `~/.config/containers/systemd/`. The substitution value is set by the calling target (`install` → local image; `install-registry` → registry image).

Two install paths are first-class. Both end with a quadlet whose `Image=` line is honest about what's running.

## Quadlet template

`deploy/driftnote.container` — only the `Image=` line changes vs current; comment block above it rewritten:

```
[Container]
# Image= is filled in by the Makefile when the quadlet is installed.
# `make install` substitutes `localhost/driftnote:local` (local build).
# `make install-registry [TAG=...]` substitutes `ghcr.io/maciej-makowski/driftnote:<TAG>`.
# The repo file's __IMAGE__ placeholder is invalid for direct copy — use the Makefile.
Image=__IMAGE__
```

Rest of the file unchanged.

## Makefile changes

### Variables

```makefile
LOCAL_IMAGE    := localhost/driftnote:local
TAG            ?= prod
REGISTRY_IMAGE := ghcr.io/maciej-makowski/driftnote:$(TAG)
```

(`TAG ?= prod` already exists from #18; `LOCAL_IMAGE` already exists.)

### `units` target — parameterised substitution

```makefile
# IMAGE must be set by the calling target (install / install-registry / reinstall*).
units:
	@test -n "$(IMAGE)" || { echo "ERROR: IMAGE must be set. Use 'make install' or 'make install-registry'."; exit 1; }
	@install -d "$(QUADLET_DIR)" "$(USER_UNIT_DIR)"
	@sed 's|__IMAGE__|$(IMAGE)|' deploy/driftnote.container > "$(QUADLET_DIR)/driftnote.container"
	@chmod 0644 "$(QUADLET_DIR)/driftnote.container"
	@install -m 0644 deploy/driftnote-backup.service         "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup-failure.service "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup.timer           "$(USER_UNIT_DIR)/"
	@systemctl --user daemon-reload
	@echo "✓ units installed (Image=$(IMAGE)); systemd reloaded"
```

The `IMAGE` guard prevents accidental direct `make units` invocations (which would copy a template with `__IMAGE__` literal — broken quadlet). Calling targets always set it.

### `build` and `pull-registry` — back to single-purpose primitives

```makefile
build:
	@podman build -f Containerfile -t "$(LOCAL_IMAGE)" .
	@echo "✓ image built locally as $(LOCAL_IMAGE)"

# Pull from GHCR. The package is public — no `podman login` required.
# Defaults to `:prod`; pin via `make pull-registry TAG=sha-abc1234`.
# No retag — the quadlet references the registry image directly when installed
# via `make install-registry`.
pull-registry:
	@podman pull "$(REGISTRY_IMAGE)"
	@echo "✓ pulled $(REGISTRY_IMAGE)"
```

The `podman tag ...` line that previously aliased the registry image as `localhost/driftnote:local` is removed.

### Install targets — local and registry paths

```makefile
install: IMAGE := $(LOCAL_IMAGE)
install: check-prereqs scripts build units start
	@echo ""
	@echo "Driftnote installed (local build). Verify with:"
	@echo "    make status"

install-registry: IMAGE := $(REGISTRY_IMAGE)
install-registry: check-prereqs scripts pull-registry units start
	@echo ""
	@echo "Driftnote installed (registry pull, $(REGISTRY_IMAGE)). Verify with:"
	@echo "    make status"

reinstall: uninstall install
reinstall-registry: uninstall install-registry
```

Note the prerequisite order for `install`: `build` moved BEFORE `units`. The quadlet has `WantedBy=default.target` so `systemctl --user start` later starts a service that references an image — the image must exist at start time. (The previous order was `units build start`, which worked because the user's first `systemctl start` happened after `build`. The new order is the same in effect but more obviously correct.)

For `install-registry`: `pull-registry` before `units` for the same reason.

### Help text

```
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

### `.PHONY` additions

Add `install-registry reinstall-registry` to the existing `.PHONY` line.

## Day-to-day flows

| Goal | Command |
|---|---|
| First-time install, local build | `make install` |
| First-time install, registry pull | `make install-registry` |
| Update to fresh `:prod` (registry path) | `make pull-registry && make restart` |
| Update local-build path | `make build && make restart` |
| Switch local → registry | `make reinstall-registry` |
| Switch registry → local | `make reinstall` |
| Pin to a specific build | `make reinstall-registry TAG=sha-abc1234` |
| Return from pin to rolling `:prod` | `make reinstall-registry` |

Rolling-forward on the registry path (`pull-registry && restart`) works because the quadlet references `ghcr.io/.../driftnote:prod` and podman pulls the new image content under the same tag. No quadlet rewrite needed for a rolling update. **Pinning to a different tag DOES require reinstall** because the quadlet's `Image=` line changes.

## `deploy/README.md`

Rewrite §4 ("Install") to describe both paths up front. Add explicit "switching paths" and "pinning" subsections referencing the new targets. Drop any remaining language that implies retag-under-localhost. The §8 rollback bullet ("Or, if you're on the GHCR-pull path: …") gets updated to reflect that rollback on the registry path is `make reinstall-registry TAG=sha-...` rather than the old `pull-registry && restart` pattern.

## Files touched

| File | Change |
|---|---|
| `deploy/driftnote.container` | `Image=` becomes `__IMAGE__` placeholder; comment rewritten |
| `Makefile` | `units` substitutes placeholder; `pull-registry` drops retag; new `install-registry` / `reinstall-registry` targets; `install` reorders prereqs (`build` before `units`); help rewritten |
| `deploy/README.md` | Rewrite §4 install paths; update §8 rollback hint |
| `docs/superpowers/specs/2026-05-15-issue-34-quadlet-image-source-design.md` | This spec |

No Python source touched. No new tests. The Makefile changes are validated by `make -n <target>` smoke checks.

## Verification

- `make -n install` shows the quadlet substitution running with `IMAGE=localhost/driftnote:local`.
- `make -n install-registry` shows the substitution with `IMAGE=ghcr.io/maciej-makowski/driftnote:prod`.
- `make -n install-registry TAG=sha-abc1234` shows the substitution with `IMAGE=ghcr.io/maciej-makowski/driftnote:sha-abc1234`.
- `make units` without an `IMAGE=` set exits with the guard error.
- `make pull-registry` shows only `podman pull` — no `podman tag` line in the output.
- The repo file `deploy/driftnote.container` contains `__IMAGE__` (no installable `Image=` line).
- After `make install` (on a test host or via dry-run inspection), the installed `~/.config/containers/systemd/driftnote.container` contains `Image=localhost/driftnote:local`.
- After `make install-registry`, the installed file contains `Image=ghcr.io/maciej-makowski/driftnote:prod`.

## Acceptance criteria

- [ ] `deploy/driftnote.container` repo file has `Image=__IMAGE__`; not directly installable.
- [ ] `make install` produces quadlet with `Image=localhost/driftnote:local`.
- [ ] `make install-registry` (default TAG) produces quadlet with `Image=ghcr.io/maciej-makowski/driftnote:prod`.
- [ ] `make install-registry TAG=sha-abc1234` produces quadlet with `Image=ghcr.io/maciej-makowski/driftnote:sha-abc1234`.
- [ ] `make pull-registry` does NOT run `podman tag`.
- [ ] `make units` without `IMAGE=` exits 1 with a clear error.
- [ ] `make reinstall-registry [TAG=...]` exists and runs uninstall → install-registry.
- [ ] `deploy/README.md` documents both paths, switch flow, pin flow.

## Risks

**Risk:** The `IMAGE` guard on `units` makes the target less standalone — someone running `make units` after editing a `deploy/*.service` file gets an error instead of a refresh.
**Mitigation:** They can run `make reinstall` / `make reinstall-registry`, which include `units` and supply IMAGE. Or invoke `make units IMAGE=localhost/driftnote:local` directly. Documented in help text.

**Risk:** Existing RPi installs have the OLD-style quadlet (`Image=localhost/driftnote:local`) installed. After this PR merges and they `git pull && make install`, the new install path produces the SAME `Image=localhost/driftnote:local` for them — no breakage. If they want the registry path, they run `make reinstall-registry`.
**Mitigation:** Zero migration burden. The existing install keeps working.

**Risk:** `sed 's|__IMAGE__|$(IMAGE)|'` with `IMAGE` containing `|` or special regex chars would break.
**Mitigation:** Image references can contain `/`, `:`, `-`, `.`, `_` — none are special to `sed`'s `|` delimiter. The `:` in registry refs and the `/` in path components are safe with `|`. Even `make install-registry TAG=something:weird` is bounded by what GHCR accepts as a tag name (alphanumeric, `_`, `-`, `.`).

## Out of scope

- Auto-detecting "clean RPi" vs "dev machine" and choosing the path automatically.
- Environment-variable substitution at quadlet generator time (not supported by quadlet).
- Multiple-host installs from a single Makefile invocation.
- Image cosign / signing verification before install.
