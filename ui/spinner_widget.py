"""Small animated spinner overlay — no external assets required."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath
from PySide6.QtWidgets import QWidget


class SpinnerWidget(QWidget):
    """
    Circular arc spinner drawn via QPainter.

    Follows the same widget flags as OverlayBar so it renders correctly on
    Windows: WA_NoSystemBackground + FramelessWindowHint, solid dark background
    painted in paintEvent.  Call ``start()`` / ``stop()`` to show/hide.
    """

    _SIZE      = 28
    _THICKNESS = 2.5
    _ARC_SPAN  = 270   # degrees of arc visible
    _STEP      = 6     # degrees rotated per tick
    _INTERVAL  = 16    # ms per tick ≈ 60 fps

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(self._SIZE, self._SIZE)

        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL)
        self._timer.timeout.connect(self._tick)
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self._angle = 0
        self.raise_()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _tick(self) -> None:
        self._angle = (self._angle + self._STEP) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Solid fill (WA_NoSystemBackground means we must paint the whole rect)
        p.fillRect(self.rect(), QColor(18, 18, 18))

        # Clip to rounded rect for the pill shape
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 6.0, 6.0)
        p.setClipPath(clip)

        t = self._THICKNESS
        margin = t + 4.0
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)

        # Background track
        pen = QPen(QColor(255, 255, 255, 40))
        pen.setWidthF(t)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawEllipse(rect)

        # Spinning arc (light-blue matches the overlay bar accent colour)
        pen.setColor(QColor(180, 210, 255, 230))
        p.setPen(pen)
        p.drawArc(rect, int(-self._angle * 16), int(-self._ARC_SPAN * 16))
        p.end()
