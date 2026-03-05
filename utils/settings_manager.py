"""Persistent user settings stored in AppData/LumaViewer/settings.ini."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QSettings

from config import config


def _ini_path() -> str:
    """Absolute path to settings.ini inside the user data directory."""
    config.ensure_dirs()
    return str(config.data_dir / "settings.ini")


class SettingsManager:
    """
    Thin wrapper around QSettings (IniFormat).

    Binary blobs (geometry, splitter state) are stored as QByteArray so
    that QSettings IniFormat encodes them correctly as base64 strings.
    Plain Python ``bytes`` round-trips can silently corrupt the data.

    File location: %APPDATA%\\LumaViewer\\settings.ini  (Windows)
                   ~/.local/share/LumaViewer/settings.ini  (Linux/macOS)
    """

    def __init__(self) -> None:
        self._s = QSettings(_ini_path(), QSettings.Format.IniFormat)

    # ------------------------------------------------------------------ #
    # Last folder                                                          #
    # ------------------------------------------------------------------ #

    @property
    def last_folder(self) -> Optional[Path]:
        """Return the last successfully opened folder, or None."""
        raw = self._s.value("general/last_folder", None)
        if raw:
            p = Path(raw)
            return p if p.is_dir() else None
        return None

    @last_folder.setter
    def last_folder(self, folder: Path) -> None:
        self._s.setValue("general/last_folder", str(folder))
        self._s.sync()

    # ------------------------------------------------------------------ #
    # Window geometry & state                                              #
    # ------------------------------------------------------------------ #

    def save_geometry(self, geometry: QByteArray) -> None:
        """Persist window geometry (position, size, screen, maximised state)."""
        self._s.setValue("window/geometry", geometry)
        self._s.sync()

    def load_geometry(self) -> Optional[QByteArray]:
        """Return saved geometry QByteArray, or None if not present."""
        raw = self._s.value("window/geometry", None)
        if raw is None:
            return None
        return raw if isinstance(raw, QByteArray) else QByteArray(raw)

    def save_splitter_state(self, state: QByteArray) -> None:
        self._s.setValue("window/splitter", state)
        self._s.sync()

    def load_splitter_state(self) -> Optional[QByteArray]:
        raw = self._s.value("window/splitter", None)
        if raw is None:
            return None
        return raw if isinstance(raw, QByteArray) else QByteArray(raw)

    # ------------------------------------------------------------------ #
    # View preferences                                                     #
    # ------------------------------------------------------------------ #

    @property
    def stretch_small(self) -> bool:
        return self._s.value("view/stretch_small", True, type=bool)

    @stretch_small.setter
    def stretch_small(self, value: bool) -> None:
        self._s.setValue("view/stretch_small", value)
        self._s.sync()

    # ------------------------------------------------------------------ #
    # Generic helpers                                                      #
    # ------------------------------------------------------------------ #

    def get(self, key: str, default=None):
        return self._s.value(key, default)

    def set(self, key: str, value) -> None:
        self._s.setValue(key, value)
        self._s.sync()

    @property
    def file_path(self) -> str:
        return self._s.fileName()
