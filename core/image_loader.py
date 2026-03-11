"""Central image loading coordinator."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImage

from .decoder_base import BaseDecoder, ImageMetadata
from .decoder_pillow import PillowDecoder
from .decoder_psd import PsdDecoder
from .decoder_raw import RawDecoder
from .decoder_fits import FitsDecoder
from .decoder_video import VideoDecoder
from .memory_estimator import MemoryEstimator
from .large_image_strategy import LargeImageStrategy, LoadMode, TiledImageProvider
from .cache_manager import CacheManager

log = logging.getLogger(__name__)


@dataclass
class ImageHandle:
    """
    Lightweight descriptor returned after initial load decision.

    The actual pixel data is NOT stored here — it lives in the cache.
    """
    path: Path
    metadata: ImageMetadata
    mode: LoadMode
    decoder: BaseDecoder
    tiled_provider: Optional[TiledImageProvider] = None
    preview: Optional[QImage] = None


class ImageLoader:
    """
    Selects the best decoder, estimates memory, and returns an ImageHandle.

    Thread-safe: instances can be shared across workers, but each call
    to ``load()`` is independent.
    """

    # Registry of available decoders (ordered by priority)
    _DECODER_CLASSES: list[type[BaseDecoder]] = [
        FitsDecoder,
        RawDecoder,
        PsdDecoder,
        PillowDecoder,
        VideoDecoder,
    ]

    def __init__(
        self,
        cache: Optional[CacheManager] = None,
        strategy: Optional[LargeImageStrategy] = None,
        preview_size: int = 2048,
    ) -> None:
        self._decoders: list[BaseDecoder] = [cls() for cls in self._DECODER_CLASSES]
        self._cache = cache or CacheManager()
        self._strategy = strategy or LargeImageStrategy()
        self._preview_size = preview_size

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def load(self, path: Path | str) -> ImageHandle:
        """
        Main entry point.

        1. Choose decoder via ``probe()``
        2. Read lightweight metadata
        3. Estimate memory
        4. Decide load mode
        5. Decode preview (cached)
        6. Return ``ImageHandle``
        """
        path = Path(path)
        decoder = self._select_decoder(path)
        log.debug("Selected decoder %s for %s", type(decoder).__name__, path.name)

        metadata = decoder.read_metadata(path)
        mode = self._strategy.choose_mode(metadata.width, metadata.height)
        log.debug(
            "Image %s: %dx%d, mode=%s, est=%.1f MB",
            path.name, metadata.width, metadata.height, mode.name,
            MemoryEstimator.estimate_mb(metadata.width, metadata.height),
        )

        # If full-res is already cached, use it directly to avoid preview→fullres flicker
        fullres_cached = self._cache.get((str(path), "fullres"))
        preview = fullres_cached if fullres_cached is not None else self._get_preview(path, decoder)

        tiled_provider = None
        if mode == LoadMode.TILED:
            tiled_provider = TiledImageProvider(
                path=path,
                decode_region_fn=decoder.decode_region,
                tile_size=decoder.preferred_tile_size(),
            )

        return ImageHandle(
            path=path,
            metadata=metadata,
            mode=mode,
            decoder=decoder,
            tiled_provider=tiled_provider,
            preview=preview,
        )

    def load_full(self, path: Path | str) -> QImage:
        """Return full-resolution image from cache, or decode and cache it."""
        path = Path(path)
        cache_key = (str(path), "fullres")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        decoder = self._select_decoder(path)
        image = decoder.decode_full(path)
        size_bytes = image.sizeInBytes() if not image.isNull() else 0
        self._cache.put(cache_key, image, size_bytes)
        return image

    def read_metadata(self, path: Path | str) -> ImageMetadata:
        """Read lightweight metadata without decoding pixels."""
        path = Path(path)
        return self._select_decoder(path).read_metadata(path)

    def has_fullres(self, path: Path | str) -> bool:
        """Return True if the full-resolution image is already in cache."""
        return self._cache.get((str(Path(path)), "fullres")) is not None

    def prefetch(self, path: Path | str) -> None:
        """
        Prefetch preview into cache.  Meant to be called from a background
        thread; returns immediately if the entry is already cached.
        """
        path = Path(path)
        cache_key = (str(path), self._preview_size)
        if self._cache.get(cache_key) is not None:
            return
        log.debug("Prefetching %s", path.name)
        try:
            decoder = self._select_decoder(path)
            self._get_preview(path, decoder)
        except Exception:
            log.debug("Prefetch failed for %s", path.name, exc_info=True)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _select_decoder(self, path: Path) -> BaseDecoder:
        """Return the decoder with the highest probe confidence."""
        best_decoder = self._decoders[0]
        best_score = -1.0
        for decoder in self._decoders:
            score = decoder.probe(path)
            if score > best_score:
                best_score = score
                best_decoder = decoder
        return best_decoder

    def _get_preview(self, path: Path, decoder: BaseDecoder) -> QImage:
        """Return preview from cache or decode it freshly."""
        cache_key = (str(path), self._preview_size)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        preview = decoder.decode_preview(path, self._preview_size)
        size_bytes = preview.sizeInBytes() if not preview.isNull() else 0
        self._cache.put(cache_key, preview, size_bytes)
        return preview
