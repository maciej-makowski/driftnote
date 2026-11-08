#!/usr/bin/env python3
"""WCAG AA contrast gate for driftnote's stylesheet tokens.

Reads the stylesheet given as the first argument, parses its :root block,
evaluates the pair set the phase-1 design locks in, prints the table, and
exits 1 when any gated pair is below its threshold.

Method (design doc section 3.4, W10 note): WCAG 2.x relative luminance from
sRGB components, ratio (L1+0.05)/(L2+0.05) rounded to 2 decimals, alpha
compositing with banker's rounding on the foreground before the ratio.
Thresholds: 4.5:1 for normal text, 3:1 for large text and non-text UI
affordances. Decorative rows print for reference and never gate the exit
code: the borders they describe carry no required information, so WCAG
1.4.11 does not apply.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

AA_TEXT = 4.5
AA_NON_TEXT = 3.0
DECORATIVE = 0.0


def norm(hexc: str) -> str:
    """Expand a 3-digit #rgb hex to #rrggbb (CSS semantics)."""
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return h


def lum(hexc: str) -> float:
    """WCAG 2.x relative luminance of an #rrggbb colour."""
    h = norm(hexc)
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def ratio(fg: str, bg: str) -> float:
    """Contrast ratio of two #rrggbb colours, rounded to 2 decimals."""
    l1, l2 = lum(fg), lum(bg)
    return round((max(l1, l2) + 0.05) / (min(l1, l2) + 0.05), 2)


def blend(fg: str, bg: str, alpha: float) -> str:
    """Composite fg over bg at alpha, banker's rounding per channel."""
    f, b = norm(fg), norm(bg)
    return "".join(
        f"{round(int(f[i : i + 2], 16) * alpha + int(b[i : i + 2], 16) * (1 - alpha)):02x}"
        for i in (0, 2, 4)
    )


def parse_tokens(css: str) -> dict[str, str]:
    """Name to value mapping of the first :root block in a stylesheet."""
    block = re.search(r":root\s*\{(.*?)\}", css, re.DOTALL)
    if block is None:
        msg = "no :root block found in stylesheet"
        raise ValueError(msg)
    tokens: dict[str, str] = {}
    for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block.group(1)):
        tokens[name] = value.strip()
    return tokens


def resolve(name: str, tokens: dict[str, str]) -> str:
    """Token reference to its value; a literal #rrggbb passes through."""
    if name.startswith("--"):
        try:
            return tokens[name]
        except KeyError:
            msg = f"token {name} not defined in :root"
            raise ValueError(msg) from None
    return name


class Pair(NamedTuple):
    """One gated or informational fg/bg pair from the design doc."""

    label: str
    fg: str  # token name or #rrggbb literal
    bg: str  # token name or #rrggbb literal
    threshold: float  # gate at this ratio; DECORATIVE means reference row
    alpha: float = 1.0


class Row(NamedTuple):
    """One evaluated pair, with the values and ratio it was judged on."""

    pair: Pair
    fg_value: str
    bg_value: str
    value: float
    passed: bool


PAIRS: tuple[Pair, ...] = (
    # Text pairs at AA 4.5:1. Selector context in each label names the
    # surface the pair models (W10 proposed table, design doc section 3.4).
    Pair("body text", "--fg", "--bg", AA_TEXT),
    Pair("card text (chips, cards, results rows)", "--fg", "--bg-raised", AA_TEXT),
    Pair("secondary text (topbar nav, labels, runs th)", "--fg-muted", "--bg", AA_TEXT),
    Pair("tag chip text", "--fg-muted", "--bg-raised", AA_TEXT),
    Pair("chip hover text", "--accent", "--bg-hover", AA_TEXT),
    Pair("pad cell text on raised wash (td.empty at rest)", "--fg-dim", "--bg-raised", AA_TEXT),
    Pair("pad cell text on entry wash (td.has-entry at rest)", "--fg-dim", "--cal-entry", AA_TEXT),
    Pair("pad cell text on hover wash (td:hover)", "--fg-dim", "--bg-hover", AA_TEXT),
    Pair("links", "--accent", "--bg", AA_TEXT),
    Pair("link hover", "--accent-hover", "--bg", AA_TEXT),
    Pair("button text", "--bg", "--accent", AA_TEXT),
    Pair("button text on hover", "--bg", "--accent-hover", AA_TEXT),
    Pair("warn banner text", "--warn-fg", "--warn-bg", AA_TEXT),
    Pair("error banner text", "--error-fg", "--error-bg", AA_TEXT),
    Pair("test-controls body text", "--fg", "--warn-bg", AA_TEXT),
    Pair("calendar day text (td.has-entry)", "--fg", "--cal-entry", AA_TEXT),
    Pair("calendar dom label (td.has-entry)", "--fg-muted", "--cal-entry", AA_TEXT),
    Pair("calendar today text (td.today-empty)", "--fg", "--cal-today-empty", AA_TEXT),
    Pair("calendar today dom label", "--fg-muted", "--cal-today-empty", AA_TEXT),
    # Non-text pairs at 3:1 (WCAG 1.4.11): dots, status stripes, focus ring.
    Pair("ok dot on card (non-text)", "--ok", "--bg-raised", AA_NON_TEXT),
    Pair("error status stripe on card (non-text)", "--status-error", "--bg-raised", AA_NON_TEXT),
    Pair("focus outline (non-text)", "--accent", "--bg", AA_NON_TEXT),
    # Decorative rows: printed for reference, never gate the exit code.
    Pair("border on bg (decorative, no required info)", "--border", "--bg", DECORATIVE),
    Pair("border on raised (decorative, no required info)", "--border", "--bg-raised", DECORATIVE),
)


def evaluate(css: str) -> list[Row]:
    """Evaluate every pair in PAIRS against a stylesheet's text."""
    tokens = parse_tokens(css)
    rows: list[Row] = []
    for pair in PAIRS:
        fg = resolve(pair.fg, tokens)
        bg = resolve(pair.bg, tokens)
        if pair.alpha < 1.0:
            fg = blend(fg, bg, pair.alpha)
        value = ratio(fg, bg)
        gated = pair.threshold > DECORATIVE
        rows.append(Row(pair, fg, bg, value, not gated or value >= pair.threshold))
    return rows


def print_table(rows: list[Row]) -> None:
    """Print the pair table in fixed columns."""
    label_w = max(len(r.pair.label) for r in rows)
    print(f"{'pair':<{label_w}}  {'fg':<7}  {'bg':<7}  {'ratio':>5}  {'gate':<5}  verdict")
    for r in rows:
        if r.pair.threshold == DECORATIVE:
            gate, verdict = "-", "decorative"
        else:
            gate, verdict = f"{r.pair.threshold:.0f}:1", ("pass" if r.passed else "FAIL")
        print(
            f"{r.pair.label:<{label_w}}  {r.fg_value:<7}  {r.bg_value:<7}"
            f"  {r.value:>5.2f}  {gate:<5}  {verdict}"
        )


def main(argv: list[str] | None = None) -> int:
    """Parse the stylesheet, print the pair table, exit 1 on any AA failure."""
    parser = argparse.ArgumentParser(
        description="Check a stylesheet's :root pairs against WCAG AA.",
    )
    parser.add_argument("stylesheet", type=Path, help="stylesheet holding the :root token block")
    args = parser.parse_args(argv)

    rows = evaluate(args.stylesheet.read_text(encoding="utf-8"))
    print_table(rows)
    failures = [r for r in rows if r.pair.threshold > DECORATIVE and not r.passed]
    if failures:
        print(f"\n{len(failures)} pair(s) below threshold")
        return 1
    print("\nall gated pairs pass AA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
