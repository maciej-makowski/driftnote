#!/usr/bin/env python3
"""Stand-alone alert-email helper.

Invoked by /etc/systemd/system/driftnote-backup.service via OnFailure=. Reads
SMTP credentials from the same env file the app uses. Subject + body come from
$1 and $2.
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: alert-email.py <subject> <body>", file=sys.stderr)
        return 2

    subject, body = sys.argv[1], sys.argv[2]

    user = os.environ["DRIFTNOTE_GMAIL_USER"]
    password = os.environ["DRIFTNOTE_GMAIL_APP_PASSWORD"]
    host = os.environ.get("DRIFTNOTE_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("DRIFTNOTE_SMTP_PORT", "587"))
    starttls = os.environ.get("DRIFTNOTE_SMTP_STARTTLS", "true").lower() == "true"

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = user
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if starttls:
            smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
