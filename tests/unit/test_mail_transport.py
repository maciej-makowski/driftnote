"""Tests for mail transport config translation."""

from __future__ import annotations

from pydantic import SecretStr

from driftnote.config import (
    BackupConfig,
    Config,
    DigestsConfig,
    DiskConfig,
    EmailConfig,
    ParsingConfig,
    PromptConfig,
    ScheduleConfig,
    Secrets,
)
from driftnote.mail.transport import ImapTransport, SmtpTransport, transports_from_config


def _config(**email_overrides: object) -> Config:
    email = EmailConfig(
        imap_folder="Driftnote/Inbox",
        imap_processed_folder="Driftnote/Processed",
        recipient="you@gmail.com",
        sender_name="Driftnote",
        imap_host="imap.gmail.com",
        imap_port=993,
        imap_tls=True,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_tls=False,
        smtp_starttls=True,
    )
    return Config(
        schedule=ScheduleConfig(
            daily_prompt="0 21 * * *",
            weekly_digest="0 8 * * 1",
            monthly_digest="0 8 1 * *",
            yearly_digest="0 8 1 1 *",
            imap_poll="*/5 * * * *",
            timezone="Europe/London",
        ),
        email=email.model_copy(update=email_overrides),
        prompt=PromptConfig(subject_template="[Driftnote] {date}", body_template="t.j2"),
        parsing=ParsingConfig(
            mood_regex=r"^Mood:\s*(\S+)", tag_regex=r"#(\w+)", max_photos=4, max_videos=2
        ),
        digests=DigestsConfig(weekly_enabled=True, monthly_enabled=True, yearly_enabled=True),
        backup=BackupConfig(retain_months=12, encrypt=False, age_key_path=""),
        disk=DiskConfig(
            warn_percent=80,
            alert_percent=95,
            check_cron="0 */6 * * *",
            data_path="/var/driftnote/data",
        ),
        secrets=Secrets(
            gmail_user="you@gmail.com",
            gmail_app_password=SecretStr("p"),
            cf_access_aud="aud",
            cf_team_domain="t.example.com",
        ),
    )


def test_transports_from_config_prod() -> None:
    cfg = _config()
    imap, smtp = transports_from_config(cfg)
    assert imap == ImapTransport(
        host="imap.gmail.com",
        port=993,
        tls=True,
        username="you@gmail.com",
        password="p",
        inbox_folder="Driftnote/Inbox",
        processed_folder="Driftnote/Processed",
    )
    assert smtp == SmtpTransport(
        host="smtp.gmail.com",
        port=587,
        tls=False,
        starttls=True,
        username="you@gmail.com",
        password="p",
        sender_address="you@gmail.com",
        sender_name="Driftnote",
        reply_to=None,
    )


def test_transports_from_config_dev_with_overrides() -> None:
    cfg = _config(
        imap_host="mail",
        imap_port=3143,
        imap_tls=False,
        smtp_host="mail",
        smtp_port=3025,
        smtp_starttls=False,
    )
    imap, smtp = transports_from_config(cfg)
    assert imap.host == "mail"
    assert imap.tls is False
    assert smtp.starttls is False
    assert smtp.port == 3025


def test_transports_from_config_propagates_reply_to() -> None:
    cfg = _config(reply_to="you+driftnote@gmail.com")
    _imap, smtp = transports_from_config(cfg)
    assert smtp.reply_to == "you+driftnote@gmail.com"


def test_transports_from_config_reply_to_defaults_to_none() -> None:
    cfg = _config()
    _imap, smtp = transports_from_config(cfg)
    assert smtp.reply_to is None
