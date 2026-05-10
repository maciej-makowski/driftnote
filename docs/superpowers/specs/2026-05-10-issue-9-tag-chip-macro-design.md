# `tag_chip` macro + tag chips on search results

> Design spec for [issue #9](https://github.com/maciej-makowski/driftnote/issues/9).

## Goal

Render `#tag` consistently as a chip-link everywhere it appears, and surface tag chips on search-result rows (currently bare). Drive all tag-chip rendering through a single Jinja macro so adding new surfaces (and #10's word cloud later) doesn't drift.

## Scope

**In scope:**
- New Jinja macro `tag_chip(tag, count=none, size_rem=none)` in `src/driftnote/web/templates/_macros.html.j2`.
- Three call sites updated to use the macro: entry detail, tags page, search results.
- Search route enriches results with their tags via a new repository helper `tags_for_dates`.
- CSS consolidation: drop context-specific tag selectors (`.entry .tags a`, `.tag-cloud a`) and replace with one `.tag-chip` rule.

**Out of scope (decided in brainstorming):**
- Calendar-cell tag indicator (badge or tooltip) — not adding clutter to 56px cells.
- Edit-form chip preview above the CSV input — duplicates the input's value with stale-state risk.
- Tag autocomplete in the edit form.
- Tag-management features (rename, merge, delete) — separate issue if ever wanted.

## The macro

`src/driftnote/web/templates/_macros.html.j2` (new):

```jinja
{% macro tag_chip(tag, count=none, size_rem=none) %}
<a href="/?tag={{ tag }}" class="tag-chip"{% if size_rem %} style="font-size: {{ size_rem }}rem"{% endif %}>#{{ tag }}{% if count is not none %} ({{ count }}){% endif %}</a>
{%- endmacro %}
```

Three callers:

- `entry.html.j2` — `{{ tag_chip(t) }}` per tag in the existing `<p class="tags">` block.
- `tags.html.j2` — `{{ tag_chip(tag, count=count, size_rem=0.8 + count*0.1) }}`. The dynamic per-tag font-size (frequency-based cloud sizing) is the canonical legitimate use of inline `style=`; the macro encapsulates it.
- `search.html.j2` — `{{ tag_chip(t) }}` per tag, after the result's date/mood line.

Imported with `{% from "_macros.html.j2" import tag_chip %}` at the top of each calling template (bare name; reads cleanly for a single-symbol import; standardised across all three templates).

## Repository helper

`src/driftnote/repository/entries.py`:

```python
def tags_for_dates(session: Session, dates: list[str]) -> dict[str, list[str]]:
    """Return {date: [tag, ...]} for each date in `dates`. Dates with no tags
    are absent from the result. Single SQL query — no N+1."""
    if not dates:
        return {}
    stmt = select(Tag).where(Tag.date.in_(dates)).order_by(Tag.date, Tag.tag)
    out: dict[str, list[str]] = {}
    for tag in session.scalars(stmt):
        out.setdefault(tag.date, []).append(tag.tag)
    return out
```

Naming aligns with the existing `tags_by_date_in_range` (which takes a range, not a list of dates) — different shape, separate helper. Style matches: `select(Tag)` + `session.scalars(...)` + iterate ORM instances, mirroring the surrounding code.

## Search route change

`src/driftnote/web/routes_browse.py::search_view`:

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
    rendered = templates.TemplateResponse(
        request,
        "search.html.j2",
        _ctx(q=q, results=results, error=error, tags_by_date=tags_by_date),
    )
    rendered.headers["Cache-Control"] = "no-store"
    return rendered
```

The `Cache-Control: no-store` was added in PR #28; it stays.

## Search template change

`src/driftnote/web/templates/search.html.j2`:

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

## CSS consolidation

`src/driftnote/web/static/style.css` — drop the per-context selectors `.entry .tags a` and `.tag-cloud a` (and their hovers). Add one canonical rule:

```css
.tag-chip {
  background: var(--bg-raised);
  color: var(--fg-muted);
  padding: 2px 8px;
  font-size: 13px;
  margin-right: 6px;
}
.tag-chip:hover { background: var(--bg-hover); color: var(--accent); }
```

The tag cloud (`.tag-cloud`) keeps its `display: flex; flex-wrap: wrap; gap: 8px` layout rule; only the per-link styling moves into `.tag-chip`. Dynamic font-size from frequency stays as the inline `style=` produced by the macro.

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/templates/_macros.html.j2` | New — single macro |
| `src/driftnote/web/templates/entry.html.j2` | Import + use macro for the inline tag list |
| `src/driftnote/web/templates/tags.html.j2` | Import + use macro; pass `count` + `size_rem` |
| `src/driftnote/web/templates/search.html.j2` | Import + use macro; render chips per result row |
| `src/driftnote/web/routes_browse.py` | `search_view` fetches `tags_by_date` from new helper |
| `src/driftnote/repository/entries.py` | New `tags_for_dates(session, dates)` helper |
| `src/driftnote/web/static/style.css` | Drop `.entry .tags a` + `.tag-cloud a`; add `.tag-chip` |
| `tests/unit/test_repository_entries.py` (or similar) | Cover empty list, mixed-tag dates, no-tag dates |
| `tests/integration/test_web_routes_browse.py` | Search response renders tag chips for tagged hits |

## Acceptance criteria

- [ ] All tag-chip rendering goes through the `tag_chip` macro; no inline `<a href="/?tag=...">#...</a>` anywhere except the macro itself.
- [ ] `tags_for_dates([])` returns `{}` without hitting the DB.
- [ ] `tags_for_dates(["2026-05-06", "2026-05-15"])` returns one query with `WHERE date IN (...)` and the dict shape `{date: [tag, ...]}`.
- [ ] Search results that match a tagged entry render that entry's chips, each link going to `/?tag=<tag>`.
- [ ] Tag cloud still scales font-size by frequency.
- [ ] Existing entry-detail and tags-page integration tests pass unchanged (markup is equivalent).
- [ ] No raw `#hex` colors outside `:root` (existing stylesheet invariant).

## Risks

**Risk:** CSS consolidation drops two existing selectors. If anything else in the codebase or tests asserts on `.entry .tags a` or `.tag-cloud a`, it will break.
**Mitigation:** Repo-wide grep before deletion. Existing integration tests assert on URL strings (`/?tag=...`) and tag text presence, not CSS selectors — confirmed by reading the test files.

**Risk:** The macro changes whitespace around the `<a>` element compared to the current inline form, breaking tests that pin exact HTML.
**Mitigation:** The current entry-page tests check for `/?tag=` substring presence, not exact whitespace. The new search test should follow the same pattern.

**Risk:** `tags_for_dates` over-permissive — `Tag.date.in_(dates)` with a huge `dates` list could exceed SQLite's expression depth limit.
**Mitigation:** Search results are FTS-bounded and small (current `search_fts` returns at most O(matches), which is tens for typical journal corpora). If the limit ever becomes a concern, batching is straightforward — not a real risk at journal scale.
