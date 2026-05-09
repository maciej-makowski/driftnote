"""Tests for image and video derivative generation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from driftnote.ingest.attachments import (
    AttachmentArtifacts,
    derive_photo,
    derive_video_poster,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "images"


def test_derive_photo_jpeg_creates_web_and_thumb(tmp_path: Path) -> None:
    artifacts = derive_photo(
        original_bytes=(FIXTURE_DIR / "tiny.jpg").read_bytes(),
        original_filename="tiny.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert isinstance(artifacts, AttachmentArtifacts)
    assert artifacts.original_path == tmp_path / "originals" / "tiny.jpg"
    assert artifacts.web_path == tmp_path / "web" / "tiny.jpg"
    assert artifacts.thumb_path == tmp_path / "thumbs" / "tiny.jpg"
    assert artifacts.original_path.exists()
    assert artifacts.web_path.exists()
    assert artifacts.thumb_path.exists()
    with Image.open(artifacts.thumb_path) as t:
        assert max(t.size) == 320
    with Image.open(artifacts.web_path) as w:
        # Original is 400x300 — already smaller than 1600 cap, so web copy keeps the dimensions.
        assert max(w.size) == 400


def test_derive_photo_heic_converts_to_jpeg(tmp_path: Path) -> None:
    artifacts = derive_photo(
        original_bytes=(FIXTURE_DIR / "tiny.heic").read_bytes(),
        original_filename="tiny.heic",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    # Original is preserved verbatim.
    assert artifacts.original_path.suffix == ".heic"
    # Web/thumb are JPEG for browser compatibility.
    assert artifacts.web_path is not None
    assert artifacts.thumb_path is not None
    assert artifacts.web_path.suffix == ".jpg"
    assert artifacts.thumb_path.suffix == ".jpg"
    with Image.open(artifacts.web_path) as img:
        assert img.format == "JPEG"


def test_derive_photo_strips_exif_from_derivatives(tmp_path: Path) -> None:
    # Build an in-memory JPEG with embedded EXIF.
    from PIL import Image as _Image

    src = _Image.new("RGB", (200, 150), color=(60, 100, 180))
    exif_bytes = b""
    if hasattr(src, "getexif"):
        exif = src.getexif()
        exif[0x010F] = "DriftnoteTestMaker"  # Make
        exif_bytes = exif.tobytes()
    out = tmp_path / "with-exif.jpg"
    src.save(out, "JPEG", exif=exif_bytes)
    raw = out.read_bytes()

    artifacts = derive_photo(
        original_bytes=raw,
        original_filename="with-exif.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert artifacts.web_path is not None
    with Image.open(artifacts.web_path) as web:
        web_exif = web.getexif() if hasattr(web, "getexif") else {}
    assert all(tag != 0x010F for tag in web_exif)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not available on this host",
)
def test_derive_video_poster_extracts_frame(tmp_path: Path) -> None:
    poster = derive_video_poster(
        original_bytes=(FIXTURE_DIR / "tiny.mov").read_bytes(),
        original_filename="tiny.mov",
        originals_dir=tmp_path / "originals",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert poster.original_path.exists()
    assert poster.thumb_path is not None
    assert poster.thumb_path.suffix == ".jpg"
    assert poster.thumb_path.exists()
    assert poster.web_path is None
    with Image.open(poster.thumb_path) as img:
        assert img.format == "JPEG"


def test_derive_photo_preserves_original_filename_for_originals_dir(tmp_path: Path) -> None:
    artifacts = derive_photo(
        original_bytes=(FIXTURE_DIR / "tiny.jpg").read_bytes(),
        original_filename="my photo!.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    # Originals are stored with the sender's filename verbatim (they're treated as opaque).
    assert artifacts.original_path.name == "my photo!.jpg"
    # Web/thumb may differ in suffix but should keep the stem.
    assert artifacts.web_path is not None
    assert artifacts.web_path.stem == "my photo!"


def test_derive_photo_handles_unreadable_original(tmp_path: Path) -> None:
    """If the bytes don't decode as an image, original is still saved but web/thumb are None."""
    artifacts = derive_photo(
        original_bytes=b"not an image",
        original_filename="broken.jpg",
        originals_dir=tmp_path / "originals",
        web_dir=tmp_path / "web",
        thumbs_dir=tmp_path / "thumbs",
    )
    assert artifacts.original_path.exists()
    assert artifacts.web_path is None
    assert artifacts.thumb_path is None


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
        assert web.size == (150, 200), f"expected post-rotation 150x200 in web copy, got {web.size}"
    # Original is preserved verbatim — its pixel data is still 200x150 with
    # Orientation=6, even though the rendered display is 150x200.
    assert artifacts.original_path.read_bytes() == raw
