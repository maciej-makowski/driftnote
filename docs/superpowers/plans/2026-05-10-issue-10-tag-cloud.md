# Issue #10 — Tag-cloud spiral layout

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat font-size-scaled tag list at `/tags` with a server-rendered word cloud — tags arranged spatially via an Archimedean spiral, with the largest tag at centre and smaller ones spiralling outward. Mobile (<600px) keeps the existing flat list as a fallback.

**Architecture:** A new `src/driftnote/web/cloud.py` module exposes `layout_cloud(tag_counts) -> list[CloudTag]`, a pure function packing tags onto a 600×400 canvas. The `tags_view` route calls it once and passes the result to the template alongside the existing flat-list data. CSS media queries swap visibility between canvas and flat list at the 600 px boundary.

**Tech Stack:** Python 3.14 (`math.sqrt`/`cos`/`sin`), FastAPI, Jinja2, plain CSS (no JS), pytest, ruff.

**Spec:** [docs/superpowers/specs/2026-05-10-issue-10-tag-cloud-design.md](../specs/2026-05-10-issue-10-tag-cloud-design.md)

**Issue:** https://github.com/maciej-makowski/driftnote/issues/10

**Branch:** `feat/issue-10-tag-cloud` (worktree at `/var/home/cfiet/Documents/Projects/driftnote-issue-10/`)

---

## Working notes for the implementer

- All paths in this plan are relative to the repo root (the worktree).
- Tests run via `uv run pytest`. Fast suite: `uv run pytest -q -m "not live and not slow"`. Pre-commit hooks run ruff + the fast unit suite on every commit.
- `from __future__ import annotations` everywhere.
- If a pre-commit hook fails, fix the cause and create a NEW commit (never `--amend`).
- The `_no_store` helper in `routes_browse.py` is already applied to `tags_view` — keep it.

---

## Chunk 1: Backend — `layout_cloud` (TDD)

### Task 1.1: Create `src/driftnote/web/cloud.py` and unit tests

**Files:**
- Create: `src/driftnote/web/cloud.py`
- Create: `tests/unit/test_web_cloud.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_web_cloud.py` with this exact content:

```python
"""Tests for the tag-cloud spiral layout."""

from __future__ import annotations

from driftnote.web.cloud import CloudTag, layout_cloud


def _bbox(t: CloudTag) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) using the same heuristic the algorithm uses."""
    bbox_w = int(t.font_size * 0.6 * (len(t.name) + 1))
    bbox_h = int(t.font_size * 1.2)
    return (t.x, t.y, bbox_w, bbox_h)


def test_layout_cloud_empty_input_returns_empty_list() -> None:
    assert layout_cloud({}) == []


def test_layout_cloud_largest_tag_lands_near_center() -> None:
    """Centerpiece (step=0, r=0) is placed with bbox-center at canvas-center.

    With r=0 the placement is exact modulo int truncation, so within 1 px.
    """
    cloud = layout_cloud({"work": 50, "rest": 5}, width=600, height=400)
    largest = next(t for t in cloud if t.name == "work")
    assert largest.placed
    cx, cy = 300, 200
    bbox_w = int(largest.font_size * 0.6 * (len("work") + 1))
    bbox_h = int(largest.font_size * 1.2)
    assert abs(largest.x + bbox_w // 2 - cx) <= 1
    assert abs(largest.y + bbox_h // 2 - cy) <= 1


def test_layout_cloud_placements_do_not_overlap() -> None:
    """Every pair of placed tags' bboxes is axis-aligned-disjoint."""
    counts = {f"tag{i}": 50 - i for i in range(20)}
    cloud = layout_cloud(counts)
    placed = [t for t in cloud if t.placed]
    assert len(placed) >= 1
    for i, a in enumerate(placed):
        ax, ay, aw, ah = _bbox(a)
        for b in placed[i + 1 :]:
            bx, by, bw, bh = _bbox(b)
            disjoint = (
                ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
            )
            assert disjoint, f"{a.name} overlaps {b.name}"


def test_layout_cloud_marks_unplaceable_tags() -> None:
    """A tiny canvas crammed with big tags forces some unplaced."""
    counts = {f"tag{i}": 100 for i in range(20)}
    cloud = layout_cloud(counts, width=100, height=100, max_steps=50)
    assert any(not t.placed for t in cloud)


def test_layout_cloud_font_sizes_clamped_to_range() -> None:
    cloud = layout_cloud({f"t{i}": i + 1 for i in range(10)}, min_font=10, max_font=24)
    for t in cloud:
        assert 10 <= t.font_size <= 24


def test_layout_cloud_identical_counts_all_at_max_font() -> None:
    """All-equal counts → sqrt(1.0) = 1 → every tag at max_font; ordering alphabetic."""
    cloud = layout_cloud({"banana": 5, "apple": 5, "cherry": 5}, min_font=12, max_font=36)
    assert [t.name for t in cloud] == ["apple", "banana", "cherry"]
    assert all(t.font_size == 36 for t in cloud)


def test_layout_cloud_returns_one_cloudtag_per_input() -> None:
    counts = {"a": 1, "b": 2, "c": 3}
    cloud = layout_cloud(counts)
    assert len(cloud) == 3
    assert {t.name for t in cloud} == {"a", "b", "c"}
```

- [ ] **Step 2: Run the tests, confirm `ImportError`**

```bash
cd /var/home/cfiet/Documents/Projects/driftnote-issue-10
uv run pytest tests/unit/test_web_cloud.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'driftnote.web.cloud'`.

- [ ] **Step 3: Implement `cloud.py`**

Create `src/driftnote/web/cloud.py` with this exact content:

```python
"""Server-side tag-cloud layout via Archimedean spiral.

Public API: `layout_cloud(tag_counts, ...)` returns a list of
`CloudTag` ready to be rendered as absolutely-positioned `<a>` elements.

Pure function — no I/O, deterministic for a given input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Public canvas dimensions — single source of truth shared with the
# tags_view route handler so handler/template/CSS stay in agreement.
DEFAULT_WIDTH = 600
DEFAULT_HEIGHT = 400

# Pixel margin added to every bounding box during collision testing only.
# Returned (x, y) are un-padded so the template can render `left:{{ x }}px`
# directly. The margin absorbs proportional-font width-estimation slop.
_BBOX_MARGIN = 4


@dataclass(frozen=True)
class CloudTag:
    name: str
    count: int
    x: int          # left-edge px (CSS-friendly), un-padded
    y: int          # top-edge px, un-padded
    font_size: int  # px
    placed: bool    # True if the spiral found a collision-free spot


def layout_cloud(
    tag_counts: dict[str, int],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    min_font: int = 12,
    max_font: int = 36,
    max_steps: int = 500,
) -> list[CloudTag]:
    """Pack tags onto a `width`×`height` canvas using an Archimedean spiral.

    Tags are sorted by count descending with alphabetical tie-break; the
    first (the most-used tag, or alphabetically-first if all counts are
    equal) is placed at the canvas centre. Subsequent tags spiral outwards
    until a collision-free spot is found or `max_steps` is exhausted.

    Returns one `CloudTag` per input tag, in placement order. Tags that
    couldn't be placed are returned with `placed=False` and (x, y) set to
    (0, 0); callers (and templates) should skip them.
    """
    if not tag_counts:
        return []

    sorted_tags = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    max_count = sorted_tags[0][1]
    cx = width // 2
    cy = height // 2

    placed: list[tuple[int, int, int, int]] = []  # padded bboxes for collision
    out: list[CloudTag] = []

    for name, count in sorted_tags:
        scale = math.sqrt(count / max_count)
        font_size = round(min_font + (max_font - min_font) * scale)
        bbox_w = int(font_size * 0.6 * (len(name) + 1))
        bbox_h = int(font_size * 1.2)

        spot: tuple[int, int] | None = None
        for step in range(max_steps):
            theta = step * 0.3
            r = step * 1.5
            x = int(cx + r * math.cos(theta) - bbox_w / 2)
            y = int(cy + r * math.sin(theta) - bbox_h / 2)
            if not _collides(x, y, bbox_w, bbox_h, placed):
                spot = (x, y)
                break

        if spot is None:
            out.append(CloudTag(name=name, count=count, x=0, y=0,
                                 font_size=font_size, placed=False))
        else:
            x, y = spot
            placed.append((
                x - _BBOX_MARGIN,
                y - _BBOX_MARGIN,
                bbox_w + 2 * _BBOX_MARGIN,
                bbox_h + 2 * _BBOX_MARGIN,
            ))
            out.append(CloudTag(name=name, count=count, x=x, y=y,
                                 font_size=font_size, placed=True))

    return out


def _collides(
    x: int, y: int, w: int, h: int, placed: list[tuple[int, int, int, int]]
) -> bool:
    """Axis-aligned bbox overlap check against every already-placed bbox.

    Each entry in `placed` is (x, y, w, h) of the PADDED bbox.
    """
    pad_x = x - _BBOX_MARGIN
    pad_y = y - _BBOX_MARGIN
    pad_w = w + 2 * _BBOX_MARGIN
    pad_h = h + 2 * _BBOX_MARGIN
    for px, py, pw, ph in placed:
        if (
            pad_x + pad_w > px
            and px + pw > pad_x
            and pad_y + pad_h > py
            and py + ph > pad_y
        ):
            return True
    return False
```

Notes for the implementer:
- The `_collides` helper takes the **un-padded** candidate (x, y, w, h) and pads them for the comparison; the `placed` list stores **already-padded** bboxes. This means each pair gets a 4 px gap around both sides — total 8 px between adjacent bboxes. That's intentional headroom; do not optimise.
- `math.sqrt`, `math.cos`, `math.sin` are imported via the `math` module rather than from-imports to keep the namespace tidy.
- The `placed=False` branch sets `(x, y) = (0, 0)` to satisfy the dataclass; the template gates rendering on `t.placed` so the (0, 0) value never reaches the page.

- [ ] **Step 4: Run the tests, confirm 7 pass**

```bash
uv run pytest tests/unit/test_web_cloud.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run the full unit suite**

```bash
uv run pytest tests/unit -q -m "not live and not slow"
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/driftnote/web/cloud.py tests/unit/test_web_cloud.py
git commit -m "feat(web): add layout_cloud — server-side spiral tag-cloud layout"
```

---

## Chunk 2: Wire into `tags_view` route

### Task 2.1: Update the handler + add a structlog logger

**Files:**
- Modify: `src/driftnote/web/routes_browse.py`

- [ ] **Step 1: Add the imports**

Open `src/driftnote/web/routes_browse.py`. The existing import block runs from line 3 to roughly line 30. Add:

1. `import structlog` as a new line in the third-party group, immediately after the existing `from sqlalchemy.exc import OperationalError` line (or wherever ruff prefers — the formatter will normalise on commit).
2. `from driftnote.web.cloud import DEFAULT_HEIGHT, DEFAULT_WIDTH, layout_cloud` after the existing `from driftnote.web.banners import compute_banners` import (alphabetical within the `driftnote.web` group).

Then immediately after the imports block, before `_TEMPLATES_DIR = ...`, add:

```python
log = structlog.get_logger(__name__)
```

This is the first structlog logger in this module. The existing `src/driftnote/logging.py` configures structlog at app startup; `get_logger(__name__)` picks up that configuration.

- [ ] **Step 2: Update `tags_view` to compute and pass the cloud**

Locate `tags_view` (around line 138 — the handler that renders `tags.html.j2`). Replace its body with:

```python
    @app.get("/tags", response_class=HTMLResponse)
    async def tags_view(request: Request) -> HTMLResponse:
        with session_scope(engine) as session:
            freq = tag_frequencies_in_range(session, "0001-01-01", "9999-12-31")
        cloud = layout_cloud(freq)
        unplaced = sum(1 for t in cloud if not t.placed)
        if unplaced:
            log.info("tag_cloud_unplaced", count=unplaced, total=len(cloud))
        ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
        return _no_store(
            templates.TemplateResponse(
                request,
                "tags.html.j2",
                _ctx(
                    tags=ranked,
                    cloud=cloud,
                    canvas_width=DEFAULT_WIDTH,
                    canvas_height=DEFAULT_HEIGHT,
                ),
            )
        )
```

- [ ] **Step 3: Run the tags-page integration test**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_tags_page_lists_tags -v
```

Expected: pass. The existing test just asserts the tag names appear in the response body. The cloud markup hasn't been added to the template yet, but the route returns 200 OK and the existing flat-list rendering is unchanged.

(No commit yet — Tasks 2.2 and 2.3 land in the same logical change.)

### Task 2.2: Update `tags.html.j2` to render canvas + fallback list

**Files:**
- Modify: `src/driftnote/web/templates/tags.html.j2`

- [ ] **Step 1: Replace the template**

Overwrite `src/driftnote/web/templates/tags.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% from "_macros.html.j2" import tag_chip %}
{% block title %}Tags — Driftnote{% endblock %}
{% block content %}
<h1>Tags</h1>
{% if cloud %}
<div class="tag-cloud-canvas" style="width:{{ canvas_width }}px;height:{{ canvas_height }}px">
  {% for t in cloud %}
    {% if t.placed %}
      <a href="/?tag={{ t.name }}" class="tag-chip cloud-chip" style="left:{{ t.x }}px;top:{{ t.y }}px;font-size:{{ t.font_size }}px">#{{ t.name }}</a>
    {% endif %}
  {% endfor %}
</div>
{% endif %}
<ul class="tag-cloud">
  {% for tag, count in tags %}
    <li>{{ tag_chip(tag, count=count, size_rem=0.8 + count * 0.1) }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

The `{% if cloud %}` guard means an empty DB doesn't render a 600×400 grey rectangle. Mobile (<600px) sees the flat-list `<ul class="tag-cloud">` because the CSS media query (next task) hides the canvas.

### Task 2.3: Add a failing integration assertion

**Files:**
- Modify: `tests/integration/test_web_routes_browse.py`

- [ ] **Step 1: Extend `test_tags_page_lists_tags`**

Locate `test_tags_page_lists_tags` in `tests/integration/test_web_routes_browse.py` (around line 56). Replace its body with:

```python
def test_tags_page_lists_tags(app_with_data: tuple[FastAPI, Engine]) -> None:
    app, _ = app_with_data
    r = TestClient(app).get("/tags")
    assert r.status_code == 200
    assert "work" in r.text
    assert "cooking" in r.text
    # Cloud canvas is rendered with at least one positioned chip.
    assert 'class="tag-cloud-canvas"' in r.text
    assert "left:" in r.text
```

- [ ] **Step 2: Run the test, confirm it passes**

```bash
uv run pytest tests/integration/test_web_routes_browse.py::test_tags_page_lists_tags -v
```

Expected: pass. The fixture seeds two tags (`work`, `cooking`) on `2026-05-06`; both will appear in the cloud canvas with `left:` positions. The CSS rule for `.tag-cloud-canvas` doesn't exist yet (next chunk) but the markup is in place; the test only checks markup presence.

- [ ] **Step 3: Run the full integration suite**

```bash
uv run pytest tests/integration -q -m "not live and not slow"
```

Expected: green.

- [ ] **Step 4: Commit Tasks 2.1 + 2.2 + 2.3 together**

```bash
git add src/driftnote/web/routes_browse.py \
        src/driftnote/web/templates/tags.html.j2 \
        tests/integration/test_web_routes_browse.py
git commit -m "feat(web): render tags page as a server-side word cloud"
```

---

## Chunk 3: CSS — canvas styling + media-query swap

### Task 3.1: Add `.tag-cloud-canvas` rules

**Files:**
- Modify: `src/driftnote/web/static/style.css`

- [ ] **Step 1: Locate the existing tag-cloud area**

Open `src/driftnote/web/static/style.css`. Find the existing block:

```css
/* Tag cloud — flat list (mobile fallback after #10) */
.tag-cloud { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
```

(The exact comment may differ; the rule itself is what matters. It's the section consolidating the `.tag-chip` rule from #9.)

- [ ] **Step 2: Add the canvas + media-query rules**

Replace the `.tag-cloud` block above with:

```css
/* Tag cloud canvas (desktop): absolutely-positioned chips on a 600x400 area */
.tag-cloud-canvas {
  position: relative;
  margin: 16px auto;
  background: var(--bg-raised);
}
.tag-cloud-canvas .cloud-chip {
  position: absolute;
  white-space: nowrap;
  margin-right: 0;  /* override .tag-chip default */
}

/* Flat tag list — used as the mobile fallback */
.tag-cloud { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }

@media (max-width: 600px) {
  .tag-cloud-canvas { display: none; }
}
@media (min-width: 601px) {
  .tag-cloud { display: none; }
}
```

Don't touch any other rule in the file — `.tag-chip`, the calendar rules, the admin rules, etc. all stay as-is.

- [ ] **Step 3: Stylesheet invariants audit**

```bash
grep -n "border-radius" src/driftnote/web/static/style.css
```

Expected: 1 match (the `.dot { border-radius: 50%; }` rule from PR #19).

```bash
grep -nE "box-shadow|linear-gradient|radial-gradient" src/driftnote/web/static/style.css
```

Expected: empty.

```bash
grep -nE '#[0-9a-fA-F]{3,6}' src/driftnote/web/static/style.css | grep -vE '^\s*[0-9]+:\s+--'
```

Expected: empty (no raw hex outside `:root`).

- [ ] **Step 4: Run the full integration suite**

```bash
uv run pytest tests/integration -q -m "not live and not slow"
```

Expected: green. CSS changes don't affect markup tests.

- [ ] **Step 5: Commit**

```bash
git add src/driftnote/web/static/style.css
git commit -m "style(web): tag-cloud canvas styling + mobile media-query swap"
```

---

## Chunk 4: Final verification + PR

### Task 4.1: Full fast suite

- [ ] **Step 1: Run unit + integration (excluding live/slow)**

```bash
uv run pytest -q -m "not live and not slow"
```

Expected: all green. Test count delta from master baseline: +7 unit (`test_web_cloud.py`) and 0 integration (existing test extended in place).

### Task 4.2: Manual visual sanity check

Layout-heavy changes deserve eyes on the rendered page. Quick check before opening the PR:

- [ ] **Step 1: Run the dev server**

```bash
unset DRIFTNOTE_HOME DRIFTNOTE_CONFIG DRIFTNOTE_DATA_ROOT  # clean env
DRIFTNOTE_HOME=$HOME/.driftnote uv run driftnote serve
```

(If your `~/.driftnote` doesn't have data, point at any directory containing a `config.toml` and `.env`.)

- [ ] **Step 2: Open `/tags` at desktop width and 360 px**

Visit `http://localhost:8000/tags` in a browser:
- Desktop (≥601 px): a 600×400 area with the cloud canvas; chips are absolutely positioned, no overlaps, largest tag near center.
- Mobile (≤600 px): the canvas is hidden; the flat font-scaled list shows.

If the layout looks broken (chips overlap, largest tag isn't central, mobile fallback doesn't show), STOP and re-investigate — likely a bbox-estimation drift or a CSS specificity issue.

### Task 4.3: Push + open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/issue-10-tag-cloud
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(web): server-side tag-cloud spiral layout (#10)" --body "$(cat <<'EOF'
## Summary

Closes #10.

- New `src/driftnote/web/cloud.py` module: pure-function `layout_cloud(tag_counts) -> list[CloudTag]` packs tags onto a 600×400 canvas via Archimedean spiral. Largest tag at centre, smaller ones spiral outwards; collisions detected via axis-aligned bbox overlap with 4 px margin.
- `tags_view` calls it once and passes the result to the template; logs unplaced count via `structlog`.
- `tags.html.j2` renders both the canvas (desktop) and the existing flat list (mobile fallback). CSS media queries toggle visibility at 600 px.
- No JavaScript dep — stays in the no-SPA pattern.

## Scaling and ordering

- `font_size = min_font + (max_font - min_font) * sqrt(count / max_count)` — square-root scale smooths visual distribution when one tag dominates.
- Sort key is `(-count, name)`; alphabetical tie-break for equal counts (so all-equal counts land in a deterministic order at the centre).

## Tests

- 7 unit tests cover: empty input, no overlap among placements, largest-near-center, font clamping, identical-counts behaviour, unplaceable-tag handling, one-CloudTag-per-input.
- Existing `test_tags_page_lists_tags` integration test extended to assert the canvas markup and at least one positioned chip.

## Out of scope

- Animated/draggable tags, filtering inside the cloud.
- Per-tag colours by category (no category data exists).
- Responsive canvas size — fixed at 600×400.

## Spec + plan

- Spec: `docs/superpowers/specs/2026-05-10-issue-10-tag-cloud-design.md`
- Plan: `docs/superpowers/plans/2026-05-10-issue-10-tag-cloud.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
