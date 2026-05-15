# Deploying Driftnote on a Raspberry Pi

End-to-end install: from a freshly-flashed RPi to a Cloudflare-Access-protected Driftnote serving at `https://driftnote.<your-domain>`.

## Prerequisites

Before you start, have the following ready:

- **Hardware:** any Raspberry Pi 4 or 5 (or an x86\_64 server) with ≥ 2 GB RAM.
- **OS:** Fedora IoT, Fedora Server, or Ubuntu Server 22.04+. Any Linux distro that ships `podman` ≥ 4.4 (with systemd quadlet support) and `systemd` ≥ 250 should work, but only the Fedora and Ubuntu paths below are tested.
- **Cloudflare account** with Zero Trust enabled and a domain managed by Cloudflare DNS. A free Cloudflare plan is sufficient.
- **Gmail account** with 2-Step Verification turned on (required to create an App Password). See the "Setting up Gmail" section in the top-level [README.md](../README.md) for filter + label setup.
- **Optional:** a cloud storage account (OneDrive, Backblaze B2, etc.) for off-host backups.

---

## 1. Cloudflare Tunnel setup

Cloudflare Tunnel (`cloudflared`) punches an outbound TLS connection from the RPi to Cloudflare's edge, so you don't need to open any inbound ports or expose a residential IP address.

```bash
# Fedora / Fedora IoT:
sudo dnf install -y cloudflared

# Ubuntu (if cloudflared isn't in your distro's repos):
# curl -L https://pkg.cloudflare.com/cloudflare-main.gpg \
#   | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
# echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
#   https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
#   | sudo tee /etc/apt/sources.list.d/cloudflared.list
# sudo apt update && sudo apt install -y cloudflared

cloudflared tunnel login          # opens a browser tab; authorise the right Cloudflare account
cloudflared tunnel create driftnote
# Prints: Tunnel credentials written to /root/.cloudflared/<tunnel-uuid>.json
# Note the UUID — you'll need it below.

cloudflared tunnel route dns driftnote driftnote.<your-domain>
```

Create `/etc/cloudflared/config.yml` (replace `<tunnel-uuid>` and `<your-domain>`):

```yaml
tunnel: <tunnel-uuid>
credentials-file: /root/.cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: driftnote.<your-domain>
    # Driftnote's quadlet maps the container's port 8000 to host 8001 by
    # default (so it doesn't collide with another tunneled app on 8000).
    # If you change it in deploy/driftnote.container, change it here too.
    service: http://127.0.0.1:8001
  - service: http_status:404
```

Install and start the tunnel as a system service:

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared   # should show active (running)
```

> **Note:** `cloudflared service install` copies the credentials file and config to `/etc/cloudflared/` and writes a systemd unit. If you already placed `config.yml` there, the service will pick it up.

---

## 2. Cloudflare Access application

Cloudflare Access gates the tunnel endpoint behind identity verification, so the URL isn't world-readable even though the tunnel is open.

In the **Cloudflare Zero Trust dashboard** (`one.dash.cloudflare.com` → your account → **Zero Trust**):

1. **Access → Applications → Add an application → Self-hosted.**
2. **Application name:** `Driftnote`
3. **Session Duration:** `24 hours` (adjust to taste — longer = fewer re-logins).
4. **Application domain:** `driftnote.<your-domain>`
5. Click **Next**, skip the policy step for now, and **Save**.
6. You land on the application's settings. Open the **Overview** tab and copy the **Application Audience (AUD) Tag** — it's a long hex string. You'll put this in `DRIFTNOTE_CF_ACCESS_AUD`.
7. Your **team domain** is visible in the sidebar URL: `https://<team>.cloudflareaccess.com`. Take just `<team>.cloudflareaccess.com` and note it for `DRIFTNOTE_CF_TEAM_DOMAIN`.
8. Open the **Policies** tab → **Add a policy:**
   - **Policy name:** `Owner`
   - **Action:** `Allow`
   - **Configure rules:** add an `Include` rule → **Emails** → `<your-email>@<your-domain>`
9. **Save the policy.** Until at least one policy is saved, Cloudflare blocks all access to the application.

---

## 3. RPi prep

> **Rootless install:** this guide runs Driftnote as your login user, not a dedicated service account. Data and secrets live under `~/.driftnote/`; systemd units are user-mode. If you ever want the system-mode rootful setup instead, substitute `~/.driftnote` → `/var/driftnote`, `~/.driftnote/driftnote.env` → `/etc/driftnote/driftnote.env`, install paths to `/etc/containers/systemd/` and `/etc/systemd/system/`, and prefix every `systemctl --user` with `sudo systemctl`.

Your RPi must have linger enabled for your user (so user-mode units survive logout). Check:

```bash
loginctl show-user $(whoami) | grep Linger=yes
```

If that line is missing, run `sudo loginctl enable-linger $(whoami)` once.

Clone the Driftnote repo on the RPi — you'll run the install from inside it (the Makefile in §4 expects to be invoked from the project root):

```bash
git clone https://github.com/maciej-makowski/driftnote.git
cd driftnote
```

The rest of this guide assumes your shell's working directory is that checkout.

```bash
# Data + backup directories under your home.
mkdir -p ~/.driftnote/data ~/.driftnote/backups

# Drop the example config in (you'll edit it next).
cp config/config.example.toml ~/.driftnote/config.toml
chmod 0644 ~/.driftnote/config.toml
$EDITOR ~/.driftnote/config.toml
```

Set at minimum:

- `[email].recipient = "<you>+driftnote@gmail.com"`
- `[email].reply_to = "<you>+driftnote@gmail.com"`
- `[schedule].timezone` — e.g. `"Europe/London"`

Create `~/.driftnote/driftnote.env` with the secrets (mode 0600, your user-owned):

```bash
install -m 0600 /dev/stdin ~/.driftnote/driftnote.env <<'EOF'
DRIFTNOTE_GMAIL_USER=<you>@gmail.com
DRIFTNOTE_GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
DRIFTNOTE_CF_ACCESS_AUD=<the-long-hex-aud-tag>
DRIFTNOTE_CF_TEAM_DOMAIN=<your-team>.cloudflareaccess.com
DRIFTNOTE_WEB_BASE_URL=https://driftnote.<your-domain>
DRIFTNOTE_ENVIRONMENT=prod
EOF
```

> **Gmail App Password:** Google's UI displays the 16-character password with spaces (e.g. `abcd efgh ijkl mnop`). Strip the spaces — it's a single 16-character string: `abcdefghijklmnop`.

---

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

---

## 5. Post-deploy verification

**From a workstation** (not the RPi), verify the tunnel + Access chain is working:

```bash
# The first request will redirect to Cloudflare's identity provider; authenticate there.
# On success, Cloudflare issues a JWT cookie and forwards the request.
curl -sf https://driftnote.<your-domain>/healthz
# Expected: {"status":"ok","db":"ok",...}
```

If `curl` returns a Cloudflare login redirect, open the URL in a browser first to complete authentication, then retry the `curl` from the same machine.

**From the RPi**, test the full email path:

```bash
# Send a manual journal prompt.
podman exec systemd-driftnote driftnote send-prompt
# Confirm the prompt lands in your Driftnote/Inbox Gmail label within a minute or two.
```

Reply to the prompt from your phone or Gmail web, then:

```bash
# Force an immediate IMAP poll (don't wait for the scheduled cron).
podman exec systemd-driftnote driftnote poll-responses
```

Open `https://driftnote.<your-domain>/` in your browser — the calendar should show today's date with your reply attached.

---

## 6. Backups + cloud copy

The local backup timer drops a `tar.zst` snapshot in `~/.driftnote/backups/` on the 1st of each month at 03:00. Local retention defaults to 12 months. For off-host copies, pick one of the options below.

### Option A: rclone systemd timer on the RPi (preferred)

```bash
# Fedora:
sudo dnf install -y rclone
# Ubuntu:
# sudo apt install -y rclone

# Configure a remote (OneDrive, Backblaze B2, S3, etc.):
rclone config
# Walk through the interactive wizard; note the remote name you choose (e.g. "onedrive").
```

Create `~/.config/systemd/user/driftnote-cloud-sync.service`:

```ini
[Unit]
Description=Sync Driftnote backups to cloud
After=driftnote-backup.service

[Service]
Type=oneshot
ExecStart=/usr/bin/rclone sync %h/.driftnote/backups onedrive:driftnote-backups
```

Create `~/.config/systemd/user/driftnote-cloud-sync.timer`:

```ini
[Unit]
Description=Run Driftnote cloud sync after each monthly backup

[Timer]
OnCalendar=*-*-01 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable the timer:

```bash
systemctl --user daemon-reload
systemctl --user enable --now driftnote-cloud-sync.timer
```

### Option B: Manual rclone/scp from a workstation

Keeps credentials entirely off the RPi if you prefer.

```bash
rclone sync user@rpi:driftnote/backups onedrive:driftnote-backups
```

Schedule this via your workstation's cron or Task Scheduler, or run it manually after each monthly backup.

---

## 7. Update path

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

---

## 8. Rotating credentials

- **Gmail App Password compromised:** Google Account → Security → App passwords → revoke the Driftnote entry → generate a new one → update `DRIFTNOTE_GMAIL_APP_PASSWORD` in `~/.driftnote/driftnote.env` → `systemctl --user restart driftnote.service`.
- **Cloudflare AUD compromised:** Zero Trust dashboard → Access → Applications → Driftnote → ⋯ (three-dot menu) → **Refresh Application Audience (AUD)**. Copy the new value into `driftnote.env` → restart the service. Old JWTs are rejected immediately by Cloudflare once the AUD changes.

---

## Troubleshooting

| Symptom | First check |
|---|---|
| `curl https://driftnote.<your-domain>/healthz` redirects to Cloudflare login | Expected — Access is working. Authenticate in a browser first; the cookie allows subsequent `curl` calls from the same machine. |
| 403 from `/healthz` after login | AUD or team-domain mismatch in `driftnote.env`. Compare `DRIFTNOTE_CF_ACCESS_AUD` and `DRIFTNOTE_CF_TEAM_DOMAIN` against the values on the Access Application Overview tab. |
| `systemctl --user status driftnote.service` shows the container exiting immediately | `journalctl --user -u driftnote.service`, or — if user-mode journald isn't persistent — re-run the container manually to see the traceback: `podman run --rm --pull=never -v ~/.driftnote:/var/driftnote:Z -e DRIFTNOTE_CONFIG=/var/driftnote/config.toml -e DRIFTNOTE_DATA_ROOT=/var/driftnote/data --env-file ~/.driftnote/driftnote.env -p 127.0.0.1:8001:8000 localhost/driftnote:local`. Usual suspects: missing or mis-typed env vars (config validation fails fast on startup), or the bind mount is unreadable from inside the container (see next row). |
| `PermissionError: [Errno 13] Permission denied: '/var/driftnote/config.toml'` (or similar EACCES from inside the container) | Rootless podman maps your host UID 1000 to container UID 0 by default, while the image runs as a `driftnote` user with container UID 1000 (which lands in the subuid range and isn't your file's owner or group). The shipped quadlet sets `UserNS=keep-id` to map host UID 1000 ↔ container UID 1000 1:1; if you've edited the quadlet and dropped that line, restore it. |
| Daily prompt doesn't arrive | Run `podman exec systemd-driftnote driftnote send-prompt` to test the SMTP path. If that works, the scheduler is the issue — check `/admin` (after authenticating through Access) for `daily_prompt` job history. |
| Reply doesn't appear in the calendar after `poll-responses` | The Gmail filter may be marking the reply as read on arrival, which causes `SEARCH UNSEEN` to skip it. See the "Setting up Gmail" section in the top-level [README.md](../README.md). |
| Backup timer never fires | `systemctl --user list-timers driftnote-backup.timer` — `Persistent=true` means it fires on the next boot if it missed the scheduled window. |
| `cloudflared` exits with "failed to get the tunnel credentials" | The credentials JSON path in `config.yml` is wrong or the file is missing. Run `cloudflared tunnel list` to confirm the tunnel exists and check `/root/.cloudflared/` or `/etc/cloudflared/` for the JSON file. |
| `journalctl --user -u driftnote.service` returns "No journal files were found" | journald's default `Storage=auto` only writes to `/var/log/journal/` if that directory exists; on Debian/Raspberry Pi OS it doesn't, so logs go to volatile `/run/log/journal/` and the per-user journal file is never created. One-time fix: `sudo mkdir -p /var/log/journal && sudo systemd-tmpfiles --create --prefix=/var/log/journal && sudo systemctl kill --kill-who=main --signal=SIGUSR1 systemd-journald`. Or read the system journal directly without persistent setup: `sudo journalctl _UID=$(id -u) --user-unit driftnote.service`. |

---

## Quick rollback

```bash
systemctl --user stop driftnote.service                       # quadlet-generated; not enabled
systemctl --user disable --now driftnote-backup.timer         # regular unit; was enabled
rm -f ~/.config/containers/systemd/driftnote.container
rm -f ~/.config/systemd/user/driftnote-backup*.{service,timer}
rm -rf ~/.local/lib/driftnote ~/.driftnote
systemctl --user daemon-reload
# Cloudflare Tunnel stays rootful; remove with:
sudo systemctl disable --now cloudflared
sudo rm -rf /etc/cloudflared
```

Cloudflare Tunnel + Access are stateless on the dashboard side; delete the tunnel + application via the Zero Trust dashboard if you want a fully clean slate.
