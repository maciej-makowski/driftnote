# Driftnote rootless install helper.
#
# Prerequisite: ~/.driftnote/config.toml and ~/.driftnote/driftnote.env are
# already in place (see deploy/README.md §3). Linger must be enabled for
# the user (sudo loginctl enable-linger $(whoami)).
#
# Quick start (after the prerequisite is satisfied):
#     make install
#
# Re-run individual targets if you only need to refresh one piece:
#     make units            # re-copy quadlet + backup units, daemon-reload
#     make pull && make restart  # pull a new image and bounce the service
#
# Use `make help` to list every target.

SHELL          := /bin/bash
USER_NAME      := $(shell whoami)
DATA_DIR       := $(HOME)/.driftnote
SCRIPTS_DIR    := $(HOME)/.local/lib/driftnote/scripts
QUADLET_DIR    := $(HOME)/.config/containers/systemd
USER_UNIT_DIR  := $(HOME)/.config/systemd/user
LOCAL_IMAGE    := localhost/driftnote:local
# Default to the rolling `:prod` tag; override with `make pull-registry TAG=sha-abc1234`
# to pin to a specific build. The TAG= override accepts any GHCR tag verbatim.
TAG            ?= prod
REGISTRY_IMAGE := ghcr.io/maciej-makowski/driftnote:$(TAG)

.DEFAULT_GOAL := help
.PHONY: help install install-registry uninstall reinstall reinstall-registry \
        check-prereqs scripts units build pull-registry \
        start stop restart status logs

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

check-prereqs:
	@test -f "$(DATA_DIR)/config.toml" \
	    || { echo "ERROR: $(DATA_DIR)/config.toml is missing. See deploy/README.md §3."; exit 1; }
	@test -f "$(DATA_DIR)/driftnote.env" \
	    || { echo "ERROR: $(DATA_DIR)/driftnote.env is missing. See deploy/README.md §3."; exit 1; }
	@perms=$$(stat -c '%a' "$(DATA_DIR)/driftnote.env"); \
	    test "$$perms" = "600" \
	    || { echo "ERROR: $(DATA_DIR)/driftnote.env permissions are $$perms, expected 600. Run: chmod 0600 $(DATA_DIR)/driftnote.env"; exit 1; }
	@loginctl show-user "$(USER_NAME)" 2>/dev/null | grep -q "^Linger=yes" \
	    || { echo "ERROR: linger is not enabled for $(USER_NAME). Run: sudo loginctl enable-linger $(USER_NAME)"; exit 1; }
	@mkdir -p "$(DATA_DIR)/data" "$(DATA_DIR)/backups"
	@echo "✓ prerequisites ok"

scripts:
	@install -d "$(SCRIPTS_DIR)"
	@install -m 0755 scripts/backup.sh scripts/alert-email.py "$(SCRIPTS_DIR)/"
	@echo "✓ scripts installed at $(SCRIPTS_DIR)"

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

start:
	@# driftnote.service is generated from the quadlet by podman's quadlet
	@# generator; `systemctl enable` on generated units fails ("transient or
	@# generated"). The quadlet's [Install] WantedBy=default.target already
	@# creates the wants symlink at generation time, so the service autostarts
	@# on boot/login without `enable`. We just `start` it now.
	@systemctl --user start driftnote.service
	@# The backup timer is a regular (non-generated) unit — it does need enable.
	@systemctl --user enable --now driftnote-backup.timer
	@echo "✓ driftnote.service started; driftnote-backup.timer enabled and started"

stop:
	@-systemctl --user stop driftnote.service 2>/dev/null
	@-systemctl --user disable --now driftnote-backup.timer 2>/dev/null
	@echo "✓ services stopped"

restart:
	@systemctl --user restart driftnote.service
	@echo "✓ driftnote.service restarted"

status:
	@-systemctl --user status driftnote.service driftnote-backup.timer

logs:
	@journalctl --user -u driftnote.service -n 50 -f

install: IMAGE := $(LOCAL_IMAGE)
install: check-prereqs scripts build units start
	@echo ""
	@echo "Driftnote installed (local build, Image=$(LOCAL_IMAGE)). Verify with:"
	@echo "    make status"
	@echo "    curl -sf https://driftnote.<your-domain>/healthz   # via Cloudflare Access"

install-registry: IMAGE := $(REGISTRY_IMAGE)
install-registry: check-prereqs scripts pull-registry units start
	@echo ""
	@echo "Driftnote installed (registry pull, Image=$(REGISTRY_IMAGE)). Verify with:"
	@echo "    make status"
	@echo "    curl -sf https://driftnote.<your-domain>/healthz   # via Cloudflare Access"

uninstall: stop
	@rm -f "$(QUADLET_DIR)/driftnote.container"
	@rm -f "$(USER_UNIT_DIR)/driftnote-backup.service"
	@rm -f "$(USER_UNIT_DIR)/driftnote-backup-failure.service"
	@rm -f "$(USER_UNIT_DIR)/driftnote-backup.timer"
	@rm -rf "$(SCRIPTS_DIR)"
	@systemctl --user daemon-reload
	@echo "✓ uninstalled. $(DATA_DIR)/ KEPT — remove manually with: rm -rf $(DATA_DIR)"

reinstall: uninstall install
reinstall-registry: uninstall install-registry
