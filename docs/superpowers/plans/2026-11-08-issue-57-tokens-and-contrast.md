# Issue 57 implementation plan: tokens and contrast lock-in

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-11-08-issue-57-tokens-and-contrast.md`](../specs/2026-11-08-issue-57-tokens-and-contrast.md). The spec carries the file-by-file detail; this plan is the execution checklist. One PR, no parallel worktrees.

## Steps

- [ ] 1. Stage the files: `style.css` (18 :root values swapped to the target set; the opacity rule replaced by the scoped pad-cell override), `scripts/check-contrast.py` (new), `tests/unit/test_style_contrast.py` (new), this plan, and the spec.
- [ ] 2. `uv run pytest tests/unit/test_style_contrast.py -v` passes (9 tests); the browse, edit, media, and admin integration suites pass untouched.
- [ ] 3. `uv run python scripts/check-contrast.py src/driftnote/web/static/style.css` exits 0; against the shipped stylesheet at 34360a4 it exits 1.
- [ ] 4. `uv run ruff check src tests`, `uv run ruff format --check src tests`, and `uv run mypy` are clean; `pyproject.toml` and `uv.lock` stay byte-identical.
- [ ] 5. Open the PR to `master`; CI (ruff, mypy, pytest, container smoke build) goes green; squash-merge.
