"""Tests for per-date file locks."""

from __future__ import annotations

import multiprocessing as mp
import time
from datetime import date
from pathlib import Path

from driftnote.filesystem.locks import entry_lock


def _holder(
    data_root_str: str, hold_seconds: float, started_at: list[float], finished_at: list[float]
) -> None:
    from datetime import date as _date

    from driftnote.filesystem.locks import entry_lock as _lock

    with _lock(Path(data_root_str), _date(2026, 5, 6)):
        started_at.append(time.monotonic())
        time.sleep(hold_seconds)
        finished_at.append(time.monotonic())


def test_entry_lock_serializes_concurrent_holders(tmp_path: Path) -> None:
    """Two processes holding the same date's lock must not overlap."""
    mgr = mp.Manager()
    started = mgr.list()
    finished = mgr.list()
    p1 = mp.Process(target=_holder, args=(str(tmp_path), 0.3, started, finished))
    p2 = mp.Process(target=_holder, args=(str(tmp_path), 0.3, started, finished))
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    assert p1.exitcode == 0 and p2.exitcode == 0

    # The second holder's start must be after the first holder's finish.
    starts = sorted(started)
    finishes = sorted(finished)
    assert starts[1] >= finishes[0] - 0.05  # small slack for timer jitter


def test_entry_lock_releases_on_exception(tmp_path: Path) -> None:
    import pytest as _pytest

    with _pytest.raises(RuntimeError), entry_lock(tmp_path, date(2026, 5, 6)):
        raise RuntimeError("boom")
    # If the lock leaked, the next acquisition would block forever.
    with entry_lock(tmp_path, date(2026, 5, 6)):
        pass


def test_entry_lock_creates_lock_file(tmp_path: Path) -> None:
    with entry_lock(tmp_path, date(2026, 5, 6)):
        # Lock file should live under data_root/locks/ keyed by date.
        lock_files = list((tmp_path / "locks").glob("2026-05-06.lock"))
        assert lock_files
