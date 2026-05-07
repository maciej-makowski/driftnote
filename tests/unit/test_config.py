"""Tests for config loading."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from driftnote.config import Config, ConfigError, load_config

_FULL_CONFIG_TOML = """
[schedule]
daily_prompt   = "0 21 * * *"
weekly_digest  = "0 8 * * 1"
monthly_digest = "0 8 1 * *"
yearly_digest  = "0 8 1 1 *"
imap_poll      = "*/5 * * * *"
timezone       = "Europe/London"

[email]
imap_folder            = "Driftnote/Inbox"
imap_processed_folder  = "Driftnote/Processed"
recipient              = "you@gmail.com"
sender_name            = "Driftnote"
imap_host              = "imap.gmail.com"
imap_port              = 993
imap_tls               = true
smtp_host              = "smtp.gmail.com"
smtp_port              = 587
smtp_tls               = false
smtp_starttls          = true

[prompt]
subject_template = "[Driftnote] How was {date}?"
body_template    = "templates/emails/prompt.txt.j2"

[parsing]
mood_regex = '^\\s*Mood:\\s*(\\S+)'
tag_regex  = '#(\\w+)'
max_photos = 4
max_videos = 2

[digests]
weekly_enabled  = true
monthly_enabled = true
yearly_enabled  = true

[backup]
retain_months = 12
encrypt       = false
age_key_path  = ""

[disk]
warn_percent  = 80
alert_percent = 95
check_cron    = "0 */6 * * *"
data_path     = "/var/driftnote/data"
"""


def _write_config(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(dedent(body))
    return p


def test_load_config_minimum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write_config(tmp_path, _FULL_CONFIG_TOML)
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_ENVIRONMENT", "dev")

    cfg = load_config(p)

    assert isinstance(cfg, Config)
    assert cfg.schedule.daily_prompt == "0 21 * * *"
    assert cfg.email.recipient == "you@gmail.com"
    assert cfg.parsing.max_photos == 4
    assert cfg.backup.retain_months == 12
    assert cfg.secrets.gmail_user == "u@example.com"
    assert cfg.secrets.gmail_app_password.get_secret_value() == "p"
    assert cfg.environment == "dev"


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env vars override TOML values for IMAP/SMTP host wiring (dev-mode pattern)."""
    p = _write_config(tmp_path, _FULL_CONFIG_TOML)
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    monkeypatch.setenv("DRIFTNOTE_IMAP_HOST", "mail")
    monkeypatch.setenv("DRIFTNOTE_IMAP_PORT", "3143")
    monkeypatch.setenv("DRIFTNOTE_IMAP_TLS", "false")

    cfg = load_config(p)

    assert cfg.email.imap_host == "mail"
    assert cfg.email.imap_port == 3143
    assert cfg.email.imap_tls is False


def test_missing_secret_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _write_config(tmp_path, '[schedule]\ntimezone = "Europe/London"\n')
    # Intentionally leave DRIFTNOTE_GMAIL_USER unset.
    for var in [
        "DRIFTNOTE_GMAIL_USER",
        "DRIFTNOTE_GMAIL_APP_PASSWORD",
        "DRIFTNOTE_CF_ACCESS_AUD",
        "DRIFTNOTE_CF_TEAM_DOMAIN",
    ]:
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ConfigError):
        load_config(p)


def test_load_config_raises_on_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.toml")


def test_load_config_raises_on_malformed_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "config.toml"
    p.write_text("this = is = not = valid\n")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_USER", "u@example.com")
    monkeypatch.setenv("DRIFTNOTE_GMAIL_APP_PASSWORD", "p")
    monkeypatch.setenv("DRIFTNOTE_CF_ACCESS_AUD", "aud")
    monkeypatch.setenv("DRIFTNOTE_CF_TEAM_DOMAIN", "team.example.com")
    with pytest.raises(ConfigError):
        load_config(p)
