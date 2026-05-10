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
    x: int  # left-edge px (CSS-friendly), un-padded
    y: int  # top-edge px, un-padded
    font_size: int  # px
    placed: bool  # True if the spiral found a collision-free spot


def layout_cloud(
    tag_counts: dict[str, int],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    min_font: int = 12,
    max_font: int = 36,
    max_steps: int = 500,
) -> list[CloudTag]:
    """Pack tags onto a `width` x `height` canvas using an Archimedean spiral.

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
            out.append(
                CloudTag(name=name, count=count, x=0, y=0, font_size=font_size, placed=False)
            )
        else:
            x, y = spot
            placed.append(
                (
                    x - _BBOX_MARGIN,
                    y - _BBOX_MARGIN,
                    bbox_w + 2 * _BBOX_MARGIN,
                    bbox_h + 2 * _BBOX_MARGIN,
                )
            )
            out.append(CloudTag(name=name, count=count, x=x, y=y, font_size=font_size, placed=True))

    return out


def _collides(x: int, y: int, w: int, h: int, placed: list[tuple[int, int, int, int]]) -> bool:
    """Axis-aligned bbox overlap check against every already-placed bbox.

    Each entry in `placed` is (x, y, w, h) of the PADDED bbox.
    """
    pad_x = x - _BBOX_MARGIN
    pad_y = y - _BBOX_MARGIN
    pad_w = w + 2 * _BBOX_MARGIN
    pad_h = h + 2 * _BBOX_MARGIN
    for px, py, pw, ph in placed:
        if pad_x + pad_w > px and px + pw > pad_x and pad_y + pad_h > py and py + ph > pad_y:
            return True
    return False
