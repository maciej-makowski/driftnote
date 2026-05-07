"""Connection parameters for IMAP and SMTP transports.

Translated from `Config` once at app startup; passed to send/poll functions.
"""

from __future__ import annotations

from dataclasses import dataclass

from driftnote.config import Config


@dataclass(frozen=True)
class ImapTransport:
    host: str
    port: int
    tls: bool
    username: str
    password: str
    inbox_folder: str
    processed_folder: str


@dataclass(frozen=True)
class SmtpTransport:
    host: str
    port: int
    tls: bool  # implicit TLS (SMTPS, port 465)
    starttls: bool  # opportunistic STARTTLS (port 587)
    username: str
    password: str
    sender_address: str
    sender_name: str


def transports_from_config(cfg: Config) -> tuple[ImapTransport, SmtpTransport]:
    imap = ImapTransport(
        host=cfg.email.imap_host,
        port=cfg.email.imap_port,
        tls=cfg.email.imap_tls,
        username=cfg.secrets.gmail_user,
        password=cfg.secrets.gmail_app_password.get_secret_value(),
        inbox_folder=cfg.email.imap_folder,
        processed_folder=cfg.email.imap_processed_folder,
    )
    smtp = SmtpTransport(
        host=cfg.email.smtp_host,
        port=cfg.email.smtp_port,
        tls=cfg.email.smtp_tls,
        starttls=cfg.email.smtp_starttls,
        username=cfg.secrets.gmail_user,
        password=cfg.secrets.gmail_app_password.get_secret_value(),
        sender_address=cfg.secrets.gmail_user,
        sender_name=cfg.email.sender_name,
    )
    return imap, smtp
