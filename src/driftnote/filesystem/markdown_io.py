"""Read and write `entry.md` — YAML frontmatter + markdown body.

The frontmatter is parsed as YAML via PyYAML. Writes are atomic via
`os.replace`. Multi-section bodies (when several email replies feed into the
same date) keep `---` as an in-body separator; only the *first* `\\n---\\n`
after the opening one is the frontmatter terminator.

I/O uses `newline=""` to disable Python's universal-newline translation so
bodies round-trip byte-for-byte regardless of any embedded `\\r` or other
line-break characters. Property tests rely on this.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class MalformedEntryError(ValueError):
    """Raised when an entry.md file cannot be parsed as frontmatter+body."""


class PhotoRef(BaseModel):
    filename: str
    caption: str = ""


class VideoRef(BaseModel):
    filename: str
    caption: str = ""


class EntryDocument(BaseModel):
    date: date
    mood: str | None = None
    tags: list[str] = Field(default_factory=list)
    photos: list[PhotoRef] = Field(default_factory=list)
    videos: list[VideoRef] = Field(default_factory=list)
    created_at: str
    updated_at: str
    sources: list[str] = Field(default_factory=list)
    body: str = ""


def read_entry(path: Path) -> EntryDocument:
    """Parse entry.md at `path` into an EntryDocument. Raises MalformedEntryError on bad input."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if not text.startswith("---\n"):
        raise MalformedEntryError(f"{path}: missing opening frontmatter delimiter")

    rest = text[len("---\n") :]
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        # Could also be terminated by trailing ---\n with no body (hand-edited files only;
        # write_entry() never produces this shape).
        if rest.endswith("\n---"):
            fm_text, body = rest[: -len("\n---")], ""
        else:
            raise MalformedEntryError(f"{path}: unterminated frontmatter")
    else:
        fm_text = rest[:end_idx]
        body = rest[end_idx + len("\n---\n") :]

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise MalformedEntryError(f"{path}: invalid YAML frontmatter: {exc}") from exc

    if not isinstance(fm, dict):
        raise MalformedEntryError(f"{path}: frontmatter is not a mapping")

    fm["body"] = body
    try:
        return EntryDocument.model_validate(fm)
    except Exception as exc:  # pydantic.ValidationError is the expected subclass
        raise MalformedEntryError(f"{path}: invalid entry: {exc}") from exc


def write_entry(path: Path, doc: EntryDocument) -> None:
    """Atomically write `doc` to `path`. Creates parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_dict = doc.model_dump(mode="json", exclude={"body"})
    fm_text = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True).rstrip()
    rendered = f"---\n{fm_text}\n---\n{doc.body}"

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(rendered)
    tmp.replace(path)
