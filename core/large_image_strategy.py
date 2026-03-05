"""Strategy for handling very large images (tiled/ROI mode)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtGui import QImage

from .memory_estimator import MemoryEstimator


class LoadMode(Enum):
    NORMAL = auto()   # Decode full image into RAM
    TILED  = auto()   # Decode tiles on demand


@dataclass
class TileRequest:
    x: int
    y: int
    width: int
    height: int
    scale: float


class LargeImageStrategy:
    """Decides how to load an image based on its estimated memory footprint."""

    # Default threshold: images larger than this use tiled mode
    DEFAULT_THRESHOLD_MB: float = 512.0

    def __init__(self, threshold_mb: float = DEFAULT_THRESHOLD_MB) -> None:
        self._threshold_bytes = threshold_mb * 1024 * 1024

    def should_use_tiled_mode(self, width: int, height: int, bpp: int = 4) -> bool:
        """Return True when the image exceeds the RAM threshold."""
        estimated = MemoryEstimator.estimate_bytes(width, height, bpp)
        return estimated > self._threshold_bytes

    def choose_mode(self, width: int, height: int, bpp: int = 4) -> LoadMode:
        if self.should_use_tiled_mode(width, height, bpp):
            return LoadMode.TILED
        return LoadMode.NORMAL


class TiledImageProvider:
    """
    Asynchronous tile provider for very large images.

    In tiled mode the viewer requests individual screen tiles via
    ``request_tile()``; this class decodes and caches them.

    TODO: Implement full async tile engine with worker pool.
    """

    def __init__(
        self,
        path: Path,
        decode_region_fn: Callable[[Path, object, float], QImage],
        tile_size: int = 512,
    ) -> None:
        self._path = path
        self._decode_region_fn = decode_region_fn
        self._tile_size = tile_size
        self._cache: dict[tuple, QImage] = {}

    def request_tile(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        scale: float,
    ) -> Optional[QImage]:
        """
        Return a QImage for the requested region.

        Currently synchronous — async dispatch is a future enhancement.
        Returns None if the tile is not yet ready (future async mode).
        """
        key = (x, y, width, height, scale)
        if key in self._cache:
            return self._cache[key]

        from .decoder_base import Region
        region = Region(x=x, y=y, width=width, height=height)
        tile = self._decode_region_fn(self._path, region, scale)
        self._cache[key] = tile
        return tile

    def invalidate_cache(self) -> None:
        self._cache.clear()

    @property
    def tile_size(self) -> int:
        return self._tile_size
