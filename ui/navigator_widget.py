"""Navigator / minimap widget showing thumbnail + viewport rectangle."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QRectF, Signal, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QMouseEvent
from PySide6.QtWidgets import QWidget


class NavigatorWidget(QWidget):
    """
    Small thumbnail panel with a draggable viewport rectangle.

    The ``pan_requested`` signal carries the new image-space centre
    as a fractional coordinate (0.0–1.0, 0.0–1.0).
    """

    pan_requested = Signal(float, float)   # (cx_frac, cy_frac)

    THUMBNAIL_SIZE = 160

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._thumbnail: Optional[QImage] = None
        self._viewport_rect: QRectF = QRectF()   # fractional coords
        self._dragging: bool = False

        self.setFixedSize(self.THUMBNAIL_SIZE + 4, self.THUMBNAIL_SIZE + 4)
        self.setStyleSheet("background: #1a1a1a; border: 1px solid #444;")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_image(self, image: QImage) -> None:
        """Update thumbnail from a (possibly large) QImage."""
        if image.isNull():
            self._thumbnail = None
        else:
            self._thumbnail = image.scaled(
                self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.update()

    def set_viewport_rect(
        self,
        img_x: float, img_y: float,
        img_w: float, img_h: float,
        full_img_w: float, full_img_h: float,
    ) -> None:
        """
        Update the viewport rectangle shown over the thumbnail.

        All parameters are in image pixels; they will be converted to
        fractional coordinates internally.
        """
        if full_img_w <= 0 or full_img_h <= 0:
            self._viewport_rect = QRectF()
            return
        self._viewport_rect = QRectF(
            img_x / full_img_w,
            img_y / full_img_h,
            img_w / full_img_w,
            img_h / full_img_h,
        )
        self.update()

    # ------------------------------------------------------------------ #
    # Qt events                                                            #
    # ------------------------------------------------------------------ #

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(26, 26, 26))

        if self._thumbnail is None:
            return

        thumb_rect = self._thumbnail.rect()
        offset_x = (self.width()  - thumb_rect.width())  // 2
        offset_y = (self.height() - thumb_rect.height()) // 2
        painter.drawImage(offset_x, offset_y, self._thumbnail)

        if not self._viewport_rect.isEmpty():
            tw = thumb_rect.width()
            th = thumb_rect.height()
            vr = QRectF(
                offset_x + self._viewport_rect.x() * tw,
                offset_y + self._viewport_rect.y() * th,
                self._viewport_rect.width()  * tw,
                self._viewport_rect.height() * th,
            )
            pen = QPen(QColor(80, 160, 255), 1.5)
            painter.setPen(pen)
            painter.drawRect(vr)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._emit_pan(event.position())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._emit_pan(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _emit_pan(self, pos: QPointF) -> None:
        if self._thumbnail is None:
            return
        tw = self._thumbnail.width()
        th = self._thumbnail.height()
        offset_x = (self.width()  - tw) // 2
        offset_y = (self.height() - th) // 2
        cx = (pos.x() - offset_x) / tw
        cy = (pos.y() - offset_y) / th
        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))
        self.pan_requested.emit(cx, cy)
