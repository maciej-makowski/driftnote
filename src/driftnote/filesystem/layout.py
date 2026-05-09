"""Path layout helpers for the entries tree.

Single source of truth for where things live on disk so the rest of the code
never hard-codes path arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

_RAW_FILENAME_FMT = "%Y-%m-%dT%H-%M-%SZ"


@dataclass(frozen=True)
class EntryPaths:
    """All filesystem paths for one day's entry."""

    dir: Path
    entry_md: Path
    raw_dir: Path
    originals_dir: Path
    web_dir: Path
    thumbs_dir: Path


def entry_paths_for(data_root: Path, d: date) -> EntryPaths:
    """Compute (without creating) the path bundle for a given date.

    `data_root` is the parent of `entries/` (i.e. typically `/var/driftnote/data`).
    """
    base = data_root / "entries" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"
    return EntryPaths(
        dir=base,
        entry_md=base / "entry.md",
        raw_dir=base / "raw",
        originals_dir=base / "originals",
        web_dir=base / "web",
        thumbs_dir=base / "thumbs",
    )


def raw_eml_filename(received_at: datetime) -> str:
    """Filesystem-safe filename for a raw .eml message keyed on its received-at UTC time."""
    if received_at.tzinfo is None:
        raise ValueError("received_at must be timezone-aware (use UTC)")
    utc = received_at.astimezone(UTC).replace(microsecond=0)
    return utc.strftime(_RAW_FILENAME_FMT) + ".eml"


def parse_eml_received_at(filename: str) -> datetime:
    """Inverse of raw_eml_filename. Raises ValueError if the name doesn't fit."""
    if not filename.endswith(".eml"):
        raise ValueError(f"not an .eml filename: {filename!r}")
    stem = filename[: -len(".eml")]
    try:
        dt = datetime.strptime(stem, _RAW_FILENAME_FMT)
    except ValueError as exc:
        raise ValueError(f"cannot parse received-at from {filename!r}: {exc}") from exc
    return dt.replace(tzinfo=UTC)
