"""Central image display widget with smooth pan/zoom."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QSize, Signal
from PySide6.QtGui import (
    QAction, QImage, QKeyEvent, QMouseEvent, QMovie, QPainter, QPainterPath,
    QWheelEvent, QResizeEvent, QColor, QBrush,
)
from PySide6.QtWidgets import QMenu, QWidget

log = logging.getLogger(__name__)


class ImageViewer(QWidget):
    """
    Smooth pan/zoom image display widget.

    Zoom model
    ----------
    ``zoom_effective = base_scale_fit * user_zoom``

    - ``base_scale_fit`` is recomputed on resize / image change so that
      the image always fills the viewport in fit mode.
    - ``user_zoom`` is a pure multiplier controlled by the user (default 1.0).

    Signals
    -------
    zoom_changed(float)  -- emitted with effective zoom level
    pan_changed()        -- emitted when the viewport offset changes
    """

    zoom_changed = Signal(float)
    pan_changed = Signal()
    delete_requested = Signal()

    ZOOM_STEP = 1.25
    ZOOM_MIN = 0.02
    ZOOM_MAX = 32.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._base_scale_fit: float = 1.0
        self._user_zoom: float = 1.0
        self._fit_mode: bool = True
        self._offset: QPointF = QPointF(0.0, 0.0)   # top-left of image in widget coords
        self._last_mouse: Optional[QPoint] = None
        self._native_w: int = 0  # original image dimensions (for correct zoom display)
        self._native_h: int = 0

        self._stretch_small: bool = True
        self._movie: Optional[QMovie] = None

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(QSize(200, 200))
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_native_size(self, w: int, h: int) -> None:
        """Set the original image dimensions for correct zoom reporting."""
        self._native_w = w
        self._native_h = h

    def load_image(self, image: QImage) -> None:
        """Display *image* in fit-to-window mode."""
        self._stop_movie()
        self._image = image
        self._user_zoom = 1.0
        self._fit_mode = True
        self._recompute_fit()
        self.update()

    def refine_image(self, image: QImage) -> None:
        """Swap in a higher-resolution version without touching zoom or pan."""
        if (not self._fit_mode
                and self._image is not None
                and not self._image.isNull()
                and image.width() > 0):
            # Compensate for the new image dimensions so that the rendered
            # pixel size on screen stays identical (no zoom jump, no pan shift).
            self._base_scale_fit *= self._image.width() / image.width()
        self._image = image
        if self._fit_mode:
            self._recompute_fit()
        self.update()
        self.zoom_changed.emit(self._native_zoom())

    def load_movie(self, movie: QMovie) -> None:
        """Display an animated GIF or WebP."""
        self._stop_movie()
        self._movie = movie
        movie.jumpToFrame(0)
        frame = movie.currentImage()
        movie.updated.connect(self._on_movie_frame)
        movie.start()
        self._user_zoom = 1.0
        self._fit_mode = True
        if not frame.isNull():
            self._image = frame
            self._recompute_fit()
        self.update()

    def clear(self) -> None:
        """Remove the current image."""
        self._stop_movie()
        self._image = None
        self.update()

    def set_stretch_small(self, enabled: bool) -> None:
        """If *enabled*, small images are upscaled to fill the viewport.
        If False, images smaller than the viewport are shown at 1:1."""
        self._stretch_small = enabled
        if self._fit_mode:
            self._recompute_fit()
            self.update()
            self.zoom_changed.emit(self._native_zoom())

    def set_fit_mode(self) -> None:
        """Scale image to fill the viewport."""
        self._fit_mode = True
        self._user_zoom = 1.0
        self._recompute_fit()
        self.update()
        self.zoom_changed.emit(self._native_zoom())

    def set_one_to_one(self) -> None:
        """Display image at 100% (1 native pixel = 1 screen pixel)."""
        if self._image is None:
            return
        self._fit_mode = False
        self._user_zoom = 1.0
        # Scale so that 1 native pixel maps to 1 screen pixel.
        # If native dims are unknown, fall back to 1 image-pixel = 1 screen pixel.
        if self._native_w > 0 and not self._image.isNull():
            self._base_scale_fit = self._image.width() / self._native_w
        else:
            self._base_scale_fit = 1.0
        self._center_image()
        self.update()
        self.zoom_changed.emit(self._native_zoom())

    def zoom_in(self) -> None:
        """Zoom in by one step, centred on the viewport centre."""
        self._zoom_by(self.ZOOM_STEP, self._viewport_center())

    def zoom_out(self) -> None:
        """Zoom out by one step, centred on the viewport centre."""
        self._zoom_by(1.0 / self.ZOOM_STEP, self._viewport_center())

    @property
    def effective_zoom(self) -> float:
        """Zoom relative to native image dimensions (what the user sees)."""
        return self._native_zoom()

    def viewport_image_rect(self) -> QRectF:
        """Return the visible area expressed in image-pixel coordinates."""
        if self._image is None or self._image.isNull():
            return QRectF()
        zoom = self._render_zoom()
        if zoom == 0.0:
            return QRectF()
        return QRectF(
            -self._offset.x() / zoom,
            -self._offset.y() / zoom,
            self.width()  / zoom,
            self.height() / zoom,
        )

    def center_on_fraction(self, cx: float, cy: float) -> None:
        """Pan so the fractional image point (cx, cy) is centred in the viewport."""
        if self._image is None or self._image.isNull():
            return
        zoom = self._render_zoom()
        self._offset = QPointF(
            self.width()  / 2.0 - cx * self._image.width()  * zoom,
            self.height() / 2.0 - cy * self._image.height() * zoom,
        )
        self._fit_mode = False
        self.update()
        self.pan_changed.emit()

    # ------------------------------------------------------------------ #
    # Qt event handlers                                                    #
    # ------------------------------------------------------------------ #

    def resizeEvent(self, event: QResizeEvent) -> None:
        if self._fit_mode:
            self._recompute_fit()
        super().resizeEvent(event)
        self.pan_changed.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Background
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if self._image is None or self._image.isNull():
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image")
            return

        zoom = self._render_zoom()
        scaled_w = self._image.width() * zoom
        scaled_h = self._image.height() * zoom

        target = QRectF(self._offset.x(), self._offset.y(), scaled_w, scaled_h)
        source = QRectF(0, 0, self._image.width(), self._image.height())
        painter.drawImage(target, self._image, source)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = self.ZOOM_STEP if delta > 0 else 1.0 / self.ZOOM_STEP
        cursor_pos = event.position()
        self._zoom_by(factor, cursor_pos)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_mouse is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.pos() - self._last_mouse
            self._offset += QPointF(delta.x(), delta.y())
            self._last_mouse = event.pos()
            self._fit_mode = False
            self.update()
            self.pan_changed.emit()
        super().mouseMoveEvent(event)  # propagate so ViewerContainer sees the move

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse = None

    def contextMenuEvent(self, event) -> None:
        if self._image is None or self._image.isNull():
            return
        menu = QMenu(self)
        delete_act = QAction("Move to Trash", self)
        delete_act.triggered.connect(self.delete_requested)
        menu.addAction(delete_act)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif key == Qt.Key.Key_Minus:
            self.zoom_out()
        elif key == Qt.Key.Key_0:
            self.set_fit_mode()
        elif key == Qt.Key.Key_1:
            self.set_one_to_one()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _on_movie_frame(self, rect) -> None:
        self._image = self._movie.currentImage()
        self.update()

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            try:
                self._movie.updated.disconnect(self._on_movie_frame)
            except RuntimeError:
                pass
            self._movie = None

    def _render_zoom(self) -> float:
        """Screen pixels per image pixel — used for all geometry and rendering."""
        return self._base_scale_fit * self._user_zoom

    def _native_zoom(self) -> float:
        """Screen pixels per NATIVE pixel — reported to the user as zoom level."""
        rz = self._render_zoom()
        if self._native_w > 0 and self._image is not None and not self._image.isNull():
            return rz * self._image.width() / self._native_w
        return rz

    def _recompute_fit(self) -> None:
        """Recalculate base_scale_fit so the image fills the viewport."""
        if self._image is None or self._image.isNull():
            self._base_scale_fit = 1.0
            return
        vw, vh = self.width(), self.height()
        iw, ih = self._image.width(), self._image.height()
        if iw == 0 or ih == 0:
            return
        scale = min(vw / iw, vh / ih)
        if not self._stretch_small:
            scale = min(scale, 1.0)
        self._base_scale_fit = scale
        self._center_image()

    def _center_image(self) -> None:
        """Centre the (scaled) image in the viewport."""
        if self._image is None:
            return
        zoom = self._render_zoom()
        scaled_w = self._image.width() * zoom
        scaled_h = self._image.height() * zoom
        self._offset = QPointF(
            (self.width() - scaled_w) / 2.0,
            (self.height() - scaled_h) / 2.0,
        )

    def _viewport_center(self) -> QPointF:
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    def _zoom_by(self, factor: float, anchor: QPointF) -> None:
        """Zoom by *factor* keeping *anchor* point stationary."""
        new_zoom = self._user_zoom * factor
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, new_zoom))
        actual_factor = new_zoom / self._user_zoom
        self._user_zoom = new_zoom
        self._fit_mode = False

        # Adjust offset so the anchor pixel stays fixed
        self._offset = QPointF(
            anchor.x() - actual_factor * (anchor.x() - self._offset.x()),
            anchor.y() - actual_factor * (anchor.y() - self._offset.y()),
        )
        self.update()
        self.zoom_changed.emit(self._native_zoom())
