# Issue 59 implementation plan: base chrome and structural a11y

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-11-08-issue-59-base-chrome.md`](../specs/2026-11-08-issue-59-base-chrome.md). The spec carries the file-by-file detail; this plan is the execution checklist. One PR, no parallel worktrees.

## Steps

- [ ] 1. Stage the files: `base.html.j2` (skip link first in body, main id, colour-scheme meta, theme-color meta, data-URI moon favicon), `style.css` (skip-link block after the banner rules, skip-target scroll handling), the added browse smoke test, this plan, and the spec.
- [ ] 2. Run the integration suite first, before any test edit. Patch only assertions that pin exact head markup; if none break, change nothing (confirmed for this phase: none did).
- [ ] 3. `uv run pytest tests/integration/test_web_routes_browse.py tests/integration/test_web_routes_edit.py tests/integration/test_web_routes_media_and_admin.py -v` passes, including the new chrome smoke test.
- [ ] 4. `uv run pytest -m "not live"` passes apart from the environmental testcontainers errors the pristine master run reproduces; `uv run ruff check src tests`, `uv run ruff format --check src tests`, and `uv run mypy` are clean; `uv run python scripts/check-contrast.py src/driftnote/web/static/style.css` still exits 0; `pyproject.toml` and `uv.lock` stay byte-identical.
- [ ] 5. Open the PR to `master` (OD-6 favicon vetoable at the diff); CI (ruff, mypy, pytest, container smoke build) goes green; squash-merge.
