"""RAW image decoder using rawpy (libraw)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from .decoder_base import BaseDecoder, ImageMetadata, Region

try:
    import rawpy
    _RAWPY_AVAILABLE = True
except Exception:
    _RAWPY_AVAILABLE = False


_RAW_EXTENSIONS = (
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".rw2", ".raf", ".orf", ".dng", ".pef", ".x3f", ".kdc",
    ".dcr", ".mrw", ".3fr", ".mef", ".erf", ".rwl", ".iiq",
)


def _rgb_array_to_qimage(arr: np.ndarray) -> QImage:
    """Convert HxWx3 uint8 numpy array to QImage (RGB888)."""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    qimg = QImage(arr.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return qimg.copy()


class RawDecoder(BaseDecoder):
    """Decoder for camera RAW files via rawpy/libraw."""

    SUPPORTED_EXTENSIONS = _RAW_EXTENSIONS

    def probe(self, path: Path) -> float:
        if not _RAWPY_AVAILABLE:
            return 0.0
        return 0.95 if path.suffix.lower() in _RAW_EXTENSIONS else 0.0

    def read_metadata(self, path: Path) -> ImageMetadata:
        if not _RAWPY_AVAILABLE:
            return ImageMetadata(format_name="RAW")
        with rawpy.imread(str(path)) as raw:
            h, w = raw.sizes.raw_height, raw.sizes.raw_width
            return ImageMetadata(
                width=w,
                height=h,
                channels=3,
                bit_depth=14,
                color_space="raw",
                format_name=path.suffix.lstrip(".").upper(),
                extra={
                    "camera_model": getattr(raw, "camera_model", ""),
                    "iso_speed": None,
                },
            )

    def decode_preview(self, path: Path, max_size: int) -> QImage:
        """Use embedded JPEG thumbnail when available, fall back to fast demosaic."""
        if not _RAWPY_AVAILABLE:
            return QImage()
        try:
            with rawpy.imread(str(path)) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        from PIL import Image, ImageOps
                        import io
                        img = Image.open(io.BytesIO(thumb.data))
                        img = ImageOps.exif_transpose(img)
                        img.thumbnail((max_size, max_size), Image.LANCZOS)
                        from .decoder_pillow import _pil_to_qimage
                        return _pil_to_qimage(img)
                except Exception:
                    pass
                # Fallback: fast demosaic with the already-open handle
                rgb = raw.postprocess(
                    half_size=True,
                    use_camera_wb=True,
                    no_auto_bright=False,
                    output_bps=8,
                )
        except Exception:
            return QImage()
        h, w = rgb.shape[:2]
        scale = min(max_size / w, max_size / h, 1.0)
        if scale < 1.0:
            from PIL import Image
            pil = Image.fromarray(rgb)
            pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            rgb = np.array(pil)
        return _rgb_array_to_qimage(rgb)

    def decode_full(self, path: Path) -> QImage:
        """Full sensor-resolution demosaic (no half_size, no downscale)."""
        if not _RAWPY_AVAILABLE:
            return QImage()
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        return _rgb_array_to_qimage(rgb)

    def decode_region(self, path: Path, region: Region, scale: float) -> QImage:
        """Decode full image and crop — libraw does not support true ROI."""
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        from PIL import Image
        pil = Image.fromarray(rgb)
        box = (region.x, region.y, region.x + region.width, region.y + region.height)
        cropped = pil.crop(box)
        if scale != 1.0:
            new_w = max(1, int(cropped.width * scale))
            new_h = max(1, int(cropped.height * scale))
            cropped = cropped.resize((new_w, new_h), Image.LANCZOS)
        return _rgb_array_to_qimage(np.array(cropped))
