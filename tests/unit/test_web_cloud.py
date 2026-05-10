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
            disjoint = ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
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
