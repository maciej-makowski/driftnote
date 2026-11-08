"""Phase-1 contrast lock-in: token values, AA pair set, and invariants.

Encodes the design doc section 3.4 target pair set (pad cells on their
washes included) and runs it against the shipped stylesheet, so CI fails
if a later edit breaks a pair. The checker module is loaded by path
because its filename contains a hyphen.

Phase 5 adds the second :root block's exact-set pin (the geometry/motion
accumulator block) and the motion invariants' recorded exemptions: the
banner entrance is the stylesheet's only @keyframes, and the
prefers-reduced-motion block remains the only !important.
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


# Phase 5 (issue 65): motion completion. The second :root block is the
# redesign's geometry/motion accumulator (the phase-3 review asked for an
# exact-set pin once phase 5 grew it), and the motion invariants gain
# their two recorded exemptions.


GEOMETRY_AND_MOTION_TOKENS: dict[str, str] = {
    "--radius-m": "8px",
    "--space-1": "4px",
    "--space-2": "8px",
    "--space-3": "12px",
    "--space-4": "16px",
    "--space-5": "24px",
    "--space-6": "32px",
    "--ease-settle": "cubic-bezier(0.22, 0.61, 0.36, 1)",
    "--ease-soft": "cubic-bezier(0.25, 0.1, 0.25, 1)",
    "--dur-fast": "180ms",
    "--dur-med": "300ms",
    "--dur-slow": "600ms",
    "--font-serif": 'ui-serif, Georgia, "Iowan Old Style", "Times New Roman", serif',
}


def _css_block(css: str, start: int) -> str:
    """The balanced {...} block whose opening brace sits at css[start]."""
    depth = 0
    for end in range(start, len(css)):
        if css[end] == "{":
            depth += 1
        elif css[end] == "}":
            depth -= 1
            if depth == 0:
                return css[start : end + 1]
    msg = "unbalanced braces in stylesheet"
    raise AssertionError(msg)


def parse_second_root_block(css: str) -> dict[str, str]:
    """Name to value mapping of the second :root block in a stylesheet.

    The checker's parse_tokens pins the first block (the colour set); the
    second block is this redesign's geometry/motion accumulator and is
    pinned here by the same token regex.
    """
    starts = [m.start() for m in re.finditer(r":root\s*\{", css)]
    assert len(starts) == 2, f"expected two :root blocks, found {len(starts)}"
    block = _css_block(css, css.index("{", starts[1]))
    tokens: dict[str, str] = {}
    for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block):
        tokens[name] = value.strip()
    return tokens


def test_second_root_block_holds_exactly_the_accumulated_tokens(style_css: str) -> None:
    """The second :root block holds exactly the phase-3 geometry set plus
    the phase-5 motion tokens and --font-serif: nothing missing, nothing
    extra. The block is the phase-5/6 accumulation point, so it is pinned
    the way the first block is."""
    assert parse_second_root_block(style_css) == GEOMETRY_AND_MOTION_TOKENS


def test_banner_entrance_is_the_only_keyframes(style_css: str) -> None:
    """The banner entrance is the stylesheet's single @keyframes and its
    single animation shorthand: the invariant list's second recorded
    exemption, standing next to the reduced-motion block's single
    !important one."""
    assert re.findall(r"@keyframes\s+([\w-]+)\s*\{", style_css) == ["banner-enter"]
    assert re.findall(r"animation:\s*([^;]+);", style_css) == [
        "banner-enter var(--dur-slow) var(--ease-soft) forwards"
    ]


def test_banner_entrance_moves_two_pixels_and_fades_only(style_css: str) -> None:
    """The entrance animates opacity and a 2px translateY and nothing else:
    nothing scales, rotates, skews, or passes the 4px motion cap, and the
    square left stripes ride the strip's rigid transform."""
    block = _css_block(style_css, style_css.index("@keyframes banner-enter"))
    assert "opacity: 0;" in block and "opacity: 1;" in block
    assert "transform: translateY(2px);" in block
    assert "transform: translateY(0);" in block
    for forbidden in ("scale", "rotate", "skew", "matrix", "perspective", "infinite"):
        assert forbidden not in block


def test_banner_entrance_runs_once_and_holds(style_css: str) -> None:
    """The strip's animation runs once on load and then stays settled
    forever: forwards fill, default single iteration, no infinite loop."""
    bodies = re.findall(r"\.banners\s*\{([^}]*)\}", style_css)
    assert any(
        "animation: banner-enter var(--dur-slow) var(--ease-soft) forwards" in body
        for body in bodies
    )
    assert "infinite" not in style_css


def test_htmx_settle_fades_swap_content_in_over_dur_med(style_css: str) -> None:
    """Swapped-in content enters at opacity 0 via htmx's settle class and
    fades in over --dur-med: the opacity-0 opener covers every htmx
    target, and the transition sits on the preview panel's direct
    children and on the admin cards grid (the phase-6 partial's swapped
    root) in their settled state, so removing the class animates the
    fade in."""
    assert re.search(r"\.htmx-added\s*\{\s*opacity:\s*0;\s*\}", style_css)
    rule = re.search(r"\.preview > \*,\s*\.job-cards\s*\{([^}]*)\}", style_css)
    assert rule is not None
    assert "opacity" in rule.group(1)
    assert "var(--dur-med)" in rule.group(1)
    assert "var(--ease-soft)" in rule.group(1)


def test_preview_shares_the_entry_reading_style(style_css: str) -> None:
    """What you write is what you will read: the edit page's preview panel
    joins .entry-body's serif rule, and the panel reserves three preview
    lines at 17px/1.65 so the first keystroke does not shift the page."""
    reading = re.search(r"\.entry-body,\s*\.preview\s*\{([^}]*)\}", style_css)
    assert reading is not None
    assert '"Newsreader", var(--font-serif)' in reading.group(1)
    assert "font-size: 17px;" in reading.group(1)
    assert "line-height: 1.65;" in reading.group(1)
    panel = re.search(r"\.entry-edit \.preview\s*\{([^}]*)\}", style_css)
    assert panel is not None
    assert "min-height: 84px;" in panel.group(1)


def test_reduced_motion_block_remains_the_only_important(style_css: str) -> None:
    """The invariant list's one !important exemption stays the reduced-
    motion block, and its * selector governs the phase-5 motion too: the
    banner animation and the settle transitions are zeroed for
    reduced-motion users like every other animation and transition."""
    assert style_css.count("!important") == 3
    block = re.search(r"@media \(prefers-reduced-motion: reduce\) \{.*?\}", style_css, re.DOTALL)
    assert block is not None
    assert block.group(0).count("!important") == 3
    assert "animation-duration" in block.group(0)
    assert "animation-iteration-count" in block.group(0)
    assert "transition-duration" in block.group(0)
