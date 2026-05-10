# Tag-cloud spiral layout

> Design spec for [issue #10](https://github.com/maciej-makowski/driftnote/issues/10).

## Goal

Replace the flat font-size-scaled tag list at `/tags` with a proper word cloud: tags arranged spatially with the most-used tags at the center, sized larger; less-used tags drift outward and shrink. Pure server-side layout (no JS), accessible (real anchor links), graceful mobile fallback.

## Architecture

A single new module `src/driftnote/web/cloud.py` exposes `layout_cloud(...)`. Pure function, no I/O, fully unit-testable. The route handler `tags_view` calls it once and passes the resulting list to the template alongside the existing flat `tags` list (used for the mobile fallback).

## Public API

```python
# src/driftnote/web/cloud.py
from __future__ import annotations

from dataclasses import dataclass

# Public canvas dimensions — single source of truth shared with the
# tags_view route handler so handler/template/CSS stay in agreement.
DEFAULT_WIDTH = 600
DEFAULT_HEIGHT = 400


@dataclass(frozen=True)
class CloudTag:
    name: str
    count: int
    x: int          # left-edge px (CSS-friendly)
    y: int          # top-edge px
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
    ...
```

The function returns one `CloudTag` per input tag, in descending-frequency / alphabetical-tie order. Tags that fail to place after `max_steps` are returned with `placed=False` and (x, y) set to (0, 0); the template skips them. The route handler imports `DEFAULT_WIDTH`/`DEFAULT_HEIGHT` to thread the same numbers into the template context.

## Algorithm

1. **Sort** input by count descending, with alphabetical tie-break (`sorted(..., key=lambda kv: (-kv[1], kv[0]))`). Empty input → `[]` immediately. With all counts equal, every tag receives `max_font` (sqrt of 1.0) and the spiral order is alphabetical.
2. **Font scale** uses the square root of the normalised count for smoother visual distribution when one tag dominates: `font_size = round(min_font + (max_font - min_font) * sqrt(count / max_count))`.
3. **Bounding box estimate**: `bbox_w = font * 0.6 * (len(name) + 1)` (the `+1` accounts for the `#` prefix the template prepends), `bbox_h = font * 1.2`. Pad with 4 px margin on every side to absorb width-estimation slop in proportional fonts. The returned `(x, y)` is the **un-padded** top-left; the 4 px margin is applied to the bbox used for collision testing only — the template renders `left:{{ t.x }}px` directly.
4. **Archimedean spiral** from canvas centre:
   - `theta = step * 0.3` (radians)
   - `r = step * 1.5` (px)
   - `x = canvas_center_x + r * cos(theta) - bbox_w / 2`
   - `y = canvas_center_y + r * sin(theta) - bbox_h / 2`
5. For each candidate `(x, y)` check axis-aligned bbox overlap against every already-placed tag's bbox. First non-colliding spot wins.
6. If `max_steps` (default 500) exhaust, mark `placed=False` and continue to the next tag. The route-handler caller logs the count of unplaced tags via `structlog` so growth is observable.

## Data flow

```
tag_frequencies_in_range
        │
        ▼
   dict[str, int]
        │
        ▼
   layout_cloud(...) ─────► list[CloudTag]
        │
        ▼
tags.html.j2 (loops over cloud; emits absolutely-positioned <a>s)
```

## Template

`src/driftnote/web/templates/tags.html.j2`:

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

Both the canvas and the flat list are emitted; CSS toggles which is visible per viewport. The flat list is the same one the page renders today, kept intact as the mobile fallback (and as a graceful degradation if the canvas markup ever fails).

## CSS

`src/driftnote/web/static/style.css`:

```css
/* Tag cloud — desktop (canvas with absolutely-positioned chips) */
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

/* Mobile fallback: hide the canvas, show the flex list */
@media (max-width: 600px) {
  .tag-cloud-canvas { display: none; }
}
@media (min-width: 601px) {
  .tag-cloud { display: none; }
}
```

The existing `.tag-chip` rule (consolidated in #9) supplies the chip background, padding, and hover. `.cloud-chip` adds the absolute-positioning and overrides the default `margin-right` (which is irrelevant inside a positioned container).

## Route change

`src/driftnote/web/routes_browse.py::tags_view`:

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

`canvas_width` and `canvas_height` are hardcoded at the route layer to match the defaults in `layout_cloud`. Keeping them as template variables (rather than inlining in the template) keeps the spec/handler/CSS in agreement and makes a future "responsive cloud" follow-up cheap.

A module-level `log = structlog.get_logger(__name__)` is added to `routes_browse.py` if not already present (the file currently doesn't log; this introduces logging there).

## Files touched

| File | Change |
|---|---|
| `src/driftnote/web/cloud.py` | New module — `layout_cloud` + `CloudTag` (~60 lines) |
| `src/driftnote/web/routes_browse.py` | `tags_view` builds cloud + logs unplaced count |
| `src/driftnote/web/templates/tags.html.j2` | Emit canvas + keep flat-list fallback |
| `src/driftnote/web/static/style.css` | New `.tag-cloud-canvas` + media-query swap |
| `tests/unit/test_web_cloud.py` (new) | Cover empty input, no overlap, centerpiece position, font clamping, unplaceable tags |
| `tests/integration/test_web_routes_browse.py` | Extend `test_tags_page_lists_tags` to assert canvas markup |

## Tests

### Unit (`tests/unit/test_web_cloud.py`)

```python
def test_layout_cloud_empty_input_returns_empty_list() -> None:
    assert layout_cloud({}) == []


def test_layout_cloud_largest_tag_lands_near_center() -> None:
    cloud = layout_cloud({"work": 50, "rest": 5}, width=600, height=400)
    largest = next(t for t in cloud if t.name == "work")
    # Centerpiece is the first spiral step (r=0). Within ±5 px of center.
    cx, cy = 300, 200
    bbox_w = int(largest.font_size * 0.6 * (len("work") + 1))
    bbox_h = int(largest.font_size * 1.2)
    assert abs(largest.x + bbox_w / 2 - cx) < 5
    assert abs(largest.y + bbox_h / 2 - cy) < 5


def test_layout_cloud_placements_do_not_overlap() -> None:
    counts = {f"tag{i}": 50 - i for i in range(20)}
    cloud = layout_cloud(counts)
    placed = [t for t in cloud if t.placed]
    for i, a in enumerate(placed):
        a_w = int(a.font_size * 0.6 * (len(a.name) + 1))
        a_h = int(a.font_size * 1.2)
        for b in placed[i + 1 :]:
            b_w = int(b.font_size * 0.6 * (len(b.name) + 1))
            b_h = int(b.font_size * 1.2)
            assert a.x + a_w <= b.x or b.x + b_w <= a.x or a.y + a_h <= b.y or b.y + b_h <= a.y, (
                f"{a.name} overlaps {b.name}"
            )


def test_layout_cloud_marks_unplaceable_tags() -> None:
    """Tiny canvas with many big tags forces some unplaced."""
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
```

### Integration (`tests/integration/test_web_routes_browse.py`)

Add to existing `test_tags_page_lists_tags`:
```python
# Canvas markup with a positioned cloud chip is present.
assert 'class="tag-cloud-canvas"' in r.text
assert "left:" in r.text
```

(The existing fixture seeds two tags `work` and `cooking`; both should appear in the canvas, so `left:` will be present at least twice.)

## Acceptance criteria

- [ ] `/tags` shows a tag cloud where size and position correlate with frequency.
- [ ] Tags remain clickable links to `/?tag=<name>` (the existing `tag_chip` macro and per-chip styling are reused).
- [ ] Mobile (<600px) shows the flat font-size-scaled list (current behaviour preserved as fallback).
- [ ] At least four unit tests cover the layout function (empty input, no overlap, largest-near-center, font clamping, unplaceable handling).
- [ ] Existing tests still pass.
- [ ] Stylesheet invariants still hold: 1 `border-radius` (status dot), no shadow/gradient, no raw hex outside `:root`.

## Risks

**Risk:** Bbox estimation (`font * 0.6 * len`) under-shoots for wide glyphs or tags with capital letters; chips can visually overlap even though the algorithm thinks they don't.
**Mitigation:** 4 px margin padding on every bbox + `white-space: nowrap` keep the visual gap reliable for system-ui at the chosen font sizes. If a real overlap is reported, raise the per-side margin or switch to a measured monospace-style font for the cloud only.

**Risk:** Personal journal scales (~100+ tags) may exhaust 500 spiral steps for the long tail.
**Mitigation:** `max_steps` is a parameter; bump per the structlog signal. The fallback list still surfaces unplaced tags on mobile (and via the canvas-disabled CSS path).

**Risk:** Square-root scaling looks too uniform when the count distribution is itself flat (everyone has 5 entries, one has 6).
**Mitigation:** Acceptable — the layout still provides spatial differentiation by virtue of the spiral. If the user wants more contrast they can adjust `min_font`/`max_font` on the route call.

**Risk:** Tag names wider than the canvas at `max_font` (e.g. a 60-character tag at 36 px ≈ 1300 px) cannot be placed at any spiral step and always come back `placed=False`.
**Mitigation:** Accepted — the mobile flat-list fallback surfaces these regardless. Real journal tags are short enough that this is theoretical.

## Out of scope

- Animated layouts, draggable tags, filtering inside the cloud.
- Per-tag colours by category (no category data exists).
- Responsive canvas size — fixed at 600×400 for now; revisit if the layout proves cramped on common desktop widths.
