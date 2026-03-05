"""Application bootstrap: creates QApplication and wires global services."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QApplication

from config import config, AppConfig, ASSETS_DIR
from utils.logging import setup_logging

log = logging.getLogger(__name__)


class LumaApp:
    """
    Thin wrapper around QApplication.

    Responsible for:
    - setting up logging
    - creating QApplication with correct attributes
    - applying global stylesheet
    - launching the main window
    """

    def __init__(self, argv: list[str], app_config: Optional[AppConfig] = None) -> None:
        self._cfg = app_config or config
        self._cfg.ensure_dirs()

        setup_logging(
            level=getattr(logging, self._cfg.log_level, logging.INFO),
            log_file=self._cfg.data_dir / "viewer.log",
        )
        log.info("Starting Luma Viewer")

        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
        self._qapp = QApplication(argv)
        self._qapp.setApplicationName("Luma Viewer")
        self._qapp.setOrganizationName("LumaViewer")
        self._qapp.setStyle("Fusion")
        self._apply_dark_palette()
        self._apply_stylesheet()
        self._apply_app_icon()

        QThreadPool.globalInstance().setMaxThreadCount(
            self._cfg.loader.thread_pool_size
        )

        from ui.main_window import MainWindow
        self._window = MainWindow()

    def run(self, open_path: Optional[Path] = None) -> int:
        """Show the window and enter the event loop. Returns exit code."""
        self._window.show()
        if open_path and open_path.exists():
            self._window.open_path(open_path)
        return self._qapp.exec()

    # ------------------------------------------------------------------ #
    # Dark palette                                                         #
    # ------------------------------------------------------------------ #

    def _apply_app_icon(self) -> None:
        from PySide6.QtGui import QIcon
        icon_path = ASSETS_DIR / "app" / "icon.svg"
        if icon_path.exists():
            self._qapp.setWindowIcon(QIcon(str(icon_path)))

    def _apply_dark_palette(self) -> None:
        from PySide6.QtGui import QPalette, QColor
        palette = QPalette()
        dark   = QColor(30,  30,  30)
        mid    = QColor(53,  53,  53)
        light  = QColor(80,  80,  80)
        text   = QColor(220, 220, 220)
        bright = QColor(42, 130, 218)
        link   = QColor(100, 160, 230)

        palette.setColor(QPalette.ColorRole.Window,          dark)
        palette.setColor(QPalette.ColorRole.WindowText,      text)
        palette.setColor(QPalette.ColorRole.Base,            QColor(20, 20, 20))
        palette.setColor(QPalette.ColorRole.AlternateBase,   mid)
        palette.setColor(QPalette.ColorRole.ToolTipBase,     mid)
        palette.setColor(QPalette.ColorRole.ToolTipText,     text)
        palette.setColor(QPalette.ColorRole.Text,            text)
        palette.setColor(QPalette.ColorRole.Button,          mid)
        palette.setColor(QPalette.ColorRole.ButtonText,      text)
        palette.setColor(QPalette.ColorRole.BrightText,      QColor(255, 100, 100))
        palette.setColor(QPalette.ColorRole.Link,            link)
        palette.setColor(QPalette.ColorRole.Highlight,       bright)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        self._qapp.setPalette(palette)

    def _apply_stylesheet(self) -> None:
        self._qapp.setStyleSheet("""
            QToolTip {
                color: #e8e8e8;
                background-color: #3c3c3c;
                border: 1px solid #666;
                padding: 4px 8px;
                border-radius: 3px;
                font-size: 12px;
            }
            QSplitter::handle {
                background: #444;
            }
            QSplitter::handle:hover {
                background: #2a82da;
            }
            QScrollBar:vertical {
                background: #252525;
                width: 10px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #505050;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6a6a6a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #252525;
                height: 10px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: #505050;
                border-radius: 4px;
                min-width: 24px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #6a6a6a;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            QMenuBar {
                background: #2a2a2a;
                color: #d8d8d8;
                border-bottom: 1px solid #444;
            }
            QMenuBar::item:selected {
                background: #3a3a3a;
            }
            QMenu {
                background: #2e2e2e;
                color: #d8d8d8;
                border: 1px solid #555;
            }
            QMenu::item:selected {
                background: #2a82da;
                color: #fff;
            }
            QStatusBar {
                background: #272727;
                color: #b0b0b0;
                border-top: 1px solid #3a3a3a;
            }
        """)
