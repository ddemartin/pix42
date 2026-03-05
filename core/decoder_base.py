"""Abstract base class for all image decoders."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtGui import QImage


@dataclass
class ImageMetadata:
    """Minimal metadata extracted during probe/read phase."""
    width: int = 0
    height: int = 0
    channels: int = 3
    bit_depth: int = 8
    color_space: str = "sRGB"
    format_name: str = ""
    exif: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class Region:
    """Pixel-space rectangle for ROI decoding."""
    x: int
    y: int
    width: int
    height: int


class BaseDecoder(ABC):
    """
    Abstract decoder interface.

    Each concrete decoder handles one or more file formats.
    The loader selects the best decoder via ``probe()``.
    """

    # File extensions this decoder can handle (lowercase, with dot)
    SUPPORTED_EXTENSIONS: tuple[str, ...] = ()

    @abstractmethod
    def probe(self, path: Path) -> float:
        """
        Return a confidence score [0.0, 1.0] that this decoder can handle *path*.

        0.0 = cannot handle, 1.0 = perfect match.
        """

    @abstractmethod
    def read_metadata(self, path: Path) -> ImageMetadata:
        """Return lightweight metadata without decoding pixel data."""

    @abstractmethod
    def decode_preview(self, path: Path, max_size: int) -> QImage:
        """
        Decode a fast preview image scaled to fit within *max_size* pixels.

        Used for fit-to-window display and thumbnail generation.
        """

    @abstractmethod
    def decode_region(self, path: Path, region: Region, scale: float) -> QImage:
        """
        Decode a sub-region of the image at the given scale factor.

        Used for tiled rendering of large images.
        """

    # ------------------------------------------------------------------ #
    # Optional hooks                                                       #
    # ------------------------------------------------------------------ #

    def decode_full(self, path: Path) -> QImage:
        """
        Decode the image at its native resolution.

        Default: delegate to decode_preview with a very large max_size, which
        is a no-op downscale for Pillow/FITS since thumbnail() never upscales.
        RAW decoders should override this to do a full demosaic.
        """
        return self.decode_preview(path, 16_000)

    def can_decode_region(self) -> bool:
        """Return True if the decoder supports efficient region decoding."""
        return False

    def preferred_tile_size(self) -> int:
        """Preferred tile size in pixels for tiled mode."""
        return 512
