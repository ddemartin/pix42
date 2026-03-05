"""Floating overlay toolbar with auto-hide behaviour."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QGraphicsOpacityEffect,
)


class OverlayButton(QPushButton):
    """Flat icon-style button for the overlay bar."""

    _STYLE = """
        QPushButton {
            background: rgba(45, 45, 45, 210);
            border: 1px solid rgba(90, 90, 90, 120);
            border-radius: 4px;
            color: #dcdcdc;
            font-size: 14px;
            padding: 6px 10px;
            min-width: 30px;
        }
        QPushButton:hover {
            background: rgba(70, 115, 185, 230);
            border-color: rgba(120, 160, 220, 180);
            color: #ffffff;
        }
        QPushButton:pressed {
            background: rgba(40, 90, 150, 240);
        }
    """

    _ICON_SIZE = QSize(18, 18)

    def __init__(
        self,
        label: str,
        tooltip: str = "",
        icon_path: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(label, parent)
        self.setToolTip(tooltip)
        self.setStyleSheet(self._STYLE)
        if icon_path and icon_path.exists():
            self.setIcon(QIcon(str(icon_path)))
            self.setIconSize(self._ICON_SIZE)
            self.setText("")


class OverlayBar(QWidget):
    """
    Semi-transparent floating control bar shown over the image viewer.

    Signals
    -------
    prev_requested()
    next_requested()
    zoom_in_requested()
    zoom_out_requested()
    fit_requested()
    one_to_one_requested()
    fullscreen_requested()
    """

    prev_requested       = Signal()
    next_requested       = Signal()
    zoom_in_requested    = Signal()
    zoom_out_requested   = Signal()
    fit_requested        = Signal()
    one_to_one_requested = Signal()
    fullscreen_requested = Signal()

    HIDE_DELAY_MS = 2500
    FADE_DURATION_MS = 300

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade_out)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(self.FADE_DURATION_MS)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet(
            "color: #c0c0c0; font-size: 12px; padding: 4px 8px;"
            "background: rgba(40,40,40,180); border-radius:4px;"
        )

        self._build_layout()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def show_bar(self) -> None:
        """Make the bar visible and restart the hide timer."""
        self._fade_anim.stop()
        self._opacity_effect.setOpacity(1.0)
        self.raise_()
        self.show()
        self._hide_timer.start(self.HIDE_DELAY_MS)

    def set_zoom_label(self, zoom: float) -> None:
        self._zoom_label.setText(f"{zoom * 100:.0f}%")

    def keep_visible(self) -> None:
        """Call on mouse-enter to prevent auto-hide."""
        self._hide_timer.stop()
        self._fade_anim.stop()
        self._opacity_effect.setOpacity(1.0)

    def restart_hide_timer(self) -> None:
        self._hide_timer.start(self.HIDE_DELAY_MS)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _build_layout(self) -> None:
        from config import ASSETS_DIR
        _icons = ASSETS_DIR / "icons" / "overlay"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        buttons: list[tuple[str, str, Signal, Optional[Path]]] = [
            ("◀",  "Previous (←)",  self.prev_requested,        _icons / "prev.svg"),
            ("▶",  "Next (→)",       self.next_requested,        _icons / "next.svg"),
            ("−",  "Zoom out (−)",   self.zoom_out_requested,    _icons / "zoom_out.svg"),
            ("+",  "Zoom in (+)",    self.zoom_in_requested,     _icons / "zoom_in.svg"),
            ("⊡",  "Fit to window",  self.fit_requested,         _icons / "fit.svg"),
            ("1:1","Actual size",    self.one_to_one_requested,  None),
            ("⛶",  "Fullscreen (F)", self.fullscreen_requested,  _icons / "fullscreen.svg"),
        ]

        for label, tip, signal, icon_path in buttons:
            btn = OverlayButton(label, tip, icon_path, self)
            btn.clicked.connect(signal)
            layout.addWidget(btn)

        layout.addSpacing(8)
        layout.addWidget(self._zoom_label)

        self.setLayout(layout)
        self.adjustSize()

    def _start_fade_out(self) -> None:
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_finished(self) -> None:
        if self._opacity_effect.opacity() == 0.0:
            self.hide()

    def enterEvent(self, event) -> None:
        self.keep_visible()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.restart_hide_timer()
        super().leaveEvent(event)
