"""Per-date file locks via fcntl.flock.

A lock file lives under `data_root/locks/YYYY-MM-DD.lock`. Acquiring an
`entry_lock(data_root, date)` blocks until any other holder releases.

Spec §6 describes "per-date `fcntl.flock` on entry directory"; we instead
keep all lock files under a sibling `locks/` directory so the lock can be
acquired before the entry directory exists (first-time ingestion). The
serialization guarantee is identical.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path


@contextmanager
def entry_lock(data_root: Path, d: date) -> Iterator[None]:
    """Hold an exclusive lock on the per-date lock file. Blocks until acquired."""
    lock_dir = data_root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{d.isoformat()}.lock"
    # Append mode creates the file if absent; we never read/write its contents,
    # we just need an fd to flock on.
    with lock_path.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
