"""Domain model for a single image entry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImage

from core.decoder_base import ImageMetadata
from core.large_image_strategy import LoadMode


@dataclass
class ImageEntry:
    """
    Represents one image file as tracked by the application.

    Populated progressively: ``metadata`` and ``thumbnail`` are filled
    lazily by background workers.
    """
    path: Path
    metadata: Optional[ImageMetadata] = None
    thumbnail: Optional[QImage] = None
    load_mode: LoadMode = LoadMode.NORMAL
    is_loading: bool = False
    load_error: Optional[str] = None
    is_dir: bool = False

    # ------------------------------------------------------------------ #
    # Convenience properties                                               #
    # ------------------------------------------------------------------ #

    @property
    def filename(self) -> str:
        return self.path.name or self.path.drive or str(self.path)

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @property
    def is_loaded(self) -> bool:
        return self.metadata is not None

    @property
    def display_size(self) -> str:
        """Human-readable file size string."""
        b = self.size_bytes
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.0f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ImageEntry):
            return NotImplemented
        return self.path == other.path
