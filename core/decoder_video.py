"""Video thumbnail decoder — extracts frame 0 via FFmpeg subprocess."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygon
from PySide6.QtCore import QPoint

from .decoder_base import BaseDecoder, ImageMetadata, Region

log = logging.getLogger(__name__)

# Resolved once at first use; empty string means "not found"
_FFMPEG: str | None = None


def _ffmpeg_bin() -> str | None:
    global _FFMPEG
    if _FFMPEG is None:
        found = shutil.which("ffmpeg")
        _FFMPEG = found if found else ""
        if found:
            log.debug("FFmpeg found: %s", found)
        else:
            log.debug("FFmpeg not found on PATH — video thumbnails will use placeholder")
    return _FFMPEG or None


def _make_placeholder(size: int) -> QImage:
    """Dark thumbnail with a play-triangle icon."""
    s = min(size, 256)
    img = QImage(s, s, QImage.Format.Format_RGB888)
    img.fill(QColor(28, 28, 32))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy, r = s // 2, s // 2, s // 5
    p.setBrush(QColor(160, 160, 165, 180))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygon([
        QPoint(cx - r // 2, cy - r),
        QPoint(cx - r // 2, cy + r),
        QPoint(cx + r,      cy),
    ]))
    p.end()
    return img


def _extract_frame(path: Path, max_size: int, seek: str | None = "00:00:01") -> QImage:
    """Run ffmpeg to extract one frame; return null QImage on failure."""
    ffmpeg = _ffmpeg_bin()
    if ffmpeg is None:
        return QImage()

    scale_filter = (
        f"scale='if(gt(iw,ih),min({max_size},iw),-2)':"
        f"'if(gt(ih,iw),min({max_size},ih),-2)'"
    )

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    try:
        cmd = [ffmpeg, "-loglevel", "error"]
        if seek:
            cmd += ["-ss", seek]
        cmd += [
            "-i", str(path),
            "-vframes", "1",
            "-vf", scale_filter,
            "-q:v", "3",
            "-y", tmp.name,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        if r.returncode == 0:
            img = QImage(tmp.name)
            if not img.isNull():
                return img.copy()
    except Exception as exc:
        log.debug("ffmpeg frame extraction failed for %s: %s", path.name, exc)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return QImage()


class VideoDecoder(BaseDecoder):
    """Thumbnail-only decoder for common video formats via FFmpeg."""

    SUPPORTED_EXTENSIONS = (
        ".mp4", ".avi", ".mov", ".mkv", ".wmv",
        ".webm", ".m4v", ".flv", ".mpeg", ".mpg",
    )

    def probe(self, path: Path) -> float:
        return 0.95 if path.suffix.lower() in self.SUPPORTED_EXTENSIONS else 0.0

    def read_metadata(self, path: Path) -> ImageMetadata:
        return ImageMetadata(
            format_name=path.suffix.lstrip(".").upper(),
        )

    def decode_preview(self, path: Path, max_size: int) -> QImage:
        # Try seeking 1 s in; fall back to frame 0 for short clips
        img = _extract_frame(path, max_size, seek="00:00:01")
        if img.isNull():
            img = _extract_frame(path, max_size, seek=None)
        if img.isNull():
            img = _make_placeholder(max_size)
        return img

    def decode_region(self, path: Path, region: Region, scale: float) -> QImage:
        return QImage()
