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
    service: http://127.0.0.1:8000
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

Create a dedicated service account, the data directories, and the secrets directory:

```bash
# Service account — no login shell, home in /var/driftnote
sudo useradd -r -m -d /var/driftnote -s /sbin/nologin driftnote

# Data + backup directories, owned by the service account
sudo install -d -o driftnote -g driftnote /var/driftnote/data /var/driftnote/backups

# Secrets directory — root-owned, not readable by the service account
sudo install -d -m 0700 -o root -g root /etc/driftnote
```

Download the example config and edit it:

```bash
sudo curl -fsSL \
  https://raw.githubusercontent.com/maciej-makowski/driftnote/master/config/config.example.toml \
  -o /var/driftnote/config.toml
sudo chown driftnote:driftnote /var/driftnote/config.toml
sudo chmod 0644 /var/driftnote/config.toml
sudo $EDITOR /var/driftnote/config.toml
```

Set at minimum:

- `[email].recipient = "<you>+driftnote@gmail.com"`
- `[email].reply_to = "<you>+driftnote@gmail.com"`
- `[schedule].timezone` — e.g. `"Europe/London"`

Create `/etc/driftnote/driftnote.env` with the secrets (root-owned, mode 0600):

```bash
sudo install -m 0600 -o root -g root /dev/stdin /etc/driftnote/driftnote.env <<'EOF'
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

## 4. Install scripts + systemd units

Clone the repository to a temporary location and install the artefacts:

```bash
git clone https://github.com/maciej-makowski/driftnote.git /tmp/driftnote-source

sudo install -d /usr/local/lib/driftnote/scripts
sudo install -m 0755 \
  /tmp/driftnote-source/scripts/backup.sh \
  /tmp/driftnote-source/scripts/alert-email.py \
  /usr/local/lib/driftnote/scripts/

sudo install -m 0644 \
  /tmp/driftnote-source/deploy/driftnote.container \
  /etc/containers/systemd/

sudo install -m 0644 \
  /tmp/driftnote-source/deploy/driftnote-backup.service \
  /tmp/driftnote-source/deploy/driftnote-backup-failure.service \
  /tmp/driftnote-source/deploy/driftnote-backup.timer \
  /etc/systemd/system/

rm -rf /tmp/driftnote-source
```

---

## 5. Pull the image + start

```bash
sudo podman pull ghcr.io/maciej-makowski/driftnote:latest
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote.container driftnote-backup.timer
```

`daemon-reload` translates the quadlet source file (`driftnote.container`) into a real `.service` unit. After that, the running unit is named `driftnote.service`:

```bash
sudo systemctl status driftnote.service    # should show active (running)
sudo journalctl -u driftnote.service -f    # tail logs; Ctrl-C when you see "Uvicorn running"
```

---

## 6. Post-deploy verification

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
# 2. Send a manual journal prompt.
sudo podman exec systemd-driftnote driftnote send-prompt
# Confirm the prompt lands in your Driftnote/Inbox Gmail label within a minute or two.
```

Reply to the prompt from your phone or Gmail web, then:

```bash
# 3. Force an immediate IMAP poll (don't wait for the scheduled cron).
sudo podman exec systemd-driftnote driftnote poll-responses
```

Open `https://driftnote.<your-domain>/` in your browser — the calendar should show today's date with your reply attached.

---

## 7. Backups + cloud copy

The local backup timer drops a `tar.zst` snapshot in `/var/driftnote/backups/` on the 1st of each month at 03:00. Local retention defaults to 12 months. For off-host copies, pick one of the options below.

### Option A: rclone systemd timer on the RPi (preferred)

```bash
# Fedora:
sudo dnf install -y rclone
# Ubuntu:
# sudo apt install -y rclone

# Configure a remote (OneDrive, Backblaze B2, S3, etc.) as the driftnote user:
sudo -u driftnote rclone config
# Walk through the interactive wizard; note the remote name you choose (e.g. "onedrive").
```

Create `/etc/systemd/system/driftnote-cloud-sync.service`:

```ini
[Unit]
Description=Sync Driftnote backups to cloud
After=driftnote-backup.service

[Service]
Type=oneshot
User=driftnote
ExecStart=/usr/bin/rclone sync /var/driftnote/backups onedrive:driftnote-backups
```

Create `/etc/systemd/system/driftnote-cloud-sync.timer`:

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
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote-cloud-sync.timer
```

### Option B: Manual rclone/scp from a workstation

Keeps credentials entirely off the RPi if you prefer.

```bash
rclone sync user@rpi:/var/driftnote/backups onedrive:driftnote-backups
```

Schedule this via your workstation's cron or Task Scheduler, or run it manually after each monthly backup.

---

## 8. Update path

When a new image is published:

```bash
sudo podman pull ghcr.io/maciej-makowski/driftnote:latest
sudo systemctl restart driftnote.service
sudo journalctl -u driftnote.service -n 50   # confirm it came back up cleanly
```

If a future release introduces a database schema change, the release notes will include migration instructions. There is no automated migration tooling.

---

## 9. Rotating credentials

- **Gmail App Password compromised:** Google Account → Security → App passwords → revoke the Driftnote entry → generate a new one → update `DRIFTNOTE_GMAIL_APP_PASSWORD` in `/etc/driftnote/driftnote.env` → `sudo systemctl restart driftnote.service`.
- **Cloudflare AUD compromised:** Zero Trust dashboard → Access → Applications → Driftnote → ⋯ (three-dot menu) → **Refresh Application Audience (AUD)**. Copy the new value into `driftnote.env` → restart the service. Old JWTs are rejected immediately by Cloudflare once the AUD changes.

---

## Troubleshooting

| Symptom | First check |
|---|---|
| `curl https://driftnote.<your-domain>/healthz` redirects to Cloudflare login | Expected — Access is working. Authenticate in a browser first; the cookie allows subsequent `curl` calls from the same machine. |
| 403 from `/healthz` after login | AUD or team-domain mismatch in `driftnote.env`. Compare `DRIFTNOTE_CF_ACCESS_AUD` and `DRIFTNOTE_CF_TEAM_DOMAIN` against the values on the Access Application Overview tab. |
| `systemctl status driftnote.service` shows the container exiting immediately | `journalctl -u driftnote.service` — usual suspects: missing or mis-typed env vars (config validation fails fast on startup), or `/var/driftnote/data` has wrong ownership. |
| Daily prompt doesn't arrive | Run `sudo podman exec systemd-driftnote driftnote send-prompt` to test the SMTP path. If that works, the scheduler is the issue — check `/admin` (after authenticating through Access) for `daily_prompt` job history. |
| Reply doesn't appear in the calendar after `poll-responses` | The Gmail filter may be marking the reply as read on arrival, which causes `SEARCH UNSEEN` to skip it. See the "Setting up Gmail" section in the top-level [README.md](../README.md). |
| Backup timer never fires | `systemctl list-timers driftnote-backup.timer` — `Persistent=true` means it fires on the next boot if it missed the scheduled window. |
| `cloudflared` exits with "failed to get the tunnel credentials" | The credentials JSON path in `config.yml` is wrong or the file is missing. Run `cloudflared tunnel list` to confirm the tunnel exists and check `/root/.cloudflared/` or `/etc/cloudflared/` for the JSON file. |
