"""Smoke test that the GreenMail container fixture comes up."""

from __future__ import annotations

import socket

from tests.conftest import MailServer


def test_mail_server_ports_reachable(mail_server: MailServer) -> None:
    for port in (mail_server.smtp_port, mail_server.imap_port):
        with socket.create_connection((mail_server.host, port), timeout=3):
            pass
