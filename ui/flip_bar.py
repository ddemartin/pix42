"""Non-modal floating bar shown while the flip tool is active."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class FlipBar(QWidget):
    """Floating toolbar for flip mode."""

    flip_h_requested    = Signal()
    flip_v_requested    = Signal()
    cancel_requested    = Signal()
    save_as_requested   = Signal()
    overwrite_requested = Signal()

    _STYLE = """
        QLabel {
            color: #888;
            font-size: 12px;
            padding: 0 2px;
        }
        QPushButton {
            background: rgba(60,60,60,220);
            color: #ccc;
            border: 1px solid #666;
            border-radius: 4px;
            padding: 4px 14px;
            font-size: 12px;
        }
        QPushButton:hover    { background: rgba(90,90,90,240); color: #fff; }
        QPushButton:pressed  { background: rgba(70,120,200,220); }
        QPushButton:checked  { background: rgba(60,120,200,200); color: #fff;
                               border-color: #4a8ccf; }
        QPushButton:disabled { color: #555; border-color: #444; }
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._btn_h         = QPushButton("↔  Flip H", self)
        self._btn_v         = QPushButton("↕  Flip V", self)
        self._sep           = QLabel("|", self)
        self._btn_cancel    = QPushButton("Cancel", self)
        self._btn_save_as   = QPushButton("Save As…", self)
        self._btn_overwrite = QPushButton("Overwrite", self)

        self._btn_h.setCheckable(True)
        self._btn_v.setCheckable(True)
        self._btn_save_as.setEnabled(False)
        self._btn_overwrite.setEnabled(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        lay.addWidget(self._btn_h)
        lay.addWidget(self._btn_v)
        lay.addWidget(self._sep)
        lay.addWidget(self._btn_cancel)
        lay.addWidget(self._btn_save_as)
        lay.addWidget(self._btn_overwrite)

        self.setStyleSheet(self._STYLE)

        self._btn_h.clicked.connect(self._on_flip_h)
        self._btn_v.clicked.connect(self._on_flip_v)
        self._btn_cancel.clicked.connect(self.cancel_requested)
        self._btn_save_as.clicked.connect(self.save_as_requested)
        self._btn_overwrite.clicked.connect(self.overwrite_requested)

    def _on_flip_h(self) -> None:
        self._update_save_buttons()
        self.flip_h_requested.emit()

    def _on_flip_v(self) -> None:
        self._update_save_buttons()
        self.flip_v_requested.emit()

    def _update_save_buttons(self) -> None:
        has_flip = self._btn_h.isChecked() or self._btn_v.isChecked()
        self._btn_save_as.setEnabled(has_flip)
        self._btn_overwrite.setEnabled(has_flip and self._overwrite_allowed)

    def reset(self) -> None:
        self._btn_h.setChecked(False)
        self._btn_v.setChecked(False)
        self._btn_save_as.setEnabled(False)
        self._btn_overwrite.setEnabled(False)
        self._overwrite_allowed = True

    def set_overwrite_allowed(self, allowed: bool) -> None:
        self._overwrite_allowed = allowed
        if not allowed:
            self._btn_overwrite.setEnabled(False)
            self._btn_overwrite.setToolTip("Overwrite not supported for this format")
        else:
            self._btn_overwrite.setToolTip("")

    @property
    def flip_h(self) -> bool:
        return self._btn_h.isChecked()

    @property
    def flip_v(self) -> bool:
        return self._btn_v.isChecked()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 22, 22, 220))
        p.setPen(QColor(75, 75, 75))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
