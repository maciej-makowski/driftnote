# Issue #4 — Dark-mode UI redesign + complete calendar grid

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the utilitarian light theme on Driftnote's web UI with a flat dark theme using a coherent purple-accent palette, fix the calendar grid so it always renders six rows with prev/next-month pad cells dimmed (day numbers shown), and give the monthly email digest a parallel light-theme polish pass.

**Architecture:** A CSS-first redesign of the single static stylesheet `style.css` (current 23 lines → fresh rewrite ~150 lines), backed by one small backend change to `MonthlyCell`/`monthly_moodboard_grid` so pad cells carry `day_of_month` and the grid is always six rows. Templates get structural tweaks where the markup blocks the design (admin status dots, entry accent stripe, edit-view preview separation). The monthly email digest gets a parallel light-theme polish: a module-level palette constant replaces inline color literals, pad-cell day numbers render in a muted color, the "Open in Driftnote" link adopts an email-readable purple.

**Tech Stack:** FastAPI server-rendered Jinja2 + HTMX, plain CSS (no framework, no preprocessor), pytest, ruff, mypy.

**Spec:** [docs/superpowers/specs/2026-05-09-issue-4-dark-redesign-design.md](../specs/2026-05-09-issue-4-dark-redesign-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/4

**Branch:** `feat/issue-4-dark-redesign` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-4/`)

---

## Working notes for the implementer

- All file paths in this plan are relative to the repository root (the worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-4/`).
- Tests run via `uv run pytest`. Integration tests live under `tests/integration/`, unit tests under `tests/unit/`. The fast suite excludes `live` and `slow` markers.
- Pre-commit hooks run on `git commit`: `ruff` (lint + auto-fix), `ruff-format`, then `pytest -q -m "not live and not slow" tests/unit`. If a hook fails, fix the cause and create a NEW commit. Never `--amend` after hook failure.
- The codebase uses `from __future__ import annotations` everywhere. Match this convention in new files.
- Colour values in this plan are exact and intentional — do not "improve" them. The spec pinned the palette.
- Use `git mv` for renames, never `mv` followed by `git add`.

---

## Chunk 1: Backend — always-six-rows calendar grid with day numbers on pad cells

This chunk is the only backend change. It enables both the web template's pad-cell rendering and the email digest's pad-cell rendering. Doing it first gives the template tasks something concrete to render against.

### Task 1.1: Update `MonthlyCell` and `monthly_moodboard_grid` (TDD)

**Files:**
- Modify: `src/driftnote/digest/moodboard.py:20-24` (the `MonthlyCell` dataclass) and `src/driftnote/digest/moodboard.py:45-73` (`monthly_moodboard_grid`)
- Test: `tests/unit/test_digest_moodboard.py:29-36` (existing test) plus a new test

**Why this change:** The current grid:
1. Stops as soon as the calendar reaches the last day of the target month and the row ends (so most months are 5 rows, some are 6).
2. Sets `day_of_month=None` for pad cells, so prev/next-month days can't render their date number.

The spec requires both: always 6 rows, every cell carries its day-of-month integer.

- [ ] **Step 1: Tighten and add the failing tests**

Open `tests/unit/test_digest_moodboard.py`. Replace the body of `test_monthly_moodboard_returns_calendar_rows` (currently lines 29-36) with this stricter version, and add the two new tests below it:

```python
def test_monthly_moodboard_returns_six_rows_always() -> None:
    """Every month renders as exactly 6 weeks for stable visual rhythm."""
    days = [_day("2026-05-01"), _day("2026-05-15", mood="🌧️"), _day("2026-05-31", mood="🎉")]
    rows = monthly_moodboard_grid(year=2026, month=5, days=days)
    assert len(rows) == 6
    flat = [c for row in rows for c in row]
    moods = [c.emoji for c in flat if c.in_month and c.day_of_month == 1]
    assert moods == ["💪"]


def test_monthly_moodboard_pads_to_six_rows_for_short_months() -> None:
    """February 2026 is a short month — naturally fits in 5 rows. Must still pad to 6."""
    rows = monthly_moodboard_grid(year=2026, month=2, days=[])
    assert len(rows) == 6


def test_monthly_moodboard_pad_cells_carry_day_of_month() -> None:
    """Prev/next-month pad cells render their actual day number (dimmed in the UI)."""
    rows = monthly_moodboard_grid(year=2026, month=5, days=[])
    flat = [c for row in rows for c in row]
    pad = [c for c in flat if not c.in_month]
    assert pad, "May 2026 starts on a Friday so there must be pad cells"
    # Every pad cell carries a real calendar day number 1..31, not None.
    assert all(isinstance(c.day_of_month, int) for c in pad)
    assert all(1 <= c.day_of_month <= 31 for c in pad)
    # No emoji on pad cells (we don't carry mood data outside the target month).
    assert all(c.emoji is None for c in pad)
```

- [ ] **Step 2: Run the new tests and confirm they fail**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-4
uv run pytest tests/unit/test_digest_moodboard.py -v
```

Expected: the three monthly tests fail. The first fails on `len(rows) == 6` (May 2026 currently fits in 5 weeks); the third fails on `isinstance(c.day_of_month, int)` because pad cells have `day_of_month=None`.

- [ ] **Step 3: Update the `MonthlyCell` type**

In `src/driftnote/digest/moodboard.py`, replace the `MonthlyCell` dataclass (lines 20-24) with:

```python
@dataclass(frozen=True)
class MonthlyCell:
    date: date
    in_month: bool  # False for grid pad cells outside this month
    day_of_month: int  # always populated; pad cells carry the actual prev/next-month day number
    emoji: str | None
```

The change is `day_of_month: int | None` → `day_of_month: int`.

- [ ] **Step 4: Update `monthly_moodboard_grid` to always return 6 rows and populate day_of_month**

Replace the body of `monthly_moodboard_grid` (lines 45-73) with:

```python
def monthly_moodboard_grid(
    *, year: int, month: int, days: list[DayInput]
) -> list[list[MonthlyCell]]:
    """Calendar grid: rows = weeks, columns = Mon..Sun. Always returns six
    rows for stable visual rhythm. Cells outside the target month carry
    `in_month=False` but still expose the prev/next-month day number for
    rendering as dimmed pad cells."""
    by_date = {d.date: d.mood for d in days}

    first = date(year, month, 1)

    # Snap to the Monday of the week containing the 1st.
    grid_start = first - timedelta(days=first.weekday())
    rows: list[list[MonthlyCell]] = []
    cur = grid_start
    for _ in range(6):
        row: list[MonthlyCell] = []
        for _ in range(7):
            in_month = cur.month == month and cur.year == year
            row.append(
                MonthlyCell(
                    date=cur,
                    in_month=in_month,
                    day_of_month=cur.day,
                    emoji=by_date.get(cur) if in_month else None,
                )
            )
            cur += timedelta(days=1)
        rows.append(row)
    return rows
```

Key changes vs. the current implementation:
- The outer `while` loop is replaced with a fixed `for _ in range(6)`. We always emit exactly 6 rows.
- `next_first` (the local that drove the old termination condition) is gone — unused now.
- `day_of_month=cur.day` regardless of `in_month`. Pad cells now carry the actual prev/next-month day number.
- `emoji` stays `None` for pad cells (we don't have mood data outside the target month).

- [ ] **Step 5: Run the moodboard tests and confirm they pass**

```bash
uv run pytest tests/unit/test_digest_moodboard.py -v
```

Expected: all 4 tests in this file pass (the 3 above + the existing `test_yearly_grid_53_weeks_max`).

- [ ] **Step 6: Run the full unit suite to catch any other consumer**

```bash
uv run pytest tests/unit -q
```

Expected: green. The existing monthly digest test (`tests/unit/test_digest_monthly.py`) renders a digest and only asserts emoji and stats are in the output — it doesn't pin row count, so it continues to pass.

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/digest/moodboard.py tests/unit/test_digest_moodboard.py
git commit -m "feat(digest): always render 6-week moodboard grid with pad-cell day numbers"
```

The commit message uses `feat(digest)` because the type signature change (`int | None` → `int`) is a small public API broadening that callers benefit from.

### Task 1.2: Render pad-cell day numbers in the calendar template (TDD)

**Files:**
- Modify: `src/driftnote/web/templates/calendar.html.j2`
- Test: `tests/integration/test_web_routes_browse.py` (add a new test below the existing `test_calendar_page_renders`)

The template currently gates the entire cell content on `{% if c.in_month %}`. We need pad cells to render their day number in a `dim` class so CSS can muted-style them.

- [ ] **Step 1: Add the failing integration test**

Append to `tests/integration/test_web_routes_browse.py`:

```python
def test_calendar_page_renders_pad_cell_day_numbers(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """May 2026 starts Friday: Mon..Thu of week 1 are April 27..30. The grid
    must render those day numbers in cells flagged dim."""
    app, _ = app_with_data
    r = TestClient(app).get("/?year=2026&month=5")
    assert r.status_code == 200
    # Six rows of seven cells each.
    assert r.text.count('<tr>') == 6 + 1  # 6 body rows + 1 header row
    # Pad cells carry the dim class and show their day-of-month.
    assert 'class="dim"' in r.text
    # April 30 is a pad cell at the start of May 2026 (Thu of week 1).
    assert ">30<" in r.text
```

- [ ] **Step 2: Run the test and confirm it fails**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_calendar_page_renders_pad_cell_day_numbers -v
```

Expected: fails on `'class="dim"' in r.text` (pad cells don't render their dim class on the inner element today — though they do on the `<td>`) or on `'>30<' in r.text` (April 30 is not rendered today). The exact failure depends on whether the pre-existing `dim` class on `<td>` matches the substring; the day-number assertion is the load-bearing one.

- [ ] **Step 3: Replace `calendar.html.j2`**

Overwrite `src/driftnote/web/templates/calendar.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ year }}-{{ "%02d"|format(month) }} — Driftnote{% endblock %}
{% block content %}
<h1>{{ month_name }} {{ year }}</h1>
<nav class="month-nav">
  <a href="/?year={{ prev_year }}&month={{ prev_month }}">‹ prev</a>
  <a href="/?year={{ next_year }}&month={{ next_month }}">next ›</a>
</nav>
<table class="calendar">
  <thead><tr>
    {% for label in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"] %}<th>{{ label }}</th>{% endfor %}
  </tr></thead>
  <tbody>
    {% for row in cells %}
      <tr>
      {% for c in row %}
        <td class="{% if c.in_month %}{% if c.date.isoformat() == today_iso %}today{% endif %}{% else %}dim{% endif %}">
          {% if c.in_month %}
            <a href="/entry/{{ c.date.isoformat() }}">
              <div class="dom">{{ c.day_of_month }}</div>
              <div class="emoji">{{ c.emoji or "·" }}</div>
            </a>
          {% else %}
            <div class="dom">{{ c.day_of_month }}</div>
          {% endif %}
        </td>
      {% endfor %}
      </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Key changes:
- Pad cells (`{% else %}`) now render their `day_of_month` inside a `dim`-classed `<td>` and a `dom`-classed inner `<div>` (CSS will style `td.dim .dom` muted).
- In-month cells get a `today` class on the `<td>` when their ISO date matches a new `today_iso` template variable.
- A `today` class is wired up so the CSS rule `td.today` can apply the accent outline.

- [ ] **Step 4: Wire `today_iso` into the route handler**

Open `src/driftnote/web/routes_browse.py`. Locate the `cells = monthly_moodboard_grid(...)` call (around line 76) and the `templates.TemplateResponse` call below it (around line 81-86). Add `today_iso=iso_now()[:10]` to the template context dict. The render call should look like:

```python
cells = monthly_moodboard_grid(year=y, month=m, days=days)
return templates.TemplateResponse(
    request,
    "calendar.html.j2",
    {
        "request": request,
        "year": y,
        "month": m,
        "month_name": _cal.month_name[m],
        "cells": cells,
        "today_iso": iso_now()[:10],
        # ...keep all existing context keys exactly as they are...
    },
)
```

(Read the surrounding code first — keep `prev_year`, `prev_month`, `next_year`, `next_month`, and any other keys that are already there. The example above shows the new key in context, not a complete dict.)

- [ ] **Step 5: Run the new test and confirm it passes**

```bash
uv run pytest tests/integration/test_web_routes_browse.py -v
```

Expected: all 6 tests in this file pass (the 5 existing + the new pad-cell test).

- [ ] **Step 6: Run the integration suite to catch any browse regressions**

```bash
uv run pytest tests/integration -q -m "not live and not slow"
```

Expected: green. Some tests in this directory require external resources and are excluded by the markers — that's intentional.

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/web/templates/calendar.html.j2 src/driftnote/web/routes_browse.py tests/integration/test_web_routes_browse.py
git commit -m "feat(web): render calendar pad cells with day numbers + today class"
```

---

## Chunk 2: CSS rewrite + structural template tweaks

This chunk is mostly content. CSS is hard to TDD line-by-line (visual). The strategy is:
1. Drop in the new stylesheet content as a single replace.
2. Make the structural template changes that the new CSS depends on (admin status dots, entry accent stripe, edit-view preview block, search/admin inline-style cleanup, tag pill markup).
3. Run the full integration suite to catch any markup regressions.
4. Run a grep-based audit step that enforces the spec's invariants (no border-radius outside the dot rule, palette variables present, etc).
5. Visual smoke-test by running the dev server and checking each page at desktop + mobile widths.

### Task 2.1: Rewrite `style.css`

**Files:**
- Modify: `src/driftnote/web/static/style.css` (current 23 lines, full rewrite to ~150 lines)

- [ ] **Step 1: Overwrite `style.css` with the dark-theme rewrite**

Replace the entire contents of `src/driftnote/web/static/style.css` with:

```css
:root {
  --bg:           #1e1e1e;
  --bg-raised:    #252525;
  --bg-hover:     #2d2d2d;
  --fg:           #e5e5e5;
  --fg-muted:     #a0a0a0;
  --fg-dim:       #5a5a5a;
  --accent:       #bb9af7;
  --accent-hover: #d2b8ff;
  --border:       #333;
  --warn-bg:      #3b2a1a;
  --warn-fg:      #f5c542;
  --error-bg:     #3b1a1a;
  --error-fg:     #ff6b6b;
  --ok:           #6dbf6d;
  --status-warn:  #f5c542;
  --status-error: #ff6b6b;
}

* { box-sizing: border-box; }

body {
  font-family: system-ui, sans-serif;
  background: var(--bg);
  color: var(--fg);
  margin: 0 auto;
  padding: 0 16px;
  max-width: 960px;
  font-size: 15px;
  line-height: 1.5;
}

h1 { font-size: 24px; font-weight: 600; margin: 16px 0 12px; }
h2 { font-size: 18px; font-weight: 600; margin: 16px 0 8px; }
h3 { font-size: 16px; font-weight: 600; margin: 12px 0 6px; }

a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); }

:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Top bar */
.topbar {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}
.topbar nav a { margin-left: 16px; color: var(--fg-muted); }
.topbar nav a:hover { color: var(--accent); }
.brand { font-weight: 700; color: var(--fg); }
.brand:hover { color: var(--fg); }

/* Banners */
.banners { display: flex; flex-direction: column; gap: 6px; margin: 12px 0; }
.banner { padding: 8px 12px; }
.banner-warn  { background: var(--warn-bg);  color: var(--warn-fg);  border-left: 4px solid var(--warn-fg); }
.banner-error { background: var(--error-bg); color: var(--error-fg); border-left: 4px solid var(--error-fg); }

/* Calendar */
.month-nav { display: flex; gap: 16px; margin: 8px 0 12px; }
.calendar { width: 100%; border-collapse: collapse; }
.calendar th, .calendar td {
  padding: 4px;
  text-align: center;
  border: 1px solid var(--border);
  height: 56px;
}
.calendar th { color: var(--fg-muted); font-weight: 500; font-size: 13px; }
.calendar td a { color: var(--fg); display: block; }
.calendar td:hover { background: var(--bg-hover); }
.calendar td.dim { color: var(--fg-dim); }
.calendar td.today { outline: 1px solid var(--accent); outline-offset: -1px; }
.calendar .emoji { font-size: 20px; }
.calendar .dom { font-size: 11px; color: var(--fg-muted); }
.calendar td.dim .dom { color: var(--fg-dim); }

/* Tag cloud */
.tag-cloud { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.tag-cloud a {
  background: var(--bg-raised);
  color: var(--fg);
  padding: 2px 8px;
}
.tag-cloud a:hover { background: var(--bg-hover); color: var(--accent); }

/* Entry view */
.entry {
  border-left: 4px solid var(--accent);
  padding: 4px 0 4px 16px;
}
.entry .mood { font-size: 26px; }
.entry .tags a {
  background: var(--bg-raised);
  color: var(--fg-muted);
  padding: 2px 8px;
  margin-right: 6px;
  font-size: 13px;
}
.entry .tags a:hover { background: var(--bg-hover); color: var(--accent); }
.entry .media img { max-width: 240px; margin: 4px; }
.entry .media video { max-width: 100%; }

/* Edit view */
.entry-edit label { display: block; margin: 8px 0 4px; color: var(--fg-muted); font-size: 13px; }
.entry-edit input[type="text"], .entry-edit input:not([type]) {
  background: var(--bg-raised);
  color: var(--fg);
  border: 1px solid var(--border);
  padding: 6px 10px;
  width: 100%;
}
.entry-edit textarea {
  background: var(--bg-raised);
  color: var(--fg);
  border: 1px solid var(--border);
  padding: 8px 10px;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 14px;
}
.entry-edit .preview {
  background: var(--bg);
  border-left: 4px solid var(--accent);
  padding: 12px 16px;
  margin-top: 8px;
}

/* Buttons */
button, .entry-edit button {
  background: var(--accent);
  color: var(--bg);
  border: none;
  padding: 8px 16px;
  font: inherit;
  cursor: pointer;
}
button:hover { background: var(--accent-hover); }

/* Search */
.search-form input[type="search"] {
  background: var(--bg-raised);
  color: var(--fg);
  border: 1px solid var(--border);
  padding: 6px 10px;
  width: 100%;
  max-width: 400px;
}
.search-results { list-style: none; padding: 0; }
.search-results li {
  background: var(--bg-raised);
  padding: 8px 12px;
  margin: 6px 0;
}

/* Admin */
.job-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.job-cards .card {
  background: var(--bg-raised);
  padding: 12px 16px;
}
.job-cards .card h2 { margin-top: 0; font-size: 16px; }
.job-cards .card p { margin: 4px 0; font-size: 14px; }

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.dot-ok    { background: var(--ok); }
.dot-warn  { background: var(--status-warn); }
.dot-error { background: var(--status-error); }

.test-controls {
  margin-top: 24px;
  padding: 12px;
  border: 2px dashed var(--warn-fg);
  background: var(--warn-bg);
  color: var(--fg);
}
.test-controls h2 { margin-top: 0; }
.test-controls .hint { color: var(--fg-muted); margin: 4px 0 12px; font-size: 13px; }
.test-controls form { display: inline-block; margin: 4px; }

.runs { width: 100%; border-collapse: collapse; margin-top: 12px; }
.runs th, .runs td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--border); }
.runs th { color: var(--fg-muted); font-weight: 500; }
.runs tr.status-error td { border-left: 4px solid var(--status-error); }
.runs tr.status-warn  td { border-left: 4px solid var(--status-warn); }
.runs tr.status-ok    td { border-left: 4px solid var(--ok); }

.notice {
  padding: 8px 12px;
  background: var(--bg-raised);
  border-left: 4px solid var(--ok);
  margin: 8px 0;
}

/* Mobile: shrink the calendar so it fits a 360px viewport */
@media (max-width: 600px) {
  .calendar thead { display: none; }
  .calendar td {
    height: 40px;
    padding: 2px;
  }
  .calendar .dom { font-size: 10px; }
  .calendar .emoji { font-size: 16px; }
}
```

Notes for the implementer:
- The CSS is intentionally flat. The only `border-radius` rule is on `.dot { border-radius: 50%; }` (status circle shape). The grep audit in step 4 will fail if any other rule introduces `border-radius`.
- The `runs` table styling uses `border-left` on `<td>` rather than `<tr>` because `border` on table rows is unreliable across browsers when `border-collapse: collapse` is in effect.
- `:focus-visible` is intentional (keyboard focus only) — `:focus` would also fire on mouse clicks, which is visually noisy.

- [ ] **Step 2: Run the existing integration tests to catch markup regressions**

```bash
uv run pytest tests/integration -q -m "not live and not slow"
```

Expected: green. The CSS rewrite shouldn't break any test — tests assert on response status and inner text, not on style attributes.

- [ ] **Step 3: Commit just the CSS**

```bash
git add src/driftnote/web/static/style.css
git commit -m "feat(web): rewrite stylesheet as flat dark theme with purple accent"
```

### Task 2.2: Update `entry.html.j2` and `entry_edit.html.j2` for accent stripe + preview separation

**Files:**
- Modify: `src/driftnote/web/templates/entry.html.j2`
- Modify: `src/driftnote/web/templates/entry_edit.html.j2`

The entry view's accent stripe is implemented via the `.entry` CSS rule (already added). The markup is correct as-is. Confirm by reading the file.

The edit view needs minor structural cleanup so the textarea and preview are sibling blocks the CSS can style independently.

- [ ] **Step 1: Read the current `entry_edit.html.j2`**

The file is short. Open it.

- [ ] **Step 2: Overwrite `entry_edit.html.j2`**

Replace its contents with:

```jinja
{% extends "base.html.j2" %}
{% block title %}Edit {{ entry.date }} — Driftnote{% endblock %}
{% block content %}
<form method="post" action="/entry/{{ entry.date }}" class="entry-edit">
  <h1>Edit {{ entry.date }}</h1>
  <label>Mood (one emoji)
    <input name="mood" value="{{ entry.mood or '' }}">
  </label>
  <label>Tags (comma-separated)
    <input name="tags" value="{{ tags_csv }}">
  </label>
  <label>Body (markdown)
    <textarea name="body" rows="14"
              hx-post="/preview" hx-target="#preview" hx-trigger="keyup changed delay:400ms">{{ entry.body_md }}</textarea>
  </label>
  <h2>Preview</h2>
  <div id="preview" class="preview">{{ initial_preview|safe }}</div>
  <p>
    <button type="submit">Save</button>
    <a href="/entry/{{ entry.date }}">Cancel</a>
  </p>
</form>
{% endblock %}
```

Key changes:
- Removed all inline `style=""` attributes (`width:100%` is now in CSS).
- `<input>` and `<textarea>` are children of their `<label>` — no `for=` needed, click-on-label-focuses works automatically. Cleaner and more accessible.
- Heading downgraded from `<h3>Preview</h3>` to `<h2>Preview</h2>` to match the spec's heading hierarchy (h2 is the section level).

- [ ] **Step 3: Run the edit-route tests**

```bash
uv run pytest tests/integration/test_web_routes_edit.py -v
```

Expected: green. The edit tests don't pin the heading level or inline styles.

- [ ] **Step 4: Commit**

```bash
git add src/driftnote/web/templates/entry_edit.html.j2
git commit -m "feat(web): clean up entry-edit markup for new theme"
```

(`entry.html.j2` is unchanged — its existing `<article class="entry">` element picks up the new `.entry` CSS rule with the accent stripe automatically.)

### Task 2.3: Update `admin.html.j2` for status dots and remove inline styles

**Files:**
- Modify: `src/driftnote/web/templates/admin.html.j2`
- Test: `tests/integration/test_web_routes_media_and_admin.py` (existing tests must still pass; one new assertion)

The admin template currently has eight inline `style=""` attributes and renders status as text. The new CSS expects:
- `.notice` instead of inline-styled `<p class="notice" style="...">`.
- `.test-controls` and `.test-controls .hint` instead of inline styles.
- A `.dot.dot-ok|warn|error` element before each card's status text.

We need a small mapping helper to turn a job's last status into a CSS class. The view function provides the cards; the template renders the dots.

- [ ] **Step 1: Add a status→dot-class mapping in `routes_admin.py`**

In `src/driftnote/web/routes_admin.py`, find where the `cards` list is built for the template context (the function that handles `GET /admin`). Each card already exposes `last_status` (one of `"ok"`, `"warn"`, `"error"`, or `None`).

Add a helper at module scope (near the top of the file, below the imports):

```python
def _dot_class_for_status(status: str | None) -> str:
    """Map a job's last status to a CSS class for the rendered dot."""
    if status == "ok":
        return "dot-ok"
    if status == "warn":
        return "dot-warn"
    if status == "error":
        return "dot-error"
    return "dot-ok"  # never-run jobs render a neutral green; the "(never)" text disambiguates
```

In the index handler, when building each card dict for the template, attach the class:

```python
card_dict = {
    "job": ...,
    "last_started_at": ...,
    "last_status": ...,
    "last_detail": ...,
    "last_success_at": ...,
    "failures_30d": ...,
    "dot_class": _dot_class_for_status(...last_status...),
}
```

(The exact card construction depends on what's already there. Read the surrounding code before editing — match its existing data shape and just add `"dot_class"` alongside.)

- [ ] **Step 2: Add a regression test for the dot class**

Append to `tests/integration/test_web_routes_media_and_admin.py`:

```python
def test_admin_renders_status_dot_class(setup: tuple[FastAPI, Engine, Path]) -> None:
    """Each job card includes a colored dot reflecting last_status."""
    fapp, eng, _ = setup
    with session_scope(eng) as session:
        rid = record_job_run(session, job="imap_poll", started_at="2026-05-06T08:00:00Z")
        finish_job_run(
            session,
            run_id=rid,
            finished_at="2026-05-06T08:00:01Z",
            status="error",
            error_kind="imap_auth",
        )
    r = TestClient(fapp).get("/admin")
    assert r.status_code == 200
    # The error dot appears in the imap_poll card.
    assert 'class="dot dot-error"' in r.text
```

- [ ] **Step 3: Run the test, confirm it fails**

```bash
uv run pytest tests/integration/test_web_routes_media_and_admin.py::test_admin_renders_status_dot_class -v
```

Expected: fails — template doesn't render a dot yet.

- [ ] **Step 4: Overwrite `admin.html.j2`**

Replace the file's contents with:

```jinja
{% extends "base.html.j2" %}
{% block title %}Admin — Driftnote{% endblock %}
{% block content %}
{% if notice %}
  <p class="notice">{{ notice }}</p>
{% endif %}
<h1>Admin</h1>
<section class="job-cards">
{% for card in cards %}
  <article class="card">
    <h2>{{ card.job }}</h2>
    <p>
      <span class="dot {{ card.dot_class }}"></span>
      Last: {{ card.last_started_at or "(never)" }} — {{ card.last_status or "—" }}{% if card.last_detail %} ({{ card.last_detail }}){% endif %}
    </p>
    <p>Last success: {{ card.last_success_at or "(never)" }}</p>
    <p>Failures (30d): {{ card.failures_30d }}</p>
    <a href="/admin/runs/{{ card.job }}">history</a>
  </article>
{% endfor %}
</section>

{% if dev_mode %}
  <section class="test-controls">
    <h2>Test controls (dev only)</h2>
    <p class="hint">
      Synchronously dispatches the listed scheduled job. The result lands in
      the corresponding card above (refresh after a couple of seconds).
    </p>
    <form method="post" action="/admin/test/send-prompt"><button>Send today's prompt</button></form>
    <form method="post" action="/admin/test/send-digest/weekly"><button>Send weekly digest</button></form>
    <form method="post" action="/admin/test/send-digest/monthly"><button>Send monthly digest</button></form>
    <form method="post" action="/admin/test/send-digest/yearly"><button>Send yearly digest</button></form>
    <form method="post" action="/admin/test/poll-now"><button>Poll responses now</button></form>
  </section>
{% endif %}

{% if recent_runs is defined %}
<h2>Runs for {{ job_filter }}</h2>
<table class="runs">
  <thead><tr><th>Started</th><th>Status</th><th>Detail</th><th>Error</th><th>Ack</th></tr></thead>
  <tbody>
  {% for r in recent_runs %}
    <tr class="status-{{ r.status }}">
      <td>{{ r.started_at }}</td>
      <td>{{ r.status }}</td>
      <td>{{ r.detail or "" }}</td>
      <td>{{ (r.error_kind or "") }} {{ (r.error_message or "") }}</td>
      <td>
        {% if r.status in ('error', 'warn') and not r.acknowledged_at %}
          <form method="post" action="/admin/runs/{{ r.id }}/ack" style="display:inline">
            <button>ack</button>
          </form>
        {% else %}
          {{ r.acknowledged_at or "" }}
        {% endif %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

Key changes:
- Inline styles on the notice, test-controls, and form blocks are removed (CSS handles them).
- Each card's status `<p>` opens with `<span class="dot {{ card.dot_class }}"></span>`.
- One inline `style="display:inline"` remains on the inline ack form. Keeping it: this is the canonical case for inline form-display, the alternative is a single-use class. (Spec's "remove inline styles" rule is not absolute — see the spec's tag-size decision for precedent.)

- [ ] **Step 5: Run the admin test suite, confirm everything passes**

```bash
uv run pytest tests/integration/test_web_routes_media_and_admin.py -v
```

Expected: all 8 tests pass (the 7 existing + the new dot test).

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/web/routes_admin.py src/driftnote/web/templates/admin.html.j2 tests/integration/test_web_routes_media_and_admin.py
git commit -m "feat(admin): render status dots, remove inline styles"
```

### Task 2.4: Clean up `search.html.j2` and `tags.html.j2`

**Files:**
- Modify: `src/driftnote/web/templates/search.html.j2`
- Modify: `src/driftnote/web/templates/tags.html.j2`

- [ ] **Step 1: Overwrite `search.html.j2`**

Replace its contents with:

```jinja
{% extends "base.html.j2" %}
{% block title %}Search — Driftnote{% endblock %}
{% block content %}
<h1>Search</h1>
<form method="get" action="/search" class="search-form">
  <input type="search" name="q" value="{{ q or '' }}" placeholder="quick brown fox" autofocus>
  <button>Search</button>
</form>
{% if error %}
  <p class="banner banner-warn">{{ error }}</p>
{% endif %}
<ul class="search-results">
  {% for e in results %}
    <li><a href="/entry/{{ e.date }}">{{ e.date }} {{ e.mood or "" }}</a> — {{ e.body_text|truncate(160) }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

Changes: form now has `class="search-form"`, error block reuses the standard `.banner.banner-warn` instead of an inline-styled `<p class="banner-warn" style="...">`.

- [ ] **Step 2: Overwrite `tags.html.j2`**

Replace its contents with:

```jinja
{% extends "base.html.j2" %}
{% block title %}Tags — Driftnote{% endblock %}
{% block content %}
<h1>Tags</h1>
<ul class="tag-cloud">
  {% for tag, count in tags %}
    <li><a href="/?tag={{ tag }}" style="font-size:{{ 0.8 + (count*0.1) }}rem">#{{ tag }} ({{ count }})</a></li>
  {% endfor %}
</ul>
{% endblock %}
```

Unchanged from current (the dynamic font-size scalar is the canonical use case for inline `style=`, per the spec). The new `.tag-cloud a` CSS rule (background, padding, no rounding) applies on top.

- [ ] **Step 3: Run the browse + edit suites to catch any regressions**

```bash
uv run pytest tests/integration/test_web_routes_browse.py tests/integration/test_web_routes_edit.py -v
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add src/driftnote/web/templates/search.html.j2 src/driftnote/web/templates/tags.html.j2
git commit -m "feat(web): clean up search/tags templates for new theme"
```

### Task 2.5: Audit the stylesheet against spec invariants

**Files:**
- Read-only: `src/driftnote/web/static/style.css`

This is a verification task — no code changes if the audit passes.

- [ ] **Step 1: Verify the palette block is the first rule and uses the spec's exact hex values**

```bash
grep -E "^\s+--(bg|bg-raised|bg-hover|fg|fg-muted|fg-dim|accent|accent-hover|border|warn-bg|warn-fg|error-bg|error-fg|ok|status-warn|status-error):" src/driftnote/web/static/style.css | wc -l
```

Expected: `16` (one line per palette variable).

```bash
head -1 src/driftnote/web/static/style.css
```

Expected: `:root {` — the palette block is the first rule in the file (spec acceptance criterion).

- [ ] **Step 2: Verify there is no `border-radius` outside the dot rule**

```bash
grep -n "border-radius" src/driftnote/web/static/style.css
```

Expected: exactly one match, on the line `border-radius: 50%;` inside the `.dot` block.

- [ ] **Step 3: Verify there are no `box-shadow` or `linear-gradient` declarations**

```bash
grep -nE "box-shadow|linear-gradient|radial-gradient" src/driftnote/web/static/style.css
```

Expected: empty (no matches).

- [ ] **Step 4: Verify the mobile media query exists**

```bash
grep -n "@media (max-width: 600px)" src/driftnote/web/static/style.css
```

Expected: exactly one match.

- [ ] **Step 5: Audit raw hex usage outside `:root`**

```bash
grep -nE '#[0-9a-fA-F]{3,6}' src/driftnote/web/static/style.css | grep -v ":root\|--bg\|--bg-raised\|--bg-hover\|--fg\|--fg-muted\|--fg-dim\|--accent\|--accent-hover\|--border\|--warn-bg\|--warn-fg\|--error-bg\|--error-fg\|--ok\|--status-warn\|--status-error"
```

Expected: empty. All non-`:root` rules reference the variables.

If any audit step fails, fix the stylesheet, re-commit with message `style(web): tighten palette/flat-rule audit`, and re-run the audits.

- [ ] **Step 6: No commit if audits passed; otherwise commit fixes**

(Audit steps are read-only when they pass.)

---

## Chunk 3: Email digest light-theme polish

The email digest is rendered server-side as inline-styled HTML. The redesign brings it to a coherent light palette that pairs visually with the web's purple accent (without sharing the dark-mode tokens).

### Task 3.1: Refactor `monthly.py` to use a module-level palette + render pad-cell day numbers

**Files:**
- Modify: `src/driftnote/digest/monthly.py`
- Test: `tests/unit/test_digest_monthly_render.py` (NEW)

- [ ] **Step 1: Write the new render test**

Create `tests/unit/test_digest_monthly_render.py`:

```python
"""Snapshot-style assertions for the monthly digest's polished light theme.

These tests don't compare against a committed HTML fixture (palette tweaks
should not require fixture refreshes). Instead we assert the digest contains
the spec's load-bearing palette tokens and renders pad-cell day numbers.
"""

from __future__ import annotations

from datetime import date

from driftnote.digest.inputs import DayInput
from driftnote.digest.monthly import build_monthly_digest


def _day(d: str, *, mood: str = "💪") -> DayInput:
    return DayInput(
        date=date.fromisoformat(d),
        mood=mood,
        tags=[],
        photo_thumb=None,
        body_html="<p>body</p>",
    )


def test_digest_uses_polished_light_palette() -> None:
    digest = build_monthly_digest(
        year=2026, month=5, days=[_day("2026-05-15")], web_base_url="https://x"
    )
    # Accent (deeper purple, readable on white).
    assert "#6c4fc4" in digest.html
    # Pad-cell muted text colour.
    assert "#c4c2cc" in digest.html


def test_digest_grid_has_six_rows_with_pad_day_numbers() -> None:
    """May 2026 starts Friday → April 27..30 are pad days at the start. June 1..7
    occupy the trailing pad row (always six rows total)."""
    digest = build_monthly_digest(
        year=2026, month=5, days=[_day("2026-05-15")], web_base_url="https://x"
    )
    # Six body rows.
    assert digest.html.count("<tr>") == 6
    # Pad cells render their actual day number.
    assert ">30<" in digest.html
    assert ">1<" in digest.html  # June 1 in the trailing row
```

- [ ] **Step 2: Run the test, confirm both fail**

```bash
uv run pytest tests/unit/test_digest_monthly_render.py -v
```

Expected: both fail. The first fails because `#6c4fc4` is not in the digest HTML today (the digest uses the old `#222`/`#888`/`#ccc` literals); the second fails because the current digest doesn't render pad-cell day numbers.

- [ ] **Step 3: Replace `monthly.py` with the polished version**

Overwrite `src/driftnote/digest/monthly.py`:

```python
"""Monthly digest builder.

Subject: `[Driftnote] Month YYYY` (e.g. "[Driftnote] May 2026")
Body:
- Calendar-grid moodboard.
- Stats line: count of entries, top mood, top tags.
- Up to 6 highlight days, target minimum 4. Selection is progressive:
  1) days with a photo AND at least one rare tag (used <3x this month);
  2) days with photo OR rare tag;
  3) days with the most photos (proxied by photo_thumb being non-null).
- Link to web UI.
"""

from __future__ import annotations

import re
from collections import Counter
from html import escape

from driftnote.digest.inputs import DayInput, HighlightInput
from driftnote.digest.moodboard import MonthlyCell, monthly_moodboard_grid
from driftnote.digest.weekly import Digest

_MONTH_NAMES = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# Polished light palette for the email digest. Intentionally not shared with
# the web UI's dark CSS variables — emails inline their styles and live in
# light-default inboxes (Gmail, Apple Mail). Visual coherence comes from the
# shared accent family (purple), not from shared tokens. See
# docs/superpowers/specs/2026-05-09-issue-4-dark-redesign-design.md.
_DIGEST_PALETTE: dict[str, str] = {
    "bg":        "#ffffff",
    "bg_raised": "#f7f6fb",
    "fg":        "#1f1d2b",
    "fg_muted":  "#6c6a78",
    "fg_dim":    "#c4c2cc",
    "accent":    "#6c4fc4",
    "border":    "#e5e4ed",
}


def select_highlights(days: list[DayInput], *, target: int = 4) -> list[HighlightInput]:
    if not days:
        return []
    tag_counts: Counter[str] = Counter()
    for d in days:
        tag_counts.update(d.tags)
    rare_tags = {t for t, c in tag_counts.items() if c < 3}

    def _has_photo(d: DayInput) -> bool:
        return d.photo_thumb is not None

    def _has_rare_tag(d: DayInput) -> bool:
        return any(t in rare_tags for t in d.tags)

    pass1 = [d for d in days if _has_photo(d) and _has_rare_tag(d)]
    if len(pass1) >= target:
        chosen = pass1
    else:
        pass2 = [d for d in days if _has_photo(d) or _has_rare_tag(d)]
        if len(pass2) >= target:
            chosen = pass2
        else:
            with_photo = [d for d in days if _has_photo(d)]
            chosen = with_photo if with_photo else days

    chosen = sorted(chosen, key=lambda d: d.date)[:target]
    return [
        HighlightInput(
            date=d.date,
            mood=d.mood,
            summary_html=_first_n_sentences(d.body_html, 2),
            photo_thumb=d.photo_thumb,
        )
        for d in chosen
    ]


def build_monthly_digest(
    *,
    year: int,
    month: int,
    days: list[DayInput],
    web_base_url: str,
) -> Digest:
    p = _DIGEST_PALETTE
    name = _MONTH_NAMES[month]
    subject = f"[Driftnote] {name} {year}"

    cells = monthly_moodboard_grid(year=year, month=month, days=days)
    grid_html = "".join(_row_html(row) for row in cells)

    moods: Counter[str] = Counter(d.mood for d in days if d.mood)
    tags: Counter[str] = Counter(t for d in days for t in d.tags)
    top_mood = moods.most_common(1)
    top_tags = tags.most_common(3)
    stats_html = (
        f"<p><strong>Stats:</strong> {len(days)} entries"
        + (f" • top emoji {escape(top_mood[0][0])} ({top_mood[0][1]})" if top_mood else "")
        + (" • top tags " + ", ".join(f"#{escape(t)}" for t, _ in top_tags) if top_tags else "")
        + "</p>"
    )

    highlights_html = "".join(
        _render_highlight(h, web_base_url=web_base_url) for h in select_highlights(days)
    )

    body_html = (
        f"<html><body style=\"font-family:system-ui,sans-serif;max-width:640px;margin:auto;"
        f"padding:16px;background:{p['bg']};color:{p['fg']}\">\n"
        f"  <h1 style=\"font-size:24px;font-weight:600;margin:0 0 12px\">{escape(name)} {year}</h1>\n"
        f"  <table cellspacing=\"0\" cellpadding=\"2\" "
        f"style=\"border-collapse:collapse;margin:8px 0 16px;background:{p['bg_raised']}\">\n"
        f"    {grid_html}\n"
        f"  </table>\n"
        f"  {stats_html}\n"
        f"  {highlights_html}\n"
        f"  <p style=\"margin-top:24px\"><a href=\"{escape(web_base_url)}\" "
        f"style=\"color:{p['accent']};text-decoration:none\">Open in Driftnote</a></p>\n"
        f"</body></html>"
    )
    return Digest(subject=subject, html=body_html)


def _row_html(row: list[MonthlyCell]) -> str:
    p = _DIGEST_PALETTE
    return (
        "<tr>"
        + "".join(
            f"<td style=\"text-align:center;width:32px;height:32px;font-size:18px;"
            f"color:{p['fg'] if c.in_month else p['fg_dim']}\">"
            f"<div style=\"font-size:10px;color:{p['fg_muted'] if c.in_month else p['fg_dim']}\">"
            f"{c.day_of_month}"
            f"</div>"
            f"<div>{escape(c.emoji or ('·' if c.in_month else ''))}</div>"
            f"</td>"
            for c in row
        )
        + "</tr>"
    )


def _render_highlight(h: HighlightInput, *, web_base_url: str) -> str:
    p = _DIGEST_PALETTE
    thumb_html = (
        f"<img src=\"{escape(h.photo_thumb)}\" style=\"max-width:100%\"/>"
        if h.photo_thumb
        else ""
    )
    return (
        f"<section style=\"margin:16px 0;padding:12px 0 0 16px;"
        f"border-top:1px solid {p['border']};border-left:4px solid {p['accent']}\">"
        f"<h3 style=\"margin:0;font-size:16px\">"
        f"<a href=\"{escape(web_base_url)}/entry/{escape(h.date.isoformat())}\" "
        f"style=\"color:{p['fg']};text-decoration:none\">"
        f"{escape(h.date.isoformat())} <span style=\"font-size:20px\">{escape(h.mood or '')}</span>"
        f"</a></h3>"
        f"{h.summary_html}"
        f"{thumb_html}"
        f"</section>"
    )


def _first_n_sentences(html: str, n: int) -> str:
    """Naive sentence trim: split on `. `, take first n, retain HTML wrapper."""
    text = re.sub(r"<[^>]+>", "", html).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    snippet = " ".join(parts[:n])
    return f"<p>{escape(snippet)}</p>"
```

Key changes vs. the current version:
- New `_DIGEST_PALETTE` module constant. All inline color literals reference it.
- `_row_html` renders each cell as a stacked `<div>` pair: top div is the day number (10px font, muted color), bottom div is the emoji or `·` fallback. Pad cells get the dim foreground/muted color and an empty emoji div.
- `_render_highlight` adds a 4px accent border-left to mirror the web UI's entry-view stripe.
- Photo `border-radius:8px` is removed (flat aesthetic).
- The "Open in Driftnote" link uses the polished accent (`#6c4fc4`) instead of `#888`.

- [ ] **Step 4: Run the new render tests, confirm they pass**

```bash
uv run pytest tests/unit/test_digest_monthly_render.py -v
```

Expected: both pass.

- [ ] **Step 5: Run all monthly digest tests to make sure existing assertions still hold**

```bash
uv run pytest tests/unit/test_digest_monthly.py tests/unit/test_digest_monthly_render.py -v
```

Expected: green. The existing tests in `test_digest_monthly.py` only assert on emoji/stats/subject content — none of those changed.

- [ ] **Step 6: Run the integration digest test (greenmail send)**

```bash
uv run pytest tests/integration/test_digest_jobs.py::test_monthly_digest_sends -v
```

Expected: green. The send pipeline doesn't pin colour values; it asserts the email landed.

- [ ] **Step 7: Audit `monthly.py` for residual hardcoded literals**

```bash
grep -nE '#(222|888|ccc|eee|fafafa|f5c542|e74c3c|fff8e0|fdecea)' src/driftnote/digest/monthly.py
```

Expected: empty. The only allowed colour tokens in the file are the values inside the `_DIGEST_PALETTE` dict literal at the top.

If anything matches, the rewrite missed a literal — fix the source to reference `_DIGEST_PALETTE` and re-run.

- [ ] **Step 8: Commit**

```bash
git add src/driftnote/digest/monthly.py tests/unit/test_digest_monthly_render.py
git commit -m "feat(digest): polish monthly digest with light-theme palette + pad-cell day numbers"
```

---

## Chunk 4: Final verification

### Task 4.1: Run the full fast suite

- [ ] **Step 1: Run unit + integration (excluding live/slow)**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: all green. If anything fails, the most likely cause is a stale assertion in a test you didn't anticipate; fix in place and recommit with `test: update assertion for new dark theme`.

### Task 4.2: Manual visual smoke test

This step is required by the spec acceptance criteria ("PR description contains screenshots") and cannot be automated.

- [ ] **Step 1: Start the dev server**

```bash
uv run python -m driftnote.cli serve --reload
```

(If a different invocation is canonical for the project, use that. The point is to render the templates against the new stylesheet.)

- [ ] **Step 2: Open each page in a browser at desktop width (>= 960px)**

- `http://localhost:8000/?year=2026&month=5` — calendar must show 6 rows, pad cells dimmed with day numbers, today's cell outlined in purple.
- `http://localhost:8000/entry/2026-05-06` — accent stripe on left of article, no rounded corners on photo thumbnails.
- `http://localhost:8000/entry/2026-05-06/edit` — textarea distinct from preview block (different backgrounds, accent stripe on preview).
- `http://localhost:8000/admin` — cards in a grid, status dots colored, test-controls block in dark amber.
- `http://localhost:8000/search` — input fits on one line, results list has gap between items.
- `http://localhost:8000/tags` — flat purple-tinted pills.

Capture a screenshot of each.

- [ ] **Step 3: Resize the browser to 360px (mobile)**

Reload the calendar. Weekday header must be hidden, cells must fit on the viewport without horizontal scroll. Capture a mobile screenshot.

- [ ] **Step 4: Trigger a monthly digest send and inspect the email**

If the dev environment has the test-control button (it should, with `DRIFTNOTE_ENVIRONMENT=dev`), click "Send monthly digest". Open the resulting email in Gmail (or whichever client is configured as `recipient`). Verify:
- Calendar shows 6 rows with pad-cell day numbers in muted gray.
- The "Open in Driftnote" link is purple.
- Each highlight section has a left accent stripe.

Capture an email screenshot.

- [ ] **Step 5: Push the branch and open a PR**

```bash
git push -u origin feat/issue-4-dark-redesign
gh pr create --title "feat: dark-mode UI redesign + complete calendar grid (#4)" --body "$(cat <<'EOF'
## Summary

Closes #4.

- Flat dark theme across the web UI driven by CSS custom properties at the top of `style.css`.
- Calendar always renders 6 rows; prev/next-month pad cells show their day number in `--fg-dim`.
- Today's cell outlined in purple accent.
- Tag cloud, entry view, edit view, admin re-themed; admin status indicators are now coloured dots.
- Mobile (<600px) hides the calendar weekday header and shrinks cell padding.
- Monthly email digest gets a parallel light-theme polish with a module-level palette constant; pad cells render day numbers in the email too.

## Screenshots

- Calendar (desktop): [paste]
- Calendar (mobile, 360px): [paste]
- Entry view: [paste]
- Edit view: [paste]
- Admin: [paste]
- Monthly digest email: [paste]

## Test plan
- [x] `uv run pytest -q -m "not live and not slow"`
- [x] Calendar renders 6 rows with pad day numbers (browse integration test)
- [x] Admin renders a `dot dot-error` for an errored job (admin integration test)
- [x] Monthly digest contains `#6c4fc4` accent and `#c4c2cc` pad-cell colour (new render test)
- [x] Manual visual check at desktop + mobile widths
- [x] Manual digest email check in real inbox

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After the PR is open, populate the screenshot placeholders in the PR description with the screenshots captured in steps 2-4.

---

## Out of scope (reminders for the implementer)

- Light/dark toggle. Single dark theme.
- Per-user theming.
- Tag-as-link wiring (#9), word cloud (#10), calendar photo thumbnails (#11) — they layer on top of this PR but ship separately.
- Visual regression snapshot tooling. Screenshots are in the PR description, not committed to the repo.
