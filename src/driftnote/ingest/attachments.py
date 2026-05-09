"""Generate web/thumb derivatives for photos and a poster frame for videos.

Originals are stored verbatim (treated as opaque bytes). Derivatives:
- Photo web copy: max-axis 1600px, JPEG, EXIF stripped.
- Photo thumbnail: max-axis 320px, JPEG.
- HEIC → JPEG conversion for web/thumb (originals stay HEIC).
- Video poster: ffmpeg-extracted single frame at ~1s, max-axis 320px JPEG.

If decoding fails for any reason, the original is still preserved and
derivative paths come back as None — the UI falls back to a placeholder.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

WEB_MAX_AXIS = 1600
THUMB_MAX_AXIS = 320


@dataclass(frozen=True)
class AttachmentArtifacts:
    original_path: Path
    web_path: Path | None
    thumb_path: Path | None


def derive_photo(
    *,
    original_bytes: bytes,
    original_filename: str,
    originals_dir: Path,
    web_dir: Path,
    thumbs_dir: Path,
) -> AttachmentArtifacts:
    """Save original bytes verbatim, then attempt to produce web + thumb derivatives.

    Returns artifacts with `web_path`/`thumb_path = None` if derivative
    generation fails; the original is always written as long as the disk
    write itself succeeds.
    """
    originals_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    original_path = originals_dir / original_filename
    original_path.write_bytes(original_bytes)

    derived_stem = Path(original_filename).stem
    web_path = web_dir / f"{derived_stem}.jpg"
    thumb_path = thumbs_dir / f"{derived_stem}.jpg"

    try:
        with Image.open(BytesIO(original_bytes)) as raw_img:
            # Bake the EXIF orientation into pixel data before stripping EXIF
            # on save. Phone JPEGs commonly store sensor-orientation pixels
            # with Orientation=6 (rotate 90 CW) — without exif_transpose the
            # derivative shows up sideways for any viewer that doesn't read
            # EXIF (most browsers DO read it now, but stripping the tag means
            # they can't, so we must rotate the pixels).
            img = ImageOps.exif_transpose(raw_img)
            img = img.convert("RGB")
            web_img = _resize_max_axis(img, WEB_MAX_AXIS)
            web_img.save(web_path, "JPEG", quality=85, optimize=True)
            thumb_img = _resize_max_axis(img, THUMB_MAX_AXIS)
            thumb_img.save(thumb_path, "JPEG", quality=80, optimize=True)
    except Exception:
        return AttachmentArtifacts(
            original_path=original_path,
            web_path=None,
            thumb_path=None,
        )

    return AttachmentArtifacts(
        original_path=original_path,
        web_path=web_path,
        thumb_path=thumb_path,
    )


def derive_video_poster(
    *,
    original_bytes: bytes,
    original_filename: str,
    originals_dir: Path,
    thumbs_dir: Path,
) -> AttachmentArtifacts:
    """Save original video bytes verbatim and extract a poster frame as a JPEG thumbnail."""
    originals_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    original_path = originals_dir / original_filename
    original_path.write_bytes(original_bytes)

    derived_stem = Path(original_filename).stem
    thumb_path = thumbs_dir / f"{derived_stem}.jpg"

    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        return AttachmentArtifacts(original_path=original_path, web_path=None, thumb_path=None)

    with tempfile.NamedTemporaryFile(suffix=".jpg") as raw_thumb:
        try:
            subprocess.run(  # noqa: S603
                [
                    ffmpeg_bin,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(original_path),
                    "-ss",
                    "00:00:01",  # seek 1s in
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale='min({THUMB_MAX_AXIS},iw)':-2",
                    raw_thumb.name,
                ],
                check=True,
                timeout=30,
            )
            with Image.open(raw_thumb.name) as img:
                img.convert("RGB").save(thumb_path, "JPEG", quality=80, optimize=True)
        except subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError:
            return AttachmentArtifacts(original_path=original_path, web_path=None, thumb_path=None)

    return AttachmentArtifacts(original_path=original_path, web_path=None, thumb_path=thumb_path)


def _resize_max_axis(img: Image.Image, cap: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= cap:
        return img.copy()
    ratio = cap / longest
    new_size = (int(w * ratio), int(h * ratio))
    return img.resize(new_size, Image.Resampling.LANCZOS)
