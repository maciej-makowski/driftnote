# Issue #5 — End-to-end Raspberry Pi deployment guide

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single guided walkthrough that takes a fresh RPi → fully-deployed Driftnote behind Cloudflare Tunnel + Access. Covers prerequisites, tunnel setup, Access application, RPi prep, container deploy, post-install verification, backup-to-cloud, and update path.

**Architecture:** Pure docs change. Replaces / extends `deploy/README.md` with the full setup. Adds a `Makefile`-style summary of one-line commands. Cross-links from top-level `README.md`.

**Tech Stack:** Markdown + bash command examples. No Python, no tests.

**Issue:** https://github.com/maciej-makowski/driftnote/issues/5

---

## Chunk 1: Rewrite `deploy/README.md` to cover the full deploy

### Task 1: Read what's there now and replace

**Files:**
- Modify: `deploy/README.md` (full rewrite — keep nothing, the existing one assumes Cloudflare is already configured)
- Modify: `README.md` (add a one-line cross-reference if not already there)

- [ ] **Step 1: Read current `deploy/README.md`** so you know what's being replaced.

- [ ] **Step 2: Replace `deploy/README.md` entirely with the structure below**

Use the section outline verbatim. The exact prose is yours to write but follow these constraints:
- Each major section has a one-paragraph framing followed by a code block with the actual commands
- Commands are copy-pasteable — no placeholders that aren't called out as `<placeholder>`
- Where the user must look something up in a Cloudflare dashboard, describe the menu path explicitly (e.g. `Zero Trust → Access → Applications → Add an application → Self-hosted`)
- Don't invent commands you can't verify — if you're not sure about a flag, use the documented form from the linked tool's docs and link to it

**Section outline:**

```markdown
# Deploying Driftnote on a Raspberry Pi

End-to-end install: from a freshly-flashed RPi to a Cloudflare-Access-protected Driftnote serving at `https://driftnote.<your-domain>`.

## Prerequisites

(One paragraph + bullet list)
- Hardware: any RPi 4/5 (or x86_64 server) with ≥2 GB RAM
- OS: Fedora IoT, Fedora Server, or Ubuntu Server 22.04+. Anything else with podman + systemd-quadlet support works but isn't tested.
- A Cloudflare account with Zero Trust enabled and a domain managed by Cloudflare DNS
- A Gmail account with 2-step verification on (the App Password requires it)
- Optional: a cloud storage account (OneDrive, Backblaze B2, etc.) for off-host backups

## 1. Cloudflare Tunnel setup

(Why: punches a TLS tunnel from the RPi to Cloudflare so we don't expose port 443 on a residential IP)

```bash
# Fedora:
sudo dnf install -y cloudflared
# Ubuntu:
# curl -L https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
# echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
# sudo apt update && sudo apt install -y cloudflared

cloudflared tunnel login         # opens browser, authorize the right account
cloudflared tunnel create driftnote
# → prints the tunnel UUID and the credentials file path; note both.

cloudflared tunnel route dns driftnote driftnote.<your-domain>
```

Create `/etc/cloudflared/config.yml`:
```yaml
tunnel: <tunnel-uuid>
credentials-file: /etc/cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: driftnote.<your-domain>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared    # should be active (running)
```

## 2. Cloudflare Access application

(Why: gates the tunnel endpoint behind authentication so the URL isn't world-readable)

In the Cloudflare Zero Trust dashboard:

1. Access → Applications → **Add an application** → **Self-hosted**
2. Application name: `Driftnote`
3. Session Duration: `24 hours` (your call — longer = fewer logins, shorter = tighter)
4. Application domain: `driftnote.<your-domain>`
5. Save. You'll land on the application's settings.
6. Click **Overview** tab → copy the **Application Audience (AUD) Tag** (long hex string). You'll need this for `DRIFTNOTE_CF_ACCESS_AUD`.
7. Note your **team domain** from the URL (`https://<team>.cloudflareaccess.com`). Take just `<team>.cloudflareaccess.com`. You'll need this for `DRIFTNOTE_CF_TEAM_DOMAIN`.
8. Click **Policies** tab → **Add a policy**:
   - Policy name: `Owner`
   - Action: `Allow`
   - Configure rules: `Emails` `is` `<your-email>@<your-domain>`
9. Save. Until a policy is in place, Cloudflare blocks all access.

## 3. RPi prep

```bash
# Create the service account.
sudo useradd -r -m -s /sbin/nologin driftnote

# Data + backup directories owned by that account.
sudo install -d -o driftnote -g driftnote /var/driftnote/data /var/driftnote/backups

# Secrets directory — root-owned, mode 0700.
sudo install -d -m 0700 -o root -g root /etc/driftnote
```

Create `/var/driftnote/config.toml` from the example:
```bash
sudo curl -L https://raw.githubusercontent.com/maciej-makowski/driftnote/master/config/config.example.toml \
    -o /var/driftnote/config.toml
sudo chown driftnote:driftnote /var/driftnote/config.toml
sudo chmod 0644 /var/driftnote/config.toml
sudo $EDITOR /var/driftnote/config.toml
```

Set at minimum:
- `[email].recipient = "<you>+driftnote@gmail.com"`
- `[email].reply_to = "<you>+driftnote@gmail.com"`
- `[schedule].timezone` (e.g. `"Europe/London"`)

Create `/etc/driftnote/driftnote.env` (root-owned, mode 0600):
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

(Strip spaces from the App Password — Google's UI shows it with spaces but it's a single 16-char string.)

## 4. Install scripts + systemd units

```bash
# Pull the project's deploy artefacts.
git clone https://github.com/maciej-makowski/driftnote.git /tmp/driftnote-source

sudo install -d /usr/local/lib/driftnote/scripts
sudo install -m 0755 /tmp/driftnote-source/scripts/backup.sh \
                     /tmp/driftnote-source/scripts/alert-email.py \
                     /usr/local/lib/driftnote/scripts/

sudo install -m 0644 /tmp/driftnote-source/deploy/driftnote.container          /etc/containers/systemd/
sudo install -m 0644 /tmp/driftnote-source/deploy/driftnote-backup.service     /etc/systemd/system/
sudo install -m 0644 /tmp/driftnote-source/deploy/driftnote-backup-failure.service /etc/systemd/system/
sudo install -m 0644 /tmp/driftnote-source/deploy/driftnote-backup.timer       /etc/systemd/system/

rm -rf /tmp/driftnote-source
```

## 5. Pull the image + start

```bash
sudo podman pull ghcr.io/maciej-makowski/driftnote:latest
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote.container driftnote-backup.timer
```

Quadlets are translated to `.service` units by `daemon-reload`; the actual unit name is `driftnote.service` (the `.container` suffix is the source).

```bash
sudo systemctl status driftnote.service     # should be active (running)
sudo journalctl -u driftnote.service -f      # tail logs for a few seconds
```

## 6. Post-deploy verification

(Smoke test from a workstation, not the RPi:)

```bash
# 1. Health endpoint reachable through Cloudflare Tunnel + Access.
#    First time: browser opens to Cloudflare's identity provider; auth.
#    Then:
curl -sf https://driftnote.<your-domain>/healthz
# Expected: {"status":"ok","db":"ok",...}
```

Then from the RPi:
```bash
# 2. Send a manual prompt.
sudo podman exec systemd-driftnote driftnote send-prompt
# Confirm it lands in your `Driftnote/Inbox` Gmail label.
```

Reply to the prompt from your phone, then:
```bash
# 3. Force a poll cycle (don't wait for cron).
sudo podman exec systemd-driftnote driftnote poll-responses
```

Open `https://driftnote.<your-domain>/` in your browser — the calendar should show today's date with your reply attached.

## 7. Backups + cloud copy

The local backup timer drops a `tar.zst` snapshot in `/var/driftnote/backups/` on the 1st of each month at 03:00. Local retention defaults to 12 months. For off-host copy, pick one of:

### Option A: rclone systemd timer on the RPi (preferred)

```bash
sudo dnf install -y rclone   # or apt install
sudo -u driftnote rclone config   # walk through the OneDrive (or B2 / S3 / etc.) wizard
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

And `/etc/systemd/system/driftnote-cloud-sync.timer`:
```ini
[Unit]
Description=Run Driftnote cloud sync after each monthly backup

[Timer]
OnCalendar=*-*-01 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote-cloud-sync.timer
```

### Option B: Manual scp/rclone from a workstation

(Keeps secrets off the RPi if you prefer.)

```bash
rclone sync user@rpi:/var/driftnote/backups onedrive:driftnote-backups
```

Schedule via your workstation's cron / Task Scheduler.

## 8. Update path

```bash
sudo podman pull ghcr.io/maciej-makowski/driftnote:latest
sudo systemctl restart driftnote.service
sudo journalctl -u driftnote.service -n 50    # confirm it came back up clean
```

If a future release introduces a database schema change, the release notes will include migration instructions. There's no automated migration tooling.

## 9. Rotating credentials

- **Gmail App Password compromised:** Google Account → Security → App passwords → revoke; generate a new one; update `/etc/driftnote/driftnote.env`; `systemctl restart driftnote.service`.
- **Cloudflare AUD compromised:** Zero Trust dashboard → Access → Applications → Driftnote → ⋯ → **Refresh Application Audience (AUD)**. Copy the new value into `driftnote.env`; restart the service. Old JWTs will be rejected immediately.

## Troubleshooting

| Symptom | First check |
|---|---|
| `curl https://driftnote.<your-domain>/healthz` redirects to Cloudflare login | Expected — Access is doing its job. Use a browser. |
| 403 from `/healthz` after login | AUD or team-domain mismatch in `driftnote.env`. Compare to the Application Overview tab. |
| `systemctl status driftnote.service` shows the container exiting | `journalctl -u driftnote.service` — usual suspects are missing env vars (config validation fails fast) or `/var/driftnote/data` permissions. |
| Daily prompt doesn't arrive | `podman exec systemd-driftnote driftnote send-prompt` to test SMTP path; if that works, the scheduler. Check `/admin` (after auth) for `daily_prompt` job history. |
| Reply doesn't appear in calendar | Gmail filter incorrectly marks the reply as read on arrival → `SEARCH UNSEEN` skips it. See the "Setting up Gmail" section in the top-level README. |
| Backup never runs | `systemctl list-timers driftnote-backup.timer` — `Persistent=true` means it'll fire on boot if it missed the scheduled time. |
```

(End of `deploy/README.md` content.)

- [ ] **Step 3: Add a top-level README cross-reference**

In the project root `README.md`, the "Production deployment" section already references `deploy/README.md`. Verify the link still works after the rewrite. If the section is sparse, you can keep it sparse — the meat lives in `deploy/README.md`.

- [ ] **Step 4: Verify the markdown renders cleanly**

No code to test, but check:
```bash
# Optional: render the markdown to confirm no broken syntax
python3 -m markdown_it deploy/README.md > /tmp/deploy.html  # or any md → html tool you have
```

Just visually scan for obvious broken sections. Section anchors should resolve in GitHub's rendered view.

- [ ] **Step 5: Commit**

```bash
git add deploy/README.md
git commit -m "$(cat <<'EOF'
docs(deploy): full RPi setup walkthrough including Cloudflare Tunnel + Access

Replaces the previous deploy/README which assumed Cloudflare was already
configured. New content covers prerequisites, cloudflared install +
tunnel + DNS route, Access application + AUD lookup + policy, RPi user
creation + directory layout + secrets, image pull + systemd quadlet,
post-deploy smoke test, backup-to-cloud workflow (rclone timer or
workstation-side option), update path, credential rotation, and a
troubleshooting table.

Closes #5
EOF
)"
```

### Closeout

**Acceptance criteria:**
- [ ] Following the guide on a clean RPi → working Driftnote instance reachable via Cloudflare Access (won't be tested by the implementer; the user will verify on next deploy).
- [ ] Each step has either an exact command or an explicit dashboard menu path.
- [ ] Cross-link between root `README.md` and `deploy/README.md` is intact.
- [ ] Closes #5 via the commit message.
