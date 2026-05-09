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
REGISTRY_IMAGE := ghcr.io/maciej-makowski/driftnote:latest

.DEFAULT_GOAL := help
.PHONY: help install uninstall reinstall \
        check-prereqs scripts units build pull-registry \
        start stop restart status logs

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
	@echo "  pull-registry  Alternative to build: pull from GHCR + retag. Requires GHCR auth."

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

units:
	@install -d "$(QUADLET_DIR)" "$(USER_UNIT_DIR)"
	@install -m 0644 deploy/driftnote.container          "$(QUADLET_DIR)/"
	@install -m 0644 deploy/driftnote-backup.service     "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup-failure.service "$(USER_UNIT_DIR)/"
	@install -m 0644 deploy/driftnote-backup.timer       "$(USER_UNIT_DIR)/"
	@systemctl --user daemon-reload
	@echo "✓ units installed; systemd reloaded"

build:
	@podman build -f Containerfile -t "$(LOCAL_IMAGE)" .
	@echo "✓ image built locally as $(LOCAL_IMAGE)"

# Alternative to `build`: pull a prebuilt image from GHCR. Requires the
# package to be public, OR `podman login ghcr.io` on this host. Most
# personal installs are better off with `build`; this target is here for
# anyone who explicitly prefers the registry path.
pull-registry:
	@podman pull "$(REGISTRY_IMAGE)"
	@podman tag "$(REGISTRY_IMAGE)" "$(LOCAL_IMAGE)"
	@echo "✓ pulled $(REGISTRY_IMAGE) and tagged as $(LOCAL_IMAGE)"

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

install: check-prereqs scripts units build start
	@echo ""
	@echo "Driftnote installed. Verify with:"
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
