"""Floating panel for live image adjustments (brightness, contrast, gamma, saturation)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

_SLIDER_STYLE = """
    QSlider::groove:horizontal {
        height: 4px;
        background: #3a3a3a;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        width: 12px; height: 12px;
        margin: -4px 0;
        border-radius: 6px;
        background: #aaa;
    }
    QSlider::handle:horizontal:hover { background: #fff; }
    QSlider::sub-page:horizontal { background: #4a7ab5; border-radius: 2px; }
"""

_BTN_STYLE = """
    QPushButton {
        background: rgba(60,60,60,220);
        color: #ccc;
        border: 1px solid #666;
        border-radius: 4px;
        padding: 4px 14px;
        font-size: 12px;
    }
    QPushButton:hover   { background: rgba(90,90,90,240); color: #fff; }
    QPushButton:pressed { background: rgba(70,120,200,220); }
    QPushButton:disabled { color: #555; border-color: #444; }
"""


class _SliderRow(QWidget):
    value_changed = Signal(int)

    def __init__(
        self,
        label: str,
        lo: int,
        hi: int,
        default: int,
        fmt_fn=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._default = default
        self._fmt = fmt_fn or (lambda v: f"{v:+d}" if v != 0 else " 0")

        lbl = QLabel(label, self)
        lbl.setFixedWidth(82)
        lbl.setStyleSheet("color: #bbb; font-size: 12px;")

        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setRange(lo, hi)
        self._slider.setValue(default)
        self._slider.setStyleSheet(_SLIDER_STYLE)

        self._val_lbl = QLabel(self._fmt(default), self)
        self._val_lbl.setFixedWidth(46)
        self._val_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._val_lbl.setStyleSheet("color: #eee; font-size: 12px; font-family: monospace;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(lbl)
        lay.addWidget(self._slider, stretch=1)
        lay.addWidget(self._val_lbl)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, v: int) -> None:
        self._val_lbl.setText(self._fmt(v))
        self.value_changed.emit(v)

    def value(self) -> int:
        return self._slider.value()

    def reset(self) -> None:
        self._slider.setValue(self._default)

    def is_default(self) -> bool:
        return self._slider.value() == self._default


class AdjustBar(QWidget):
    """Floating panel for live brightness/contrast/gamma/saturation adjustments."""

    params_changed      = Signal()
    cancel_requested    = Signal()
    save_as_requested   = Signal()
    overwrite_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overwrite_allowed = True

        self._brightness = _SliderRow("Brightness", -100, 100, 0, parent=self)
        self._contrast   = _SliderRow("Contrast",   -100, 100, 0, parent=self)
        self._gamma      = _SliderRow(
            "Gamma", 10, 300, 100,
            fmt_fn=lambda v: f"{v / 100:.2f}",
            parent=self,
        )
        self._saturation = _SliderRow("Saturation", -100, 100, 0, parent=self)

        self._btn_cancel    = QPushButton("Cancel", self)
        self._btn_reset     = QPushButton("Reset All", self)
        self._btn_save_as   = QPushButton("Save As…", self)
        self._btn_overwrite = QPushButton("Overwrite", self)
        for btn in (self._btn_cancel, self._btn_reset, self._btn_save_as, self._btn_overwrite):
            btn.setStyleSheet(_BTN_STYLE)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_reset)
        btn_row.addWidget(self._btn_save_as)
        btn_row.addWidget(self._btn_overwrite)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)
        lay.addWidget(self._brightness)
        lay.addWidget(self._contrast)
        lay.addWidget(self._gamma)
        lay.addWidget(self._saturation)
        lay.addLayout(btn_row)

        for row in (self._brightness, self._contrast, self._gamma, self._saturation):
            row.value_changed.connect(lambda _: self.params_changed.emit())

        self._btn_cancel.clicked.connect(self.cancel_requested)
        self._btn_reset.clicked.connect(self._reset_all)
        self._btn_save_as.clicked.connect(self.save_as_requested)
        self._btn_overwrite.clicked.connect(self.overwrite_requested)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 22, 22, 228))
        p.setPen(QColor(72, 72, 72))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def get_params(self) -> tuple[int, int, int, int]:
        """Return (brightness, contrast, gamma_slider, saturation)."""
        return (
            self._brightness.value(),
            self._contrast.value(),
            self._gamma.value(),
            self._saturation.value(),
        )

    def is_identity(self) -> bool:
        return all(
            r.is_default()
            for r in (self._brightness, self._contrast, self._gamma, self._saturation)
        )

    def set_overwrite_allowed(self, allowed: bool) -> None:
        self._overwrite_allowed = allowed
        self._btn_overwrite.setEnabled(allowed)
        if not allowed:
            self._btn_overwrite.setToolTip("Overwrite not supported for this format")
        else:
            self._btn_overwrite.setToolTip("")

    def _reset_all(self) -> None:
        for row in (self._brightness, self._contrast, self._gamma, self._saturation):
            row.reset()
