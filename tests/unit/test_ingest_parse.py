"""Tests for raw-email parsing."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path as _Path

import pytest as _pytest

from driftnote.ingest.parse import (
    parse_reply,
)


def _eml(
    *,
    subject: str = "[Driftnote] How was 2026-05-06?",
    body_text: str = "Mood: 💪\n\nLong day at work. #work #cooking",
    body_html: str | None = None,
    in_reply_to: str | None = "<prompt-2026-05-06@driftnote>",
    attachments: list[tuple[str, str, bytes]] | None = None,  # (filename, mime, bytes)
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "you@gmail.com"
    msg["To"] = "you@gmail.com"
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="driftnote")
    msg["Date"] = "Wed, 06 May 2026 21:30:15 +0000"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    for filename, mime, payload in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def test_parse_extracts_mood_marker() -> None:
    raw = _eml(body_text="Mood: 💪\n\nGood day.")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood == "💪"
    assert parsed.body.strip() == "Good day."


def test_parse_falls_back_to_first_emoji_when_no_mood_marker() -> None:
    raw = _eml(body_text="🎉 yay something happened\n#celebrate")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood == "🎉"
    assert "celebrate" in parsed.tags


def test_parse_no_mood_at_all_yields_none() -> None:
    raw = _eml(body_text="Just some plain ASCII text. No mood available.\n#nothing")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood is None


def test_parse_extracts_tags_lowercased_deduplicated() -> None:
    raw = _eml(body_text="Mood: 💪\n\n#Work #work #COOKING and #cooking again")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert sorted(parsed.tags) == ["cooking", "work"]


def test_parse_strips_quoted_thread() -> None:
    body = (
        "Mood: 🌧️\n\nRainy walk in the park.\n\n"
        "On Wed, 6 May 2026 at 21:00, Driftnote <you@gmail.com> wrote:\n"
        "> Hi Maciej,\n"
        "> How was today?\n"
    )
    raw = _eml(body_text=body)
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert "Rainy walk in the park." in parsed.body
    assert "How was today?" not in parsed.body
    assert "On Wed" not in parsed.body


def test_parse_returns_in_reply_to() -> None:
    raw = _eml(in_reply_to="<prompt-2026-05-06@driftnote>")
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.in_reply_to == "<prompt-2026-05-06@driftnote>"


def test_parse_returns_message_id_and_date() -> None:
    raw = _eml()
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.message_id.startswith("<")
    # Date header parses to datetime
    assert parsed.date_header is not None
    assert parsed.date_header.year == 2026


def test_parse_attachments_split_by_mime_type() -> None:
    raw = _eml(
        attachments=[
            ("photo.jpg", "image/jpeg", b"\xff\xd8\xff\xd9"),
            ("video.mov", "video/quicktime", b"MOOV..."),
            ("notes.pdf", "application/pdf", b"%PDF-..."),
        ]
    )
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    photos = [a for a in parsed.attachments if a.kind == "photo"]
    videos = [a for a in parsed.attachments if a.kind == "video"]
    other = [a for a in parsed.attachments if a.kind == "other"]
    assert [a.filename for a in photos] == ["photo.jpg"]
    assert [a.filename for a in videos] == ["video.mov"]
    assert [a.filename for a in other] == ["notes.pdf"]


def test_parse_attachment_material_round_trips_bytes() -> None:
    raw = _eml(attachments=[("photo.jpg", "image/jpeg", b"\xff\xd8\xffJPG")])
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.attachments[0].content == b"\xff\xd8\xffJPG"


def test_parse_picks_plain_body_over_html_when_both_present() -> None:
    raw = _eml(
        body_text="Mood: 🎉\n\nplain text version",
        body_html="<p>HTML version</p>",
    )
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert "plain text version" in parsed.body
    assert "<p>" not in parsed.body


_FIXTURE_DIR = _Path(__file__).parent.parent / "fixtures" / "emails"


@_pytest.mark.parametrize(
    "fixture_name,expected_body_substr,expected_mood",
    [
        ("reply_outlook_web.eml", "Outlook web reply body", "💪"),
        ("reply_apple_mail_macos.eml", "Apple Mail macOS reply body", "🌧️"),
        ("reply_iphone_gmail_app.eml", "iPhone Gmail body", "🎉"),
        ("reply_french_locale.eml", "Journée tranquille au café", "☕"),
        ("reply_outlook_separator_line.eml", "Old-school Outlook reply", "😴"),
    ],
)
def test_parse_strips_quoted_block_for_real_clients(
    fixture_name: str, expected_body_substr: str, expected_mood: str
) -> None:
    raw = (_FIXTURE_DIR / fixture_name).read_bytes()
    parsed = parse_reply(raw, mood_regex=r"^\s*Mood:\s*(\S+)", tag_regex=r"#(\w+)")
    assert parsed.mood == expected_mood
    assert expected_body_substr in parsed.body
    # The original prompt should never bleed into the parsed body.
    assert "How was 2026-05-09" not in parsed.body
    assert "Comment s'est passée" not in parsed.body  # French prompt
    # Outlook's "From: <sender> Sent: ... Subject: ..." block must be stripped.
    assert "Sent: Saturday" not in parsed.body
    # The "Sent from my iPhone" signature is treated as user content here —
    # acceptable; the intent of this test is the QUOTED prompt is stripped.
