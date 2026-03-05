"""Thumbnail grid view using QListView + custom model."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QRect, Signal, QTimer,
)
from PySide6.QtGui import QImage, QColor, QPainter, QFont
from PySide6.QtWidgets import (
    QApplication, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget,
)

from models.folder_model import FolderModel
from models.image_model import ImageEntry

THUMB_SIZE = 128
CELL_SIZE  = THUMB_SIZE + 24   # extra space for filename label


class ThumbnailModel(QAbstractListModel):
    """
    Qt model adapter over FolderModel.

    Thumbnails are displayed via the ``Qt.ItemDataRole.DecorationRole``.
    Missing thumbnails show a placeholder until loaded asynchronously.
    """

    def __init__(self, folder_model: FolderModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._folder = folder_model
        self._placeholder = self._make_placeholder()

    def refresh(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return self._folder.count

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= self._folder.count:
            return None
        entry: ImageEntry = self._folder[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return entry.filename
        if role == Qt.ItemDataRole.DecorationRole:
            return entry.thumbnail if entry.thumbnail else self._placeholder
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(entry.path)
        if role == Qt.ItemDataRole.UserRole:
            return entry
        return None

    def set_thumbnail(self, path: Path, image: QImage) -> None:
        """Called by background loader when a thumbnail is ready."""
        for row in range(self._folder.count):
            if self._folder[row].path == path:
                self._folder[row].thumbnail = image
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                return

    @staticmethod
    def _make_placeholder() -> QImage:
        img = QImage(THUMB_SIZE, THUMB_SIZE, QImage.Format.Format_RGB32)
        img.fill(QColor(50, 50, 50))
        return img


class ThumbnailDelegate(QStyledItemDelegate):
    """Renders a centred thumbnail + filename label."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()
        rect: QRect = option.rect

        entry: ImageEntry = index.data(Qt.ItemDataRole.UserRole)
        is_dir = entry is not None and entry.is_dir
        is_selected = bool(option.state & option.state.State_Selected)

        if is_dir:
            bg_color = QColor(70, 120, 190) if is_selected else QColor(42, 42, 52)
        else:
            bg_color = QColor(60, 110, 180) if is_selected else QColor(35, 35, 35)
        painter.fillRect(rect, bg_color)

        if is_dir:
            is_drive = entry is not None and entry.path.parent == entry.path
            sp = QStyle.StandardPixmap.SP_DriveHDIcon if is_drive else QStyle.StandardPixmap.SP_DirIcon
            icon = QApplication.style().standardIcon(sp)
            icon_size = THUMB_SIZE // 2
            px = icon.pixmap(icon_size, icon_size)
            tx = rect.x() + (rect.width()  - px.width())  // 2
            ty = rect.y() + (rect.height() - 20 - px.height()) // 2
            painter.drawPixmap(tx, ty, px)
        else:
            thumb: QImage = index.data(Qt.ItemDataRole.DecorationRole)
            if thumb and not thumb.isNull():
                scaled = thumb.scaled(
                    THUMB_SIZE, THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                tx = rect.x() + (rect.width()  - scaled.width())  // 2
                ty = rect.y() + (rect.height() - 20 - scaled.height()) // 2
                painter.drawImage(tx, ty, scaled)

        # Filename label
        name: str = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if len(name) > 18:
            name = name[:16] + "…"
        painter.setPen(QColor(200, 200, 200))
        painter.setFont(QFont("sans-serif", 8))
        label_rect = QRect(rect.x(), rect.y() + rect.height() - 18, rect.width(), 18)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, name)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(CELL_SIZE, CELL_SIZE)


class GridView(QListView):
    """
    Thumbnail grid panel.

    Signals
    -------
    image_activated(Path)  -- emitted on single-click or keyboard navigation
    """

    image_activated  = Signal(Path)
    folder_activated = Signal(Path)

    def __init__(
        self,
        folder_model: FolderModel,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._thumb_model = ThumbnailModel(folder_model)
        self._suppress_selection = False   # guard against programmatic selects
        self.setModel(self._thumb_model)
        self.setItemDelegate(ThumbnailDelegate())
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setStyleSheet("background: #1e1e1e; border: none;")
        # Single-click OR keyboard navigation triggers the image
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def refresh(self) -> None:
        self._suppress_selection = True
        self._thumb_model.refresh()
        QTimer.singleShot(0, self._lift_suppress)

    def _lift_suppress(self) -> None:
        self._suppress_selection = False

    def set_thumbnail(self, path: Path, image: QImage) -> None:
        self._thumb_model.set_thumbnail(path, image)

    def select_path(self, path: Path) -> None:
        """Select an item programmatically without triggering image_activated."""
        for row in range(self._thumb_model.rowCount()):
            entry: ImageEntry = self._thumb_model.data(
                self._thumb_model.index(row), Qt.ItemDataRole.UserRole
            )
            if entry and entry.path == path:
                self._suppress_selection = True
                idx = self._thumb_model.index(row)
                self.setCurrentIndex(idx)
                self.scrollTo(idx)
                self._suppress_selection = False
                return

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._suppress_selection or not current.isValid():
            return
        entry: ImageEntry = self._thumb_model.data(current, Qt.ItemDataRole.UserRole)
        if entry:
            if entry.is_dir:
                self.folder_activated.emit(entry.path)
            else:
                self.image_activated.emit(entry.path)
