# Issue #6 — Photo derivatives lose EXIF orientation

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phone photos shot in physical landscape orientation but logically portrait should display correctly (not sideways) in the web UI and digest emails.

**Architecture:** Phones store JPEGs in a fixed sensor orientation and rely on the EXIF `Orientation` tag (1–8) for display rotation. `derive_photo` in `src/driftnote/ingest/attachments.py` strips EXIF before saving the derivative (privacy), so downstream viewers can't apply the rotation. Fix: bake the rotation into pixels with `PIL.ImageOps.exif_transpose` before stripping EXIF.

**Tech Stack:** Pillow + pillow-heif (already deps).

**Issue:** https://github.com/maciej-makowski/driftnote/issues/6

---

## Chunk 1: Apply EXIF orientation, then strip metadata

### Task 1: Add a rotated test fixture, fix the derivative path

**Files:**
- Modify: `src/driftnote/ingest/attachments.py` (function `derive_photo`)
- Modify: `tests/unit/test_ingest_attachments.py` (add new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ingest_attachments.py`:

```python
def test_derive_photo_applies_exif_orientation(tmp_path: Path) -> None:
    """A JPEG marked Orientation=6 (rotate 90° CW) should produce a
    derivative whose pixel dimensions are the post-rotation expected ones.

    Source: 200x150 with Orientation=6 means the 'logical' image is 150x200.
    The web/thumb derivatives must reflect 150x200 (longest axis = 200).
    """
    from io import BytesIO

    from PIL import Image as _Image

    src = _Image.new("RGB", (200, 150), color=(60, 100, 180))
    # ExifTags.Base.Orientation == 0x0112 == 274. Tag value 6 = "Rotate 90 CW".
    exif = src.getexif()
    exif[0x0112] = 6
    buf = BytesIO()
    src.save(buf, "JPEG", exif=exif.tobytes(), quality=85)
    raw = buf.getvalue()

    artifacts = derive_photo(
        original_bytes=raw,
        original_filename="rotated.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert artifacts.web_path is not None
    assert artifacts.thumb_path is not None
    with Image.open(artifacts.web_path) as web:
        assert web.size == (150, 200), (
            f"expected post-rotation 150x200 in web copy, got {web.size}"
        )
    # Original is preserved verbatim — its pixel data is still 200x150 with
    # Orientation=6, even though the rendered display is 150x200.
    assert artifacts.original_path.read_bytes() == raw
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_ingest_attachments.py::test_derive_photo_applies_exif_orientation -v`
Expected: FAIL with `web.size == (200, 150)` — the rotation wasn't applied.

- [ ] **Step 3: Fix `derive_photo`**

In `src/driftnote/ingest/attachments.py`, locate the `try:` block inside `derive_photo` (around line 60). Add `ImageOps.exif_transpose` BEFORE the existing `convert("RGB")` call. Update the import line at the top:

```python
from PIL import Image, ImageOps
```

Then change:

```python
        with Image.open(BytesIO(original_bytes)) as img:
            img = img.convert("RGB")
            web_img = _resize_max_axis(img, WEB_MAX_AXIS)
            web_img.save(web_path, "JPEG", quality=85, optimize=True)
            thumb_img = _resize_max_axis(img, THUMB_MAX_AXIS)
            thumb_img.save(thumb_path, "JPEG", quality=80, optimize=True)
```

to:

```python
        with Image.open(BytesIO(original_bytes)) as img:
            # Bake the EXIF orientation into pixel data before stripping EXIF
            # on save. Phone JPEGs commonly store sensor-orientation pixels
            # with Orientation=6 (rotate 90 CW) — without exif_transpose the
            # derivative shows up sideways for any viewer that doesn't read
            # EXIF (most browsers DO read it now, but stripping the tag means
            # they can't, so we must rotate the pixels).
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            web_img = _resize_max_axis(img, WEB_MAX_AXIS)
            web_img.save(web_path, "JPEG", quality=85, optimize=True)
            thumb_img = _resize_max_axis(img, THUMB_MAX_AXIS)
            thumb_img.save(thumb_path, "JPEG", quality=80, optimize=True)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/unit/test_ingest_attachments.py::test_derive_photo_applies_exif_orientation -v`
Expected: PASS.

- [ ] **Step 5: Run the full attachments suite to confirm no regressions**

Run: `uv run pytest tests/unit/test_ingest_attachments.py -v`
Expected: 7 passed (6 prior + 1 new).

- [ ] **Step 6: Run the full suite + lint + types**

Run: `uv run pytest -m "not live" -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy`
Expected: 176 passed; lint/types clean.

- [ ] **Step 7: Commit**

```bash
git add src/driftnote/ingest/attachments.py tests/unit/test_ingest_attachments.py
git commit -m "$(cat <<'EOF'
fix(ingest): apply EXIF orientation before generating photo derivatives

Phones store JPEG pixels in sensor-physical orientation and rely on the
EXIF Orientation tag (1-8) for display rotation. derive_photo strips
EXIF on save (privacy), so without baking the rotation into pixel data
first, every portrait phone shot ends up sideways in the web UI.

PIL.ImageOps.exif_transpose() reads the Orientation tag and applies the
correct rotation/flip to the pixel data, after which the EXIF strip is
safe. Originals are preserved verbatim (their EXIF stays intact).

Test asserts a 200x150 source with Orientation=6 produces a 150x200
derivative.

Closes #6
EOF
)"
```

### Closeout

**Acceptance criteria:**
- [ ] Photos with `Orientation=6` (the most common phone case) display in their intended orientation in the web copy and thumbnail
- [ ] Originals are preserved bit-exact (their EXIF tag is not modified)
- [ ] All existing tests still pass
- [ ] One new test covers the regression
- [ ] Closes #6 via the commit message
