"""PSD (Photoshop Document) decoder using psd-tools.

Requires:
    pip install psd-tools

psd-tools composites all layers, so it works even when Photoshop's
"Maximize Compatibility" option is disabled (no merged composite present).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from .decoder_base import BaseDecoder, ImageMetadata, Region
from .decoder_pillow import _normalize_mode, _pil_to_qimage

try:
    from psd_tools import PSDImage as _PSDImage
    _PSD_OK = True
except ImportError:
    _PSD_OK = False


def _composite(path: Path) -> "object":
    """Open a PSD and return a composited PIL Image."""
    psd = _PSDImage.open(str(path))
    pil = psd.composite()
    if pil is None:
        # Some PSDs have no pixel data at all — return a blank image
        from PIL import Image
        pil = Image.new("RGB", (psd.width, psd.height), (128, 128, 128))
    return pil


class PsdDecoder(BaseDecoder):
    """
    Reads Adobe Photoshop PSD files by compositing all layers.

    Works with files saved with or without "Maximize Compatibility".
    """

    SUPPORTED_EXTENSIONS = (".psd",)

    def probe(self, path: Path) -> float:
        if not _PSD_OK:
            return 0.0
        return 1.0 if path.suffix.lower() in self.SUPPORTED_EXTENSIONS else 0.0

    def read_metadata(self, path: Path) -> ImageMetadata:
        if not _PSD_OK:
            return ImageMetadata(format_name="PSD")
        psd = _PSDImage.open(str(path))
        depth = (
            getattr(psd, "depth", None)
            or getattr(getattr(psd, "header", None), "depth", None)
            or 8
        )
        try:
            color_space = psd.color_mode.name
        except AttributeError:
            color_space = "RGB"
        return ImageMetadata(
            width=psd.width,
            height=psd.height,
            channels=3,
            bit_depth=depth,
            color_space=color_space,
            format_name="PSD",
        )

    def decode_preview(self, path: Path, max_size: int) -> QImage:
        if not _PSD_OK:
            return QImage()
        from PIL import Image
        pil = _composite(path)
        pil = _normalize_mode(pil)
        pil.thumbnail((max_size, max_size), Image.LANCZOS)
        return _pil_to_qimage(pil)

    def decode_region(self, path: Path, region: Region, scale: float) -> QImage:
        if not _PSD_OK:
            return QImage()
        from PIL import Image
        pil = _composite(path)
        pil = _normalize_mode(pil)
        box = (region.x, region.y, region.x + region.width, region.y + region.height)
        cropped = pil.crop(box)
        if scale != 1.0:
            new_w = max(1, int(cropped.width * scale))
            new_h = max(1, int(cropped.height * scale))
            cropped = cropped.resize((new_w, new_h), Image.LANCZOS)
        return _pil_to_qimage(cropped)

    def can_decode_region(self) -> bool:
        return True
