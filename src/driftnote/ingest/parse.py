"""Parse a raw .eml byte string into a ParsedReply.

We extract:
- message_id, in_reply_to, date_header (from headers)
- body (plain text, with quoted-reply chunks stripped)
- mood (configured regex; falls back to first emoji in body; None if neither)
- tags (configured regex; lowercased + deduplicated)
- attachments (image/* → photo, video/* → video, anything else → other)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Literal


@dataclass(frozen=True)
class AttachmentMaterial:
    filename: str
    mime_type: str
    kind: Literal["photo", "video", "other"]
    content: bytes


@dataclass(frozen=True)
class ParsedReply:
    message_id: str
    in_reply_to: str | None
    date_header: datetime | None
    body: str
    mood: str | None
    tags: list[str]
    attachments: list[AttachmentMaterial]


# Each pattern matches the FIRST line of a quoted-reply header block. The
# stripper truncates the body at the earliest such line. Order does not
# matter — we pick the earliest position regardless of which pattern matched.
_QUOTE_HEADER_PATTERNS = (
    # Gmail / many clients: "On <date>, <name> wrote:"
    re.compile(r"^On\s+.+\s+wrote:\s*$", re.MULTILINE),
    # French locale (Apple Mail / Gmail FR): "Le <date> ..., <name> a écrit :"
    re.compile(r"^Le\s+.+\s+a\s+écrit\s*:\s*$", re.MULTILINE),
    # German locale: "Am <date> schrieb <name>:"
    re.compile(r"^Am\s+.+\s+schrieb\s+.+:\s*$", re.MULTILINE),
    # Polish locale: "<date> <name> napisał(a):"
    re.compile(r"^.+\s+napisał(?:a|\(a\))?\s*:\s*$", re.MULTILINE),
    # Outlook web: long underscore separator above the From: block.
    re.compile(r"^_{3,}\s*$", re.MULTILINE),
    # Outlook desktop / Exchange: explicit "-----Original Message-----" separator.
    re.compile(r"^-{3,}\s*Original\s+Message\s*-{3,}\s*$", re.MULTILINE),
    # Outlook bare "From:" header (kept last as a defensive catch — only
    # fires if none of the more specific separators above matched).
    re.compile(r"^From:\s+.+$", re.MULTILINE),
)


def parse_reply(raw: bytes, *, mood_regex: str, tag_regex: str) -> ParsedReply:
    _parsed = BytesParser(policy=policy.default).parsebytes(raw)
    msg: EmailMessage = _parsed  # BytesParser with policy.default returns EmailMessage at runtime

    message_id = (msg["Message-ID"] or "").strip()
    in_reply_to_raw = msg["In-Reply-To"]
    in_reply_to = in_reply_to_raw.strip() if in_reply_to_raw else None
    date_header_raw = msg["Date"]
    date_header = parsedate_to_datetime(date_header_raw) if date_header_raw else None

    body = _extract_plain_body(msg)
    body = _strip_quoted(body)

    mood, body = _extract_mood(body, mood_regex)
    tags = _extract_tags(body, tag_regex)
    attachments = _collect_attachments(msg)

    return ParsedReply(
        message_id=message_id,
        in_reply_to=in_reply_to,
        date_header=date_header,
        body=body,
        mood=mood,
        tags=tags,
        attachments=attachments,
    )


def _extract_plain_body(msg: EmailMessage) -> str:
    """Prefer text/plain; fall back to a stripped text/html if no plain part exists."""
    plain = msg.get_body(preferencelist=("plain",))
    if plain is not None:
        return str(plain.get_content()).rstrip("\n") + "\n"
    html = msg.get_body(preferencelist=("html",))
    if html is not None:
        return _crude_html_to_text(str(html.get_content()))
    return ""


def _crude_html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip() + "\n"


def _strip_quoted(body: str) -> str:
    """Remove the quoted-reply portion: everything from `On … wrote:` (or similar) onward,
    plus any block of `>`-prefixed lines at the end."""
    # Find the earliest quote-marker line; truncate there.
    cut_idx: int | None = None
    for pattern in _QUOTE_HEADER_PATTERNS:
        m = pattern.search(body)
        if m and (cut_idx is None or m.start() < cut_idx):
            cut_idx = m.start()
    if cut_idx is not None:
        body = body[:cut_idx]
    # Also trim trailing `>`-prefixed lines (defensive: some clients omit the header).
    lines = body.splitlines()
    while lines and lines[-1].lstrip().startswith(">"):
        lines.pop()
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def _extract_mood(body: str, mood_regex: str) -> tuple[str | None, str]:
    """Extract the mood from the body and return (mood, body_without_mood_line).

    If a mood_regex match is found, the entire matched line is removed from the body.
    Falls back to the first emoji in the body (without removing it).
    Returns (None, body) if no mood is found.
    """
    m = re.search(mood_regex, body, re.MULTILINE)
    if m:
        mood = m.group(1)
        # Remove the entire line containing the mood marker.
        line_start = body.rfind("\n", 0, m.start()) + 1
        line_end = body.find("\n", m.end())
        if line_end == -1:
            line_end = len(body)
        else:
            line_end += 1  # include the newline
        cleaned = body[:line_start] + body[line_end:]
        # Collapse multiple leading blank lines that may result from removal.
        cleaned = re.sub(r"^\n+", "", cleaned)
        return mood, cleaned
    # Fallback: first emoji in the body (don't remove it from the body).
    for ch in body:
        if _is_emoji(ch):
            return ch, body
    return None, body


def _is_emoji(ch: str) -> bool:
    """Quick-and-dirty emoji classifier — enough for journal mood extraction.

    Categories starting with 'S' (Symbol) are the safest broad bucket; we also
    include common emoji-block code points by Unicode property.
    """
    if not ch:
        return False
    cat = unicodedata.category(ch)
    if cat in {"So", "Sk"}:  # Other-Symbol, Modifier-Symbol
        return True
    cp = ord(ch)
    # Misc Symbols, Pictographs, Emoticons, Transport, Supplemental Symbols, etc.
    return any(
        lo <= cp <= hi
        for lo, hi in (
            (0x1F300, 0x1F6FF),
            (0x1F900, 0x1F9FF),
            (0x1FA70, 0x1FAFF),
            (0x2600, 0x26FF),
            (0x2700, 0x27BF),
        )
    )


def _extract_tags(body: str, tag_regex: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in re.finditer(tag_regex, body):
        normalized = m.group(1).lower()
        seen.setdefault(normalized, None)
    return list(seen)


def _collect_attachments(msg: EmailMessage) -> list[AttachmentMaterial]:
    out: list[AttachmentMaterial] = []
    for part in msg.iter_attachments():
        mime = (part.get_content_type() or "application/octet-stream").lower()
        filename = part.get_filename() or "attachment.bin"
        raw_payload = part.get_payload(decode=True)
        content: bytes = raw_payload if isinstance(raw_payload, bytes) else b""
        if mime.startswith("image/"):
            kind: Literal["photo", "video", "other"] = "photo"
        elif mime.startswith("video/"):
            kind = "video"
        else:
            kind = "other"
        out.append(
            AttachmentMaterial(filename=filename, mime_type=mime, kind=kind, content=content)
        )
    return out
