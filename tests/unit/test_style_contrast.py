"""Phase-1 contrast lock-in: token values, AA pair set, and invariants.

Encodes the design doc section 3.4 target pair set (pad cells on their
washes included) and runs it against the shipped stylesheet, so CI fails
if a later edit breaks a pair. The checker module is loaded by path
because its filename contains a hyphen.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLE_PATH = REPO_ROOT / "src" / "driftnote" / "web" / "static" / "style.css"
CHECKER_PATH = REPO_ROOT / "scripts" / "check-contrast.py"

TARGET_TOKENS: dict[str, str] = {
    "--bg": "#201b26",
    "--bg-raised": "#2a2432",
    "--bg-hover": "#352e40",
    "--fg": "#eae5f2",
    "--fg-muted": "#b6adca",
    "--fg-dim": "#a49ac0",
    "--accent": "#c5a8f5",
    "--accent-hover": "#d9c4fa",
    "--border": "#3a3145",
    "--warn-bg": "#3a2e1f",
    "--warn-fg": "#f4cf70",
    "--error-bg": "#3c222a",
    "--error-fg": "#f2989e",
    "--ok": "#9fcf9f",
    "--status-warn": "#f4cf70",
    "--status-error": "#f2989e",
    "--cal-entry": "#283428",
    "--cal-today-empty": "#3a2e1f",
}

PAD_CELL_LABELS = {
    "pad cell text on raised wash (td.empty at rest)",
    "pad cell text on entry wash (td.has-entry at rest)",
    "pad cell text on hover wash (td:hover)",
}


@pytest.fixture(name="check", scope="module")
def checker() -> ModuleType:
    """Load scripts/check-contrast.py as a module."""
    spec = importlib.util.spec_from_file_location("check_contrast", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="style_css")
def stylesheet() -> str:
    """The shipped stylesheet text."""
    return STYLE_PATH.read_text(encoding="utf-8")


def test_root_block_holds_exactly_the_phase1_tokens(style_css: str, check: ModuleType) -> None:
    """The :root block equals the section 3.4 set, no extra or missing tokens."""
    assert check.parse_tokens(style_css) == TARGET_TOKENS


def test_every_gated_pair_passes_aa(style_css: str, check: ModuleType) -> None:
    """Every gated pair in the full set clears its threshold on this stylesheet."""
    rows = check.evaluate(style_css)
    failures = [
        f"{r.pair.label}: {r.value} < {r.pair.threshold} ({r.fg_value} on {r.bg_value})"
        for r in rows
        if r.pair.threshold > 0 and r.value < r.pair.threshold
    ]
    assert failures == []


def test_pad_cell_pairs_are_encoded_on_their_washes(check: ModuleType) -> None:
    """The pad-cell rows exist and sit on td.empty, td.has-entry, and hover."""
    labels = {pair.label for pair in check.PAIRS}
    assert labels >= PAD_CELL_LABELS


def test_blend_composites_with_bankers_rounding(check: ModuleType) -> None:
    """Reference row from the W10 shipped table: 0.5 alpha over #252525."""
    assert check.blend("#a0a0a0", "#252525", 0.5) == "626262"


def test_three_digit_hex_expands_like_css(check: ModuleType) -> None:
    """W10 shipped border row: #333 expands to #333333, 1.32 on #1e1e1e."""
    assert check.ratio("#333", "#1e1e1e") == 1.32


def test_hierarchy_stays_ordered_dim_muted_fg(style_css: str, check: ModuleType) -> None:
    """dim < muted < fg on the page background (W10 tuning note)."""
    tokens = check.parse_tokens(style_css)
    dim = check.ratio(tokens["--fg-dim"], tokens["--bg"])
    muted = check.ratio(tokens["--fg-muted"], tokens["--bg"])
    fg = check.ratio(tokens["--fg"], tokens["--bg"])
    assert dim < muted < fg


def test_calendar_block_carries_no_opacity(style_css: str) -> None:
    """The shipped dimming hack is gone; the calendar block holds no opacity.

    Scoped to the calendar section because later phases may legitimately
    use opacity outside it (phase 5 fades preview and admin content in).
    """
    calendar = style_css.split("/* Calendar */", 1)[1].split("/* Tag cloud canvas", 1)[0]
    assert "opacity" not in calendar


def test_fg_dim_token_is_used_by_the_pad_cell_override(style_css: str) -> None:
    """--fg-dim is no longer a declared-but-unused token."""
    assert "var(--fg-dim)" in style_css


def test_no_raw_hex_outside_root(style_css: str) -> None:
    """Issue-9 invariant: all colour values live in the :root block."""
    block = re.search(r":root\s*\{.*?\}", style_css, re.DOTALL)
    assert block is not None
    assert "#" not in style_css.replace(block.group(0), "")
