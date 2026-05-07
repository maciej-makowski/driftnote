# Deploying Driftnote on the Raspberry Pi

## 0. Prerequisites

- Fedora-derived host with `podman` + systemd's container quadlet support.
- A user `driftnote` (`useradd -r -m -s /sbin/nologin driftnote`).
- `cloudflared` already configured to route a hostname → `127.0.0.1:8000`.
- A directory `/var/driftnote/` owned by user `driftnote`.

## 1. Install scripts and units

```bash
sudo install -d /usr/local/lib/driftnote/scripts
sudo install -m 0755 scripts/backup.sh scripts/alert-email.py /usr/local/lib/driftnote/scripts/

sudo install -m 0644 deploy/driftnote.container /etc/containers/systemd/
sudo install -m 0644 deploy/driftnote-backup.service /etc/systemd/system/
sudo install -m 0644 deploy/driftnote-backup-failure.service /etc/systemd/system/
sudo install -m 0644 deploy/driftnote-backup.timer /etc/systemd/system/
```

## 2. Drop in config + secrets

```bash
sudo install -d -m 0700 -o root /etc/driftnote
sudo install -m 0600 -o root config/config.example.toml /var/driftnote/config.toml
sudo $EDITOR /etc/driftnote/driftnote.env   # see template below
```

Template for `/etc/driftnote/driftnote.env`:

```
DRIFTNOTE_GMAIL_USER=you@gmail.com
DRIFTNOTE_GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
DRIFTNOTE_CF_ACCESS_AUD=<application-AUD-tag>
DRIFTNOTE_CF_TEAM_DOMAIN=<your-team>.cloudflareaccess.com
DRIFTNOTE_WEB_BASE_URL=https://driftnote.<your-domain>
DRIFTNOTE_ENVIRONMENT=prod
```

## 3. Enable

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now driftnote.container
sudo systemctl enable --now driftnote-backup.timer
```

## 4. Verify

```bash
curl -s http://127.0.0.1:8000/healthz  # {"status":"ok",...}
sudo journalctl -u driftnote.container -f
```

## 5. Update

```bash
sudo podman pull ghcr.io/maciej-makowski/driftnote:latest
sudo systemctl restart driftnote.container
```
