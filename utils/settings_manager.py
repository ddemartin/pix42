"""Persistent user settings stored in AppData/Pix42/settings.ini."""
from __future__ import annotations

import sys
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

    File location: %APPDATA%\\Pix42\\settings.ini  (Windows)
                   ~/.local/share/Pix42/settings.ini  (Linux/macOS)
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

    @property
    def last_image(self) -> Optional[Path]:
        """Return the last viewed image file, or None if missing/not set."""
        raw = self._s.value("general/last_image", None)
        if raw:
            p = Path(raw)
            return p if p.is_file() else None
        return None

    @last_image.setter
    def last_image(self, path: Path) -> None:
        self._s.setValue("general/last_image", str(path))
        self._s.sync()

    @property
    def restore_last_image(self) -> bool:
        return self._s.value("behavior/restore_last_image", False, type=bool)

    @restore_last_image.setter
    def restore_last_image(self, value: bool) -> None:
        self._s.setValue("behavior/restore_last_image", value)
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

    @property
    def backdrop_color(self) -> str:
        return self._s.value("view/backdrop_color", "#1e1e1e")

    @backdrop_color.setter
    def backdrop_color(self, value: str) -> None:
        self._s.setValue("view/backdrop_color", value)
        self._s.sync()

    @property
    def theme(self) -> str:
        """UI theme: 'dark' or 'light'."""
        return self._s.value("view/theme", "dark")

    @theme.setter
    def theme(self, value: str) -> None:
        self._s.setValue("view/theme", value)
        self._s.sync()

    @property
    def filmstrip_width(self) -> int:
        return int(self._s.value("view/filmstrip_width", 220, type=int))

    @filmstrip_width.setter
    def filmstrip_width(self, value: int) -> None:
        self._s.setValue("view/filmstrip_width", value)
        self._s.sync()

    @property
    def metadata_panel_width(self) -> int:
        return int(self._s.value("view/metadata_panel_width", 240, type=int))

    @metadata_panel_width.setter
    def metadata_panel_width(self, value: int) -> None:
        self._s.setValue("view/metadata_panel_width", value)
        self._s.sync()

    @property
    def metadata_panel_visible(self) -> bool:
        return self._s.value("view/metadata_panel_visible", False, type=bool)

    @metadata_panel_visible.setter
    def metadata_panel_visible(self, value: bool) -> None:
        self._s.setValue("view/metadata_panel_visible", value)
        self._s.sync()

    # ------------------------------------------------------------------ #
    # Behaviour preferences                                                #
    # ------------------------------------------------------------------ #

    @property
    def confirm_delete_file(self) -> bool:
        return self._s.value("behavior/confirm_delete_file", True, type=bool)

    @confirm_delete_file.setter
    def confirm_delete_file(self, value: bool) -> None:
        self._s.setValue("behavior/confirm_delete_file", value)
        self._s.sync()

    @property
    def confirm_delete_folder(self) -> bool:
        return self._s.value("behavior/confirm_delete_folder", True, type=bool)

    @confirm_delete_folder.setter
    def confirm_delete_folder(self, value: bool) -> None:
        self._s.setValue("behavior/confirm_delete_folder", value)
        self._s.sync()

    @property
    def start_fullscreen(self) -> bool:
        return self._s.value("behavior/start_fullscreen", False, type=bool)

    @start_fullscreen.setter
    def start_fullscreen(self, value: bool) -> None:
        self._s.setValue("behavior/start_fullscreen", value)
        self._s.sync()

    @property
    def filmstrip_visible(self) -> bool:
        return self._s.value("behavior/filmstrip_visible", False, type=bool)

    @filmstrip_visible.setter
    def filmstrip_visible(self, value: bool) -> None:
        self._s.setValue("behavior/filmstrip_visible", value)
        self._s.sync()

    @property
    def filmstrip_recursive(self) -> bool:
        return self._s.value("behavior/filmstrip_recursive", False, type=bool)

    @filmstrip_recursive.setter
    def filmstrip_recursive(self, value: bool) -> None:
        self._s.setValue("behavior/filmstrip_recursive", value)
        self._s.sync()

    # ------------------------------------------------------------------ #
    # Media                                                                #
    # ------------------------------------------------------------------ #

    @property
    def media_volume(self) -> int:
        return int(self._s.value("media/volume", 80, type=int))

    @media_volume.setter
    def media_volume(self, value: int) -> None:
        self._s.setValue("media/volume", value)
        self._s.sync()

    @property
    def media_start_muted(self) -> bool:
        return self._s.value("media/start_muted", False, type=bool)

    @media_start_muted.setter
    def media_start_muted(self, value: bool) -> None:
        self._s.setValue("media/start_muted", value)
        self._s.sync()

    # ------------------------------------------------------------------ #
    # System / daemon                                                      #
    # ------------------------------------------------------------------ #

    @property
    def close_to_tray(self) -> bool:
        return self._s.value("system/close_to_tray", False, type=bool)

    @close_to_tray.setter
    def close_to_tray(self, value: bool) -> None:
        self._s.setValue("system/close_to_tray", value)
        self._s.sync()

    @property
    def run_at_startup(self) -> bool:
        return self._s.value("system/run_at_startup", False, type=bool)

    @run_at_startup.setter
    def run_at_startup(self, value: bool) -> None:
        self._s.setValue("system/run_at_startup", value)
        self._s.sync()
        _apply_startup_registry(value)

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


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _apply_startup_registry(enable: bool) -> None:
    """Add or remove the HKCU Run key so Pix42 starts with Windows (tray mode)."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                # Frozen executable (PyInstaller) or dev interpreter
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}" --tray'
                else:
                    cmd = f'"{sys.executable}" "{Path(__file__).parent.parent / "main.py"}" --tray'
                winreg.SetValueEx(key, "Pix42", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "Pix42")
                except FileNotFoundError:
                    pass
    except Exception:
        pass
