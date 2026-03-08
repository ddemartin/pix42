"""Non-modal floating bar shown while the crop tool is active."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class CropBar(QWidget):
    """Floating confirmation toolbar for crop mode."""

    cancel_requested = Signal()
    save_as_requested = Signal()
    overwrite_requested = Signal()

    _STYLE = """
        QLabel {
            color: #ccc;
            font-size: 12px;
            padding: 0 4px;
        }
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overwrite_allowed = True

        self._lbl = QLabel("Draw a selection to crop", self)
        self._btn_cancel    = QPushButton("Cancel", self)
        self._btn_save_as   = QPushButton("Save As…", self)
        self._btn_overwrite = QPushButton("Overwrite", self)
        self._btn_save_as.setEnabled(False)
        self._btn_overwrite.setEnabled(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        lay.addWidget(self._lbl)
        lay.addStretch()
        lay.addWidget(self._btn_cancel)
        lay.addWidget(self._btn_save_as)
        lay.addWidget(self._btn_overwrite)

        self.setStyleSheet(self._STYLE)

        self._btn_cancel.clicked.connect(self.cancel_requested)
        self._btn_save_as.clicked.connect(self.save_as_requested)
        self._btn_overwrite.clicked.connect(self.overwrite_requested)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 22, 22, 220))
        p.setPen(QColor(75, 75, 75))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def update_selection(self, w: int, h: int) -> None:
        self._lbl.setText(f"Selection: {w} × {h} px")
        self._btn_save_as.setEnabled(True)
        self._btn_overwrite.setEnabled(self._overwrite_allowed)

    def clear_selection(self) -> None:
        self._lbl.setText("Draw a selection to crop")
        self._btn_save_as.setEnabled(False)
        self._btn_overwrite.setEnabled(False)

    def set_overwrite_allowed(self, allowed: bool) -> None:
        self._overwrite_allowed = allowed
        if not allowed:
            self._btn_overwrite.setEnabled(False)
            self._btn_overwrite.setToolTip("Overwrite not supported for this format")
        else:
            self._btn_overwrite.setToolTip("")
