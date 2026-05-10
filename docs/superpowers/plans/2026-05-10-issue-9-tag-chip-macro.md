# Issue #9 — `tag_chip` macro + tag chips on search results

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render `#tag` consistently as a chip-link everywhere it appears via a single Jinja macro, and surface tag chips on search-result rows (currently bare).

**Architecture:** A new `_macros.html.j2` Jinja partial holds the `tag_chip(tag, count=none, size_rem=none)` macro. Three templates (entry detail, tags page, search results) import it. A new `tags_for_dates(session, dates)` repository helper enables the search route to enrich result rows with their tags in one query. CSS rules `.entry .tags a` and `.tag-cloud a` consolidate into a single `.tag-chip` rule.

**Tech Stack:** Python 3.14, FastAPI, Jinja2, SQLAlchemy 2.0, plain CSS, pytest, ruff.

**Spec:** [docs/superpowers/specs/2026-05-10-issue-9-tag-chip-macro-design.md](../specs/2026-05-10-issue-9-tag-chip-macro-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/9

**Branch:** `feat/issue-9-tag-chip-macro` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-9/`)

---

## Working notes for the implementer

- All paths in this plan are relative to the repo root (the worktree).
- Tests run via `uv run pytest`. The fast suite excludes `live`/`slow` markers and runs as a pre-commit hook.
- `from __future__ import annotations` everywhere.
- Pre-commit hooks: ruff lint+format, fast unit suite. If a hook fails, fix the cause and create a NEW commit (never `--amend`).
- The `_no_store` helper in `routes_browse.py` is already applied to the search-view response — don't remove it.

---

## Chunk 1: Backend — `tags_for_dates` helper (TDD)

### Task 1.1: Add `tags_for_dates` to the entries repository

**Files:**
- Modify: `src/driftnote/repository/entries.py`
- Modify: `tests/unit/test_repository_entries.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/unit/test_repository_entries.py`. The file already imports the `engine` fixture, `session_scope`, `upsert_entry`, `replace_tags`, and `EntryRecord`. Add `tags_for_dates` to the existing import block (alphabetical position next to `tags_by_date_in_range`). Then append:

```python
def test_tags_for_dates_empty_input_returns_empty_dict(engine: Engine) -> None:
    """An empty list short-circuits to {} without hitting the DB."""
    with session_scope(engine) as session:
        result = tags_for_dates(session, [])
    assert result == {}


def test_tags_for_dates_returns_one_entry_per_listed_date(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-06"))
        upsert_entry(session, _record(date="2026-05-08"))
        upsert_entry(session, _record(date="2026-05-10"))
        replace_tags(session, "2026-05-06", ["work", "cooking"])
        replace_tags(session, "2026-05-08", ["holiday"])
        replace_tags(session, "2026-05-10", ["work", "rest"])
    with session_scope(engine) as session:
        result = tags_for_dates(session, ["2026-05-06", "2026-05-10"])
    # Only the listed dates appear; tags are sorted within each date.
    assert result == {
        "2026-05-06": ["cooking", "work"],
        "2026-05-10": ["rest", "work"],
    }


def test_tags_for_dates_omits_dates_with_no_tags(engine: Engine) -> None:
    with session_scope(engine) as session:
        upsert_entry(session, _record(date="2026-05-06"))
        upsert_entry(session, _record(date="2026-05-08"))
        replace_tags(session, "2026-05-06", ["work"])
    with session_scope(engine) as session:
        result = tags_for_dates(session, ["2026-05-06", "2026-05-08", "2026-05-09"])
    # 2026-05-08 has no tags; 2026-05-09 has no entry. Both absent.
    assert result == {"2026-05-06": ["work"]}
```

- [ ] **Step 2: Run the new tests, confirm `ImportError` on the missing symbol**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-9
uv run pytest tests/unit/test_repository_entries.py::test_tags_for_dates_empty_input_returns_empty_dict -v
```

Expected: collection error — `cannot import name 'tags_for_dates' from 'driftnote.repository.entries'`.

- [ ] **Step 3: Implement the helper**

In `src/driftnote/repository/entries.py`, append after `tags_by_date_in_range` (which is currently the last function in the file, ending around line 150):

```python
def tags_for_dates(session: Session, dates: list[str]) -> dict[str, list[str]]:
    """Return tag lists keyed by date, for each date in `dates`.

    Dates with no tags (or no entry at all) are absent from the result.
    Empty input short-circuits to {} without a DB query.
    """
    if not dates:
        return {}
    stmt = select(Tag).where(Tag.date.in_(dates)).order_by(Tag.date, Tag.tag)
    out: dict[str, list[str]] = {}
    for tag in session.scalars(stmt):
        out.setdefault(tag.date, []).append(tag.tag)
    return out
```

The signature matches `tags_by_date_in_range`'s style: `select(Tag)` + `session.scalars(...)` + iterate ORM instances; `dict[str, list[str]]` return; ordered tags within each date.

- [ ] **Step 4: Run all three new tests, confirm pass**

```bash
uv run pytest tests/unit/test_repository_entries.py -v -k tags_for_dates
```

Expected: 3 passed.

- [ ] **Step 5: Run the full unit suite**

```bash
uv run pytest tests/unit -q -m "not live and not slow"
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/repository/entries.py tests/unit/test_repository_entries.py
git commit -m "feat(repository): add tags_for_dates helper for explicit-date lookups"
```

---

## Chunk 2: Macro + adopt in entry/tags templates

### Task 2.1: Create `_macros.html.j2`

**Files:**
- Create: `src/driftnote/web/templates/_macros.html.j2`

- [ ] **Step 1: Write the macro**

Create `src/driftnote/web/templates/_macros.html.j2` with this exact content:

```jinja
{# Shared template macros. Import via `{% from "_macros.html.j2" import tag_chip %}` #}

{%- macro tag_chip(tag, count=none, size_rem=none) -%}
<a href="/?tag={{ tag }}" class="tag-chip"{% if size_rem %} style="font-size: {{ size_rem }}rem"{% endif %}>#{{ tag }}{% if count is not none %} ({{ count }}){% endif %}</a>
{%- endmacro %}
```

The `{%-` and `-%}` strip whitespace around the macro definition itself; the macro body emits a single `<a>` tag with no surrounding whitespace, so callers can place chips inline without extra spaces.

(No test step yet — the macro is exercised by the template integration tests in subsequent tasks.)

### Task 2.2: Adopt the macro in `entry.html.j2`

**Files:**
- Modify: `src/driftnote/web/templates/entry.html.j2`
- Tests already cover entry-page rendering (`tests/integration/test_web_routes_browse.py::test_entry_page_renders_markdown`).

- [ ] **Step 1: Replace the inline tag link with the macro**

Open `src/driftnote/web/templates/entry.html.j2`. Find the line:

```jinja
<p class="tags">{% for t in tags %}<a href="/?tag={{ t }}">#{{ t }}</a>{% endfor %}</p>
```

Replace the file contents with:

```jinja
{% extends "base.html.j2" %}
{% from "_macros.html.j2" import tag_chip %}
{% block title %}{{ entry.date }} — Driftnote{% endblock %}
{% block content %}
<article class="entry">
  <h1>{{ entry.date }} {% if entry.mood %}<span class="mood">{{ entry.mood }}</span>{% endif %}</h1>
  <p class="tags">{% for t in tags %}{{ tag_chip(t) }}{% endfor %}</p>
  <div class="body">{{ body_html|safe }}</div>
  <section class="media">
    {% for m in media if m.kind == "photo" %}
      <a href="/media/{{ entry.date }}/web/{{ m.filename | replace('.heic', '.jpg') }}">
        <img src="/media/{{ entry.date }}/thumb/{{ m.filename | replace('.heic', '.jpg') }}" alt="">
      </a>
    {% endfor %}
    {% for m in media if m.kind == "video" %}
      <video controls preload="none" poster="/media/{{ entry.date }}/thumb/{{ m.filename | replace('.', '_') }}.jpg">
        <source src="/media/{{ entry.date }}/original/{{ m.filename }}">
      </video>
    {% endfor %}
  </section>
  <p><a href="/entry/{{ entry.date }}/edit">Edit</a></p>
</article>
{% endblock %}
```

- [ ] **Step 2: Run the entry-detail integration test**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_entry_page_renders_markdown -v
```

Expected: pass. The existing test asserts `#work` (or `work`) is in the response — the macro emits `#work` as the link text, so the assertion holds.

### Task 2.3: Adopt the macro in `tags.html.j2`

**Files:**
- Modify: `src/driftnote/web/templates/tags.html.j2`
- Tests: `tests/integration/test_web_routes_browse.py::test_tags_page_lists_tags`

- [ ] **Step 1: Replace inline link with macro call**

Replace `src/driftnote/web/templates/tags.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% from "_macros.html.j2" import tag_chip %}
{% block title %}Tags — Driftnote{% endblock %}
{% block content %}
<h1>Tags</h1>
<ul class="tag-cloud">
  {% for tag, count in tags %}
    <li>{{ tag_chip(tag, count=count, size_rem=0.8 + count * 0.1) }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 2: Run the tags-page integration test**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_tags_page_lists_tags -v
```

Expected: pass. The existing test asserts `work` and `cooking` appear in the response — the macro still emits the tag text inside the chip.

- [ ] **Step 3: Commit Tasks 2.1 + 2.2 + 2.3 together**

```bash
git add src/driftnote/web/templates/_macros.html.j2 \
        src/driftnote/web/templates/entry.html.j2 \
        src/driftnote/web/templates/tags.html.j2
git commit -m "feat(web): introduce tag_chip macro; adopt in entry + tags templates"
```

---

## Chunk 3: Search results — render tag chips per row

### Task 3.1: Add the failing integration test

**Files:**
- Modify: `tests/integration/test_web_routes_browse.py`

- [ ] **Step 1: Append the new test**

Append at the end of `tests/integration/test_web_routes_browse.py` (after the existing `test_entry_page_escapes_script_tags`):

```python
def test_search_results_render_tag_chips_per_hit(
    app_with_data: tuple[FastAPI, Engine],
) -> None:
    """Each search hit shows the entry's tags as clickable chips."""
    app, _ = app_with_data
    r = TestClient(app).get("/search?q=risotto")
    assert r.status_code == 200
    # The fixture's seeded entry has tags ["work", "cooking"]; both must
    # render as tag-chip links in the response.
    assert 'class="tag-chip"' in r.text
    assert 'href="/?tag=work"' in r.text
    assert 'href="/?tag=cooking"' in r.text
```

The fixture `app_with_data` (already at the top of the file) seeds entry `2026-05-06` with `tags=["work", "cooking"]` and FTS body containing `risotto`.

- [ ] **Step 2: Run the test, confirm it fails**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_search_results_render_tag_chips_per_hit -v
```

Expected: fail on `'class="tag-chip"' in r.text` (search.html.j2 doesn't render tags yet).

### Task 3.2: Wire `tags_for_dates` into the search route

**Files:**
- Modify: `src/driftnote/web/routes_browse.py`

- [ ] **Step 1: Import `tags_for_dates`**

In `src/driftnote/web/routes_browse.py`, find the existing import block:

```python
from driftnote.repository.entries import (
    EntryRecord,
    get_entry,
    list_entries_by_tag,
    list_entries_in_range,
    list_tags_for_date,
    search_fts,
    tag_frequencies_in_range,
)
```

Add `tags_for_dates` to the alphabetical position (after `tag_frequencies_in_range`):

```python
from driftnote.repository.entries import (
    EntryRecord,
    get_entry,
    list_entries_by_tag,
    list_entries_in_range,
    list_tags_for_date,
    search_fts,
    tag_frequencies_in_range,
    tags_for_dates,
)
```

- [ ] **Step 2: Update `search_view` to fetch tags**

In `routes_browse.py`, locate `search_view` (around line 145). Replace its body with:

```python
    @app.get("/search", response_class=HTMLResponse)
    async def search_view(request: Request, q: str | None = Query(None)) -> HTMLResponse:
        results: list[EntryRecord] = []
        tags_by_date: dict[str, list[str]] = {}
        error: str | None = None
        if q:
            try:
                with session_scope(engine) as session:
                    results = search_fts(session, q)
                    tags_by_date = tags_for_dates(session, [r.date for r in results])
            except OperationalError as exc:
                orig = getattr(exc, "orig", None)
                msg = orig.args[0] if orig and orig.args else str(exc)
                error = f"invalid search query: {msg}"
        return _no_store(
            templates.TemplateResponse(
                request,
                "search.html.j2",
                _ctx(q=q, results=results, error=error, tags_by_date=tags_by_date),
            )
        )
```

Note: `tags_by_date` is queried *inside* the same `session_scope` block as `results`, before the session closes — important because the EntryRecord items are detached from the session at that point. `tags_for_dates` returns plain dict/string data, not ORM instances, so it survives the session close.

### Task 3.3: Update `search.html.j2` to render the chips

**Files:**
- Modify: `src/driftnote/web/templates/search.html.j2`

- [ ] **Step 1: Replace the template**

Replace `src/driftnote/web/templates/search.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% from "_macros.html.j2" import tag_chip %}
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
    <li>
      <a href="/entry/{{ e.date }}">{{ e.date }} {{ e.mood or "" }}</a> — {{ e.body_text|truncate(160) }}
      {% set entry_tags = tags_by_date.get(e.date, []) %}
      {% if entry_tags %}
        <span class="result-tags">{% for t in entry_tags %}{{ tag_chip(t) }}{% endfor %}</span>
      {% endif %}
    </li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 2: Run the new test, confirm pass**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_search_results_render_tag_chips_per_hit -v
```

Expected: pass.

- [ ] **Step 3: Run the full browse integration suite**

```bash
uv run pytest tests/integration/test_web_routes_browse.py -v
```

Expected: all pass (existing search tests + the new one).

- [ ] **Step 4: Commit**

```bash
git add src/driftnote/web/routes_browse.py \
        src/driftnote/web/templates/search.html.j2 \
        tests/integration/test_web_routes_browse.py
git commit -m "feat(web): render tag chips on search-result rows"
```

---

## Chunk 4: CSS consolidation

### Task 4.1: Replace per-context tag rules with a single `.tag-chip` rule

**Files:**
- Modify: `src/driftnote/web/static/style.css`

- [ ] **Step 1: Drop the two per-context rules**

In `src/driftnote/web/static/style.css`, find these two blocks:

```css
.tag-cloud a {
  background: var(--bg-raised);
  color: var(--fg);
  padding: 2px 8px;
}
.tag-cloud a:hover { background: var(--bg-hover); color: var(--accent); }
```

and

```css
.entry .tags a {
  background: var(--bg-raised);
  color: var(--fg-muted);
  padding: 2px 8px;
  margin-right: 6px;
  font-size: 13px;
}
.entry .tags a:hover { background: var(--bg-hover); color: var(--accent); }
```

Replace BOTH with a single rule placed where `.tag-cloud a` currently lives (so the section comment "Tag cloud" still groups visually). Keep the surrounding `.tag-cloud` container rule untouched.

The replacement (single canonical rule):

```css
/* Tag chips (entry view, tags cloud, search results) */
.tag-chip {
  background: var(--bg-raised);
  color: var(--fg-muted);
  padding: 2px 8px;
  font-size: 13px;
  margin-right: 6px;
}
.tag-chip:hover { background: var(--bg-hover); color: var(--accent); }
```

The `.tag-cloud` flex layout rule (`list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px;`) MUST stay — it sets up the cloud container layout, which is still needed.

- [ ] **Step 2: Audit the change**

```bash
grep -nE "\.entry \.tags a|\.tag-cloud a" src/driftnote/web/static/style.css
```

Expected: empty (both old rules gone).

```bash
grep -n "\.tag-chip" src/driftnote/web/static/style.css
```

Expected: 2 lines (the rule and the :hover variant).

- [ ] **Step 3: Run the full integration suite**

```bash
uv run pytest tests/integration -q -m "not live and not slow"
```

Expected: green. CSS changes don't affect markup tests.

- [ ] **Step 4: Stylesheet invariants audit**

```bash
grep -n "border-radius" src/driftnote/web/static/style.css
```

Expected: 1 match (the `.dot` rule from PR #19's redesign — unchanged).

```bash
grep -nE "box-shadow|linear-gradient|radial-gradient" src/driftnote/web/static/style.css
```

Expected: empty.

```bash
grep -nE '#[0-9a-fA-F]{3,6}' src/driftnote/web/static/style.css | grep -vE '^\s*[0-9]+:\s+--'
```

Expected: empty (no raw hex outside `:root`).

- [ ] **Step 5: Commit**

```bash
git add src/driftnote/web/static/style.css
git commit -m "style(web): consolidate tag chip styling into single .tag-chip rule"
```

---

## Chunk 5: Final verification + PR

### Task 5.1: Full fast suite

- [ ] **Step 1: Run unit + integration (excluding live/slow)**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: all green. Test count delta from master baseline: +3 unit (`tags_for_dates` × 3) and +1 integration (`test_search_results_render_tag_chips_per_hit`).

### Task 5.2: Push + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin feat/issue-9-tag-chip-macro
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(web): tag_chip macro + tag chips on search results (#9)" --body "$(cat <<'EOF'
## Summary

Closes #9.

- New `tag_chip(tag, count=none, size_rem=none)` Jinja macro in `src/driftnote/web/templates/_macros.html.j2` — single source of truth for rendering `#tag` as a chip-link.
- Three call sites adopt it: entry detail, tags page (passes `count` + dynamic `size_rem` for the cloud), search results (new — previously bare).
- New `tags_for_dates(session, dates)` repository helper enables the search route to enrich result rows with their tags in one query (no N+1).
- CSS consolidation: `.entry .tags a` and `.tag-cloud a` rules merged into a single `.tag-chip` rule.

## Out of scope (decided in brainstorming)

- Calendar-cell tag indicator (badge/tooltip) — would clutter 56px cells.
- Edit-form chip preview above the CSV input — duplicates input value with stale-state risk.
- Tag autocomplete, rename/merge.

## Test plan

- [x] 3 unit tests for `tags_for_dates`: empty input, multi-date dict shape, dates-without-tags omitted
- [x] 1 integration test asserts search-result rows render `class="tag-chip"` chips with correct `/?tag=<tag>` hrefs
- [x] Existing entry-detail and tags-page integration tests pass unchanged (macro markup is equivalent)
- [x] Stylesheet audit clean: 1 `border-radius` (status dot), no box-shadow/gradient, no raw hex outside `:root`

## Spec + plan

- Spec: `docs/superpowers/specs/2026-05-10-issue-9-tag-chip-macro-design.md`
- Plan: `docs/superpowers/plans/2026-05-10-issue-9-tag-chip-macro.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
