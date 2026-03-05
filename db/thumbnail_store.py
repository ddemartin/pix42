"""Persistent thumbnail cache backed by SQLite."""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODeviceBase
from PySide6.QtGui import QImage

from .database import Database


class ThumbnailStore:
    """
    Store and retrieve JPEG thumbnails in SQLite.

    Thumbnails are keyed by file path.  A stored entry is considered
    stale when the file's mtime or size has changed.
    """

    THUMB_SIZE     = 256   # max side length in pixels
    JPEG_QUALITY   = 80

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get(self, path: Path) -> Optional[QImage]:
        """
        Return cached thumbnail if valid (path matches current mtime/size).

        Returns None on cache miss or stale entry.
        """
        try:
            stat = path.stat()
        except OSError:
            return None

        row = self._db.execute(
            "SELECT mtime, size, data FROM thumbnails WHERE path = ?",
            (str(path),),
        ).fetchone()

        if row is None:
            return None
        if abs(row["mtime"] - stat.st_mtime) > 0.01 or row["size"] != stat.st_size:
            return None   # stale

        img = QImage()
        img.loadFromData(bytes(row["data"]))
        return img if not img.isNull() else None

    def put(self, path: Path, image: QImage) -> None:
        """Encode *image* as JPEG and store it in the database."""
        try:
            stat = path.stat()
        except OSError:
            return

        scaled = image.scaled(
            self.THUMB_SIZE, self.THUMB_SIZE,
            1,  # Qt.AspectRatioMode.KeepAspectRatio
            1,  # Qt.TransformationMode.SmoothTransformation
        )

        buf = QByteArray()
        buffer = QBuffer(buf)
        buffer.open(QIODeviceBase.OpenModeFlag.WriteOnly)
        scaled.save(buffer, "JPEG", self.JPEG_QUALITY)
        buffer.close()

        self._db.execute(
            """
            INSERT OR REPLACE INTO thumbnails (path, mtime, size, width, height, data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                stat.st_mtime,
                stat.st_size,
                image.width(),
                image.height(),
                bytes(buf.data()),
            ),
        )
        self._db.commit()

    def invalidate(self, path: Path) -> None:
        """Remove thumbnail for a specific path."""
        self._db.execute("DELETE FROM thumbnails WHERE path = ?", (str(path),))
        self._db.commit()

    def clear_all(self) -> None:
        self._db.execute("DELETE FROM thumbnails")
        self._db.commit()

    def prune_stale(self, max_age_days: float = 30.0) -> int:
        """
        Remove entries older than *max_age_days*.

        Returns the number of rows deleted.
        """
        cutoff = time.time() - max_age_days * 86400
        cur = self._db.execute(
            "DELETE FROM thumbnails WHERE created_at < ?", (cutoff,)
        )
        self._db.commit()
        return cur.rowcount
