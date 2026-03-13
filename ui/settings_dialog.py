"""Application settings dialog."""
from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from utils.settings_manager import SettingsManager

if TYPE_CHECKING:
    from app import Pix42App

def _make_style(theme: str) -> str:
    if theme == "light":
        return """
QDialog { background: #f0f0f0; }
QTabWidget::pane { border: 1px solid #ccc; background: #fafafa; }
QTabBar::tab {
    background: #e0e0e0; color: #555;
    padding: 6px 18px; border: 1px solid #ccc;
    border-bottom: none; border-radius: 4px 4px 0 0;
}
QTabBar::tab:selected  { background: #fafafa; color: #111; }
QTabBar::tab:hover:!selected { background: #d0d0d0; color: #333; }
QLabel { color: #333; background: transparent; }
QLabel#sectionHeader {
    color: #666; font-size: 11px; font-weight: bold;
    border-bottom: 1px solid #ccc; padding-bottom: 2px;
}
QCheckBox { color: #333; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #aaa; border-radius: 3px; background: #fff;
}
QCheckBox::indicator:checked  { background: #3a7bd5; border-color: #3a7bd5; }
QCheckBox::indicator:hover     { border-color: #666; }
QComboBox {
    background: #fff; color: #333;
    border: 1px solid #aaa; border-radius: 4px; padding: 2px 6px;
}
QComboBox QAbstractItemView { background: #fff; color: #333; selection-background-color: #3a7bd5; }
QPushButton#okBtn {
    background: #3a7bd5; color: #fff; border: none;
    border-radius: 6px; font-size: 12px; padding: 6px 22px;
}
QPushButton#okBtn:hover   { background: #4a8be5; }
QPushButton#okBtn:pressed { background: #2a6bc5; }
QPushButton#cancelBtn {
    background: #e0e0e0; color: #333;
    border: 1px solid #bbb; border-radius: 6px;
    font-size: 12px; padding: 6px 18px;
}
QPushButton#cancelBtn:hover  { background: #d0d0d0; }
QPushButton#cancelBtn:pressed { background: #bbb; }
QFrame#divider { color: #ccc; }
QLabel#note { color: #888; font-size: 11px; }
"""
    else:
        return """
QDialog { background: #1e1e1e; }
QTabWidget::pane { border: 1px solid #333; background: #252525; }
QTabBar::tab {
    background: #2a2a2a; color: #aaa;
    padding: 6px 18px; border: 1px solid #333;
    border-bottom: none; border-radius: 4px 4px 0 0;
}
QTabBar::tab:selected  { background: #252525; color: #fff; }
QTabBar::tab:hover:!selected { background: #333; color: #ccc; }
QLabel { color: #ccc; background: transparent; }
QLabel#sectionHeader {
    color: #aaa; font-size: 11px; font-weight: bold;
    border-bottom: 1px solid #333; padding-bottom: 2px;
}
QCheckBox { color: #ccc; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #555; border-radius: 3px; background: #2a2a2a;
}
QCheckBox::indicator:checked  { background: #3a7bd5; border-color: #3a7bd5; }
QCheckBox::indicator:hover     { border-color: #888; }
QComboBox {
    background: #2a2a2a; color: #ccc;
    border: 1px solid #555; border-radius: 4px; padding: 2px 6px;
}
QComboBox QAbstractItemView { background: #2e2e2e; color: #ccc; selection-background-color: #3a7bd5; }
QPushButton#okBtn {
    background: #3a7bd5; color: #fff; border: none;
    border-radius: 6px; font-size: 12px; padding: 6px 22px;
}
QPushButton#okBtn:hover   { background: #4a8be5; }
QPushButton#okBtn:pressed { background: #2a6bc5; }
QPushButton#cancelBtn {
    background: #333; color: #ccc;
    border: 1px solid #444; border-radius: 6px;
    font-size: 12px; padding: 6px 18px;
}
QPushButton#cancelBtn:hover  { background: #444; color: #fff; }
QPushButton#cancelBtn:pressed { background: #555; }
QFrame#divider { color: #333; }
QLabel#note { color: #777; font-size: 11px; }
"""


def _swatch_style(color: QColor, theme: str = "dark") -> str:
    border = "#aaa" if theme == "light" else "#555"
    return (
        f"background: {color.name()};"
        f"border: 1px solid {border};"
        "border-radius: 4px;"
    )


class SettingsDialog(QDialog):
    """
    Modal settings dialog.

    Changes to backdrop color are applied live to *viewer* for instant
    preview.  If the user cancels, the original color is restored.
    """

    def __init__(
        self,
        settings: SettingsManager,
        viewer,
        parent=None,
        app: "Optional[Pix42App]" = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._viewer = viewer
        self._app = app

        # Snapshot originals so Cancel can revert
        self._orig_backdrop = QColor(settings.backdrop_color)
        self._orig_confirm_delete_file = settings.confirm_delete_file
        self._orig_confirm_delete_folder = settings.confirm_delete_folder
        self._orig_start_fullscreen = settings.start_fullscreen
        self._orig_restore_last_image = settings.restore_last_image
        self._orig_filmstrip_visible = settings.filmstrip_visible
        self._orig_filmstrip_recursive = settings.filmstrip_recursive
        self._orig_media_start_muted = settings.media_start_muted
        self._orig_close_to_tray = settings.close_to_tray
        self._orig_run_at_startup = settings.run_at_startup
        self._orig_theme = settings.theme

        self._current_backdrop = QColor(settings.backdrop_color)
        self._current_theme = settings.theme

        self.setWindowTitle("Settings")
        self.setFixedSize(420, 470)
        self.setModal(True)
        self.setStyleSheet(_make_style(self._current_theme))
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._appearance_tab(), "Appearance")
        tabs.addTab(self._behavior_tab(), "Behavior")
        tabs.addTab(self._system_tab(), "System")
        root.addWidget(tabs)

        root.addStretch()

        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(div)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self._on_cancel)

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("okBtn")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

    def _appearance_tab(self) -> QWidget:
        tab = QWidget()
        tab.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(12)

        hdr_theme = QLabel("Theme")
        hdr_theme.setObjectName("sectionHeader")
        layout.addWidget(hdr_theme)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(10)
        theme_row.addWidget(QLabel("Color theme:"))
        theme_row.addStretch()

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Dark", "dark")
        self._theme_combo.addItem("Light", "light")
        self._theme_combo.setCurrentIndex(0 if self._current_theme == "dark" else 1)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self._theme_combo)
        layout.addLayout(theme_row)

        layout.addSpacing(8)

        hdr = QLabel("Backdrop")
        hdr.setObjectName("sectionHeader")
        layout.addWidget(hdr)

        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel("Viewer background color:")
        row.addWidget(lbl)
        row.addStretch()

        self._color_swatch = QPushButton()
        self._color_swatch.setFixedSize(64, 24)
        self._color_swatch.setStyleSheet(_swatch_style(self._current_backdrop, self._current_theme))
        self._color_swatch.setToolTip("Click to choose color")
        self._color_swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_swatch.clicked.connect(self._pick_color)
        row.addWidget(self._color_swatch)
        layout.addLayout(row)

        layout.addStretch()
        return tab

    def _behavior_tab(self) -> QWidget:
        tab = QWidget()
        tab.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(12)

        hdr = QLabel("File operations")
        hdr.setObjectName("sectionHeader")
        layout.addWidget(hdr)

        self._confirm_delete_file_cb = QCheckBox("Ask for confirmation before deleting files")
        self._confirm_delete_file_cb.setChecked(self._orig_confirm_delete_file)
        layout.addWidget(self._confirm_delete_file_cb)

        self._confirm_delete_folder_cb = QCheckBox("Ask for confirmation before deleting folders")
        self._confirm_delete_folder_cb.setChecked(self._orig_confirm_delete_folder)
        layout.addWidget(self._confirm_delete_folder_cb)

        layout.addSpacing(8)

        hdr2 = QLabel("Startup")
        hdr2.setObjectName("sectionHeader")
        layout.addWidget(hdr2)

        self._start_fullscreen_cb = QCheckBox("Start in fullscreen mode")
        self._start_fullscreen_cb.setChecked(self._orig_start_fullscreen)
        layout.addWidget(self._start_fullscreen_cb)

        self._restore_last_image_cb = QCheckBox("Restore last viewed image on startup")
        self._restore_last_image_cb.setChecked(self._orig_restore_last_image)
        layout.addWidget(self._restore_last_image_cb)

        self._filmstrip_visible_cb = QCheckBox("Show filmstrip on startup")
        self._filmstrip_visible_cb.setChecked(self._orig_filmstrip_visible)
        layout.addWidget(self._filmstrip_visible_cb)

        layout.addSpacing(8)

        hdr_fs = QLabel("Filmstrip")
        hdr_fs.setObjectName("sectionHeader")
        layout.addWidget(hdr_fs)

        self._filmstrip_recursive_cb = QCheckBox(
            "Show images from current folder and all subdirectories"
        )
        self._filmstrip_recursive_cb.setChecked(self._orig_filmstrip_recursive)
        layout.addWidget(self._filmstrip_recursive_cb)

        layout.addSpacing(8)

        hdr3 = QLabel("Media")
        hdr3.setObjectName("sectionHeader")
        layout.addWidget(hdr3)

        self._media_start_muted_cb = QCheckBox("Start video and audio muted (safe for work)")
        self._media_start_muted_cb.setChecked(self._orig_media_start_muted)
        layout.addWidget(self._media_start_muted_cb)

        layout.addStretch()
        return tab

    def _system_tab(self) -> QWidget:
        tab = QWidget()
        tab.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 8)
        layout.setSpacing(12)

        hdr = QLabel("Background process")
        hdr.setObjectName("sectionHeader")
        layout.addWidget(hdr)

        self._close_to_tray_cb = QCheckBox("Keep running in tray when closing the window")
        self._close_to_tray_cb.setChecked(self._orig_close_to_tray)
        self._close_to_tray_cb.toggled.connect(self._on_tray_toggled)
        layout.addWidget(self._close_to_tray_cb)

        self._run_at_startup_cb = QCheckBox("Launch Pix42 at Windows startup (minimised to tray)")
        self._run_at_startup_cb.setChecked(self._orig_run_at_startup)
        self._run_at_startup_cb.setEnabled(self._orig_close_to_tray)
        layout.addWidget(self._run_at_startup_cb)

        if sys.platform != "win32":
            self._run_at_startup_cb.setVisible(False)

        note = QLabel("When enabled, Pix42 stays loaded in memory so files open instantly.")
        note.setObjectName("note")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()
        return tab

    # ------------------------------------------------------------------ #
    # Actions                                                              #
    # ------------------------------------------------------------------ #

    def _on_tray_toggled(self, checked: bool) -> None:
        self._run_at_startup_cb.setEnabled(checked)
        if not checked:
            self._run_at_startup_cb.setChecked(False)

    def _on_theme_changed(self, index: int) -> None:
        self._current_theme = self._theme_combo.itemData(index)
        if self._app is not None:
            self._app.apply_theme(self._current_theme)
        # Re-style this dialog to match the new theme
        self.setStyleSheet(_make_style(self._current_theme))
        self._color_swatch.setStyleSheet(_swatch_style(self._current_backdrop, self._current_theme))

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(
            self._current_backdrop, self, "Choose backdrop color",
        )
        if not color.isValid():
            return
        self._current_backdrop = color
        self._color_swatch.setStyleSheet(_swatch_style(color, self._current_theme))
        # Live preview
        self._viewer.set_backdrop_color(color)

    def _on_ok(self) -> None:
        self._settings.theme = self._current_theme
        self._settings.backdrop_color = self._current_backdrop.name()
        self._settings.confirm_delete_file = self._confirm_delete_file_cb.isChecked()
        self._settings.confirm_delete_folder = self._confirm_delete_folder_cb.isChecked()
        self._settings.start_fullscreen = self._start_fullscreen_cb.isChecked()
        self._settings.restore_last_image = self._restore_last_image_cb.isChecked()
        self._settings.filmstrip_visible = self._filmstrip_visible_cb.isChecked()
        self._settings.filmstrip_recursive = self._filmstrip_recursive_cb.isChecked()
        self._settings.media_start_muted = self._media_start_muted_cb.isChecked()

        new_tray = self._close_to_tray_cb.isChecked()
        new_startup = self._run_at_startup_cb.isChecked()
        self._settings.close_to_tray = new_tray
        self._settings.run_at_startup = new_startup  # also writes registry

        # Create or destroy the tray icon if the setting changed
        if self._app is not None:
            if new_tray:
                self._app.ensure_tray()
            else:
                self._app.hide_tray()

        self.accept()

    def _on_cancel(self) -> None:
        # Revert live theme and backdrop preview
        if self._current_theme != self._orig_theme and self._app is not None:
            self._app.apply_theme(self._orig_theme)
        self._viewer.set_backdrop_color(self._orig_backdrop)
        self.reject()
