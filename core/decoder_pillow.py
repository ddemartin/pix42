"""Pillow-based decoder for common raster formats."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

from .decoder_base import BaseDecoder, ImageMetadata, Region

try:
    from PIL import Image, ExifTags, ImageOps
    Image.MAX_IMAGE_PIXELS = None  # viewer app — no decompression bomb limit needed
    _PILLOW_AVAILABLE = True
except Exception:
    _PILLOW_AVAILABLE = False


def _normalize_mode(img: "Image.Image") -> "Image.Image":
    """Convert img to a mode suitable for LANCZOS resampling and QImage output."""
    # Convert raw packed 16-bit modes (e.g. from TIFF plugin) before further handling
    if img.mode in ("I;16", "I;16B", "I;16L", "I;16S"):
        img = img.convert("I")

    if img.mode in ("I", "F"):
        # 16/32-bit grayscale or float — normalize to 8-bit
        arr = np.array(img, dtype=np.float32)
        lo, hi = float(arr.min()), float(arr.max())
        if hi > lo:
            arr = (arr - lo) / (hi - lo) * 255.0
        return Image.fromarray(arr.astype(np.uint8), mode="L")

    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if img.mode == "PA" else "RGB")

    # Pillow ≥ 10 may keep uint16 dtype for 16-bit-per-channel RGB/RGBA TIFFs
    arr = np.array(img)
    if arr.dtype != np.uint8:
        arr_f = arr.astype(np.float32)
        lo, hi = float(arr_f.min()), float(arr_f.max())
        if hi > lo:
            arr_f = (arr_f - lo) / (hi - lo) * 255.0
        arr_u8 = arr_f.astype(np.uint8)
        out_mode = "L" if arr_u8.ndim == 2 else ("RGBA" if arr_u8.shape[2] == 4 else "RGB")
        return Image.fromarray(arr_u8, out_mode)

    return img


def _pil_to_qimage(pil_img: "Image.Image") -> QImage:
    """Convert a PIL Image to QImage with explicit stride to avoid moiré artifacts."""
    if pil_img.mode == "RGBA":
        data = pil_img.tobytes("raw", "RGBA")
        bytes_per_line = pil_img.width * 4
        qimg = QImage(data, pil_img.width, pil_img.height,
                      bytes_per_line, QImage.Format.Format_RGBA8888)
    else:
        pil_img = pil_img.convert("RGB")
        data = pil_img.tobytes("raw", "RGB")
        bytes_per_line = pil_img.width * 3
        qimg = QImage(data, pil_img.width, pil_img.height,
                      bytes_per_line, QImage.Format.Format_RGB888)
    return qimg.copy()  # detach from PIL data buffer


class PillowDecoder(BaseDecoder):
    """Decoder for JPEG, PNG, BMP, TIFF, WEBP and other Pillow-supported formats."""

    SUPPORTED_EXTENSIONS = (
        ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp",
        ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".pbm",
    )

    def probe(self, path: Path) -> float:
        if not _PILLOW_AVAILABLE:
            return 0.0
        return 0.9 if path.suffix.lower() in self.SUPPORTED_EXTENSIONS else 0.1

    def read_metadata(self, path: Path) -> ImageMetadata:
        if not _PILLOW_AVAILABLE:
            return ImageMetadata(format_name="unknown")
        with Image.open(path) as img:
            exif_raw = {}
            try:
                raw_exif = img._getexif()  # type: ignore[attr-defined]
                if raw_exif:
                    exif_raw = {
                        ExifTags.TAGS.get(k, k): v
                        for k, v in raw_exif.items()
                    }
            except Exception:
                pass

            # Use post-rotation dimensions so callers see the display size
            try:
                transposed = ImageOps.exif_transpose(img)
                w, h = transposed.width, transposed.height
            except Exception:
                w, h = img.width, img.height

            channels = len(img.getbands())
            return ImageMetadata(
                width=w,
                height=h,
                channels=channels,
                bit_depth=8,
                color_space="sRGB",
                format_name=img.format or path.suffix.lstrip(".").upper(),
                exif=exif_raw,
            )

    def decode_preview(self, path: Path, max_size: int) -> QImage:
        if not _PILLOW_AVAILABLE:
            return QImage()
        with Image.open(path) as img:
            # Apply EXIF orientation BEFORE resize so dimensions are correct
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img = _normalize_mode(img)
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            return _pil_to_qimage(img)

    def decode_region(self, path: Path, region: Region, scale: float) -> QImage:
        if not _PILLOW_AVAILABLE:
            return QImage()
        with Image.open(path) as img:
            # Apply EXIF orientation first so region coords match the display image
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            img = _normalize_mode(img)
            box = (region.x, region.y, region.x + region.width, region.y + region.height)
            cropped = img.crop(box)
            if scale != 1.0:
                new_w = max(1, int(cropped.width * scale))
                new_h = max(1, int(cropped.height * scale))
                cropped = cropped.resize((new_w, new_h), Image.LANCZOS)
            return _pil_to_qimage(cropped)

    def can_decode_region(self) -> bool:
        return True
