# Issue 61 implementation plan: cosy surfaces and calendar a11y

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-11-08-issue-61-cosy-surfaces.md`](../specs/2026-11-08-issue-61-cosy-surfaces.md). The spec carries the file-by-file detail; this plan is the execution checklist. One PR, no parallel worktrees.

## Steps

- [ ] 1. Stage the files: `style.css` (second `:root` block with `--radius-m`, `--space-1..6`, `--ease-settle`, `--dur-fast`; radius on chips, buttons, inputs, cards, calendar cells, results rows; inputs borderless; spacing tokenisation with chip padding untouched; the hover/focus transition rule; the `prefers-reduced-motion` block; the `.calendar-empty` rule), `calendar.html.j2` (cell anchor `aria-label` with the full date, the empty-month conditional line), `routes_browse.py` (the one additive `month_empty` context boolean), the spec, and this plan.
- [ ] 2. Run the integration suite first, before any test edit, and compare against the pristine master run. Patch only assertions that pin exact values this phase changes (confirmed for this phase: the two calendar anchor regexes); if a phase-1 unit test breaks, the CSS rule is wrong, not the test.
- [ ] 3. Add the four browse tests: full-date `aria-label` on all 42 cell links, the empty-month line present, absent, and pad-cell scoping.
- [ ] 4. `uv run pytest -m "not live"` passes apart from the environmental testcontainers errors the pristine master run reproduces with identical node ids; `uv run ruff check src tests`, `uv run ruff format --check src tests`, and `uv run mypy` are clean; `uv run python scripts/check-contrast.py src/driftnote/web/static/style.css` exits 0 on 26 rows; the invariant greps hold (no `#` outside `:root`, no shadows, gradients, keyframes, or opacity, `!important` only in the reduced-motion block, no transform or animation properties, chip padding literal); `pyproject.toml` and `uv.lock` stay byte-identical.
- [ ] 5. Open the PR to `master`; CI (ruff, mypy, pytest, container smoke build) goes green; squash-merge. Phases 1 to 3 then ride the first batched deploy (Maciek-gated).
