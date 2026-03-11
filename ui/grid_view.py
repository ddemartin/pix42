"""Thumbnail grid view using QListView + custom model."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QRect, Signal, QTimer, QPoint,
)
from PySide6.QtGui import QImage, QColor, QPainter, QFont, QPen, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QLineEdit, QListView, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QWidget,
)

from models.folder_model import FolderModel
from models.image_model import ImageEntry

THUMB_SIZE = 128
CELL_SIZE  = THUMB_SIZE + 24   # extra space for filename label


class ThumbnailModel(QAbstractListModel):
    """
    Qt model adapter over FolderModel.

    Supports live filtering by filename and/or cached metadata text
    (``ImageEntry.search_text``).  The internal ``_visible`` list holds the
    real FolderModel indices that pass the current filter.
    """

    rename_done  = Signal(Path, Path)  # (old_path, new_path)
    rename_error = Signal(str)

    def __init__(self, folder_model: FolderModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._folder = folder_model
        self._placeholder = self._make_placeholder()
        self._filter: str = ""
        self._visible: list[int] = []
        self._rebuild_visible()

    # ------------------------------------------------------------------ #
    # Filter                                                               #
    # ------------------------------------------------------------------ #

    def set_filter(self, text: str) -> None:
        self._filter = text.lower().strip()
        self.beginResetModel()
        self._rebuild_visible()
        self.endResetModel()

    def refresh_filter(self) -> None:
        """Re-apply current filter (call after search_text on entries changes)."""
        self.beginResetModel()
        self._rebuild_visible()
        self.endResetModel()

    def _rebuild_visible(self) -> None:
        q = self._filter
        total = self._folder.count
        if not q:
            self._visible = list(range(total))
            return
        vis = []
        for i in range(total):
            entry = self._folder[i]
            if entry.is_dir:
                vis.append(i)
                continue
            if q in entry.filename.lower():
                vis.append(i)
            elif entry.search_text and q in entry.search_text:
                vis.append(i)
        self._visible = vis

    def find_visible_row(self, path: Path) -> int:
        """Return visual row for *path*, or -1 if not currently visible."""
        for vis_row, actual in enumerate(self._visible):
            if self._folder[actual].path == path:
                return vis_row
        return -1

    @property
    def filter_stats(self) -> tuple[int, int]:
        """(visible_files, total_files) — dirs excluded from both counts."""
        total = sum(1 for i in range(self._folder.count) if not self._folder[i].is_dir)
        if not self._filter:
            return total, total
        visible = sum(1 for i in self._visible if not self._folder[i].is_dir)
        return visible, total

    # ------------------------------------------------------------------ #
    # Qt model interface                                                   #
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        self.beginResetModel()
        self._rebuild_visible()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._visible)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._visible):
            return None
        entry: ImageEntry = self._folder[self._visible[index.row()]]

        if role == Qt.ItemDataRole.DisplayRole:
            return entry.filename
        if role == Qt.ItemDataRole.DecorationRole:
            return entry.thumbnail if entry.thumbnail else self._placeholder
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(entry.path)
        if role == Qt.ItemDataRole.UserRole:
            return entry
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        base = super().flags(index)
        if not index.isValid():
            return base
        entry: ImageEntry = self._folder[self._visible[index.row()]]
        if entry and not entry.is_dir:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        entry: ImageEntry = self._folder[self._visible[index.row()]]
        if entry.is_dir:
            return False
        new_stem = str(value).strip()
        if not new_stem or new_stem == entry.path.stem:
            return False
        new_name = new_stem + entry.path.suffix
        new_path = entry.path.parent / new_name
        if new_path.exists():
            self.rename_error.emit(f"'{new_name}' already exists")
            return False
        try:
            entry.path.rename(new_path)
        except OSError as exc:
            self.rename_error.emit(str(exc))
            return False
        old_path = entry.path
        entry.path = new_path
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.UserRole])
        self.rename_done.emit(old_path, new_path)
        return True

    def set_thumbnail(self, path: Path, image: QImage) -> None:
        """Called by background loader when a thumbnail is ready."""
        for actual_row in range(self._folder.count):
            if self._folder[actual_row].path == path:
                self._folder[actual_row].thumbnail = image
                try:
                    vis_row = self._visible.index(actual_row)
                    idx = self.index(vis_row)
                    self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                except ValueError:
                    pass  # item not visible (filtered out)
                return

    @staticmethod
    def _make_placeholder() -> QImage:
        img = QImage(THUMB_SIZE, THUMB_SIZE, QImage.Format.Format_RGB32)
        img.fill(QColor(50, 50, 50))
        return img


class ThumbnailDelegate(QStyledItemDelegate):
    """Renders a centred thumbnail + filename label."""

    def __init__(self, extra_selected: "set[Path]", parent=None):
        super().__init__(parent)
        self._extra_selected = extra_selected

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
        is_extra = entry is not None and not entry.is_dir and entry.path in self._extra_selected

        if is_dir:
            bg_color = QColor(70, 120, 190) if is_selected else QColor(42, 42, 52)
        elif is_extra:
            bg_color = QColor(50, 90, 50)  # green tint for extra-selected
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

        # Checkmark badge for extra-selected items
        if is_extra:
            badge_size = 14
            bx = rect.x() + rect.width() - badge_size - 3
            by = rect.y() + 3
            painter.setBrush(QColor(80, 160, 80))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(bx, by, badge_size, badge_size)
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            cx, cy = bx + badge_size // 2, by + badge_size // 2
            painter.drawLine(cx - 3, cy, cx - 1, cy + 3)
            painter.drawLine(cx - 1, cy + 3, cx + 4, cy - 2)

        painter.restore()

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> Optional[QWidget]:
        entry: ImageEntry = index.data(Qt.ItemDataRole.UserRole)
        if entry is None or entry.is_dir:
            return None
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setStyleSheet("""
            QLineEdit {
                background: #1a3a5c;
                color: #fff;
                border: 1px solid #4a8ccf;
                border-radius: 2px;
                font-size: 9px;
                padding: 0 2px;
            }
        """)
        return editor

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        entry: ImageEntry = index.data(Qt.ItemDataRole.UserRole)
        if entry and not entry.is_dir:
            editor.setText(entry.path.stem)  # type: ignore[attr-defined]
            editor.selectAll()               # type: ignore[attr-defined]

    def setModelData(
        self, editor: QWidget, model: QAbstractListModel, index: QModelIndex
    ) -> None:
        new_stem = editor.text().strip()  # type: ignore[attr-defined]
        if new_stem:
            model.setData(index, new_stem, Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(
        self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        rect = option.rect
        label_rect = QRect(rect.x() + 2, rect.y() + rect.height() - 22, rect.width() - 4, 22)
        editor.setGeometry(label_rect)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(CELL_SIZE, CELL_SIZE)


class GridView(QListView):
    """
    Thumbnail grid panel.

    Signals
    -------
    image_activated(Path)         -- emitted on single-click or keyboard navigation
    multi_selection_changed(list) -- emitted when Ctrl+click selection changes
    """

    image_activated         = Signal(Path)
    folder_activated        = Signal(Path)
    scroll_changed          = Signal()   # emitted (debounced) when scroll position changes
    rename_done             = Signal(Path, Path)  # (old_path, new_path)
    rename_failed           = Signal(str)
    multi_selection_changed = Signal(list)   # list[Path]
    filter_stats_changed    = Signal(int, int)  # (visible_files, total_files)

    def __init__(
        self,
        folder_model: FolderModel,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._thumb_model = ThumbnailModel(folder_model)
        self._suppress_selection = False   # guard against programmatic selects
        self._extra_selected: set[Path] = set()  # Ctrl+click multi-select
        self.setModel(self._thumb_model)
        self.setItemDelegate(ThumbnailDelegate(self._extra_selected))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setStyleSheet("background: #1e1e1e; border: none;")
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        # Single-click OR keyboard navigation triggers the image
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        # Bubble rename signals from the model
        self._thumb_model.rename_done.connect(self.rename_done)
        self._thumb_model.rename_error.connect(self.rename_failed)
        # Debounced scroll → scroll_changed
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(150)
        self._scroll_timer.timeout.connect(self.scroll_changed)
        self.verticalScrollBar().valueChanged.connect(self._scroll_timer.start)

    def refresh(self) -> None:
        self._suppress_selection = True
        self._thumb_model.refresh()
        QTimer.singleShot(0, self._lift_suppress)

    def _lift_suppress(self) -> None:
        self._suppress_selection = False

    def set_thumbnail(self, path: Path, image: QImage) -> None:
        self._thumb_model.set_thumbnail(path, image)

    def get_visible_paths(self) -> list[Path]:
        """Return paths of image entries currently visible in the viewport."""
        vp = self.viewport().rect()
        tl = self.indexAt(vp.topLeft() + QPoint(1, 1))
        br = self.indexAt(vp.bottomRight() - QPoint(1, 1))
        first = tl.row() if tl.isValid() else 0
        last  = br.row() if br.isValid() else self._thumb_model.rowCount() - 1
        # Clamp and include a small buffer row above/below
        first = max(0, first - 1)
        last  = min(self._thumb_model.rowCount() - 1, last + 1)
        paths = []
        for row in range(first, last + 1):
            idx   = self._thumb_model.index(row)
            entry = self._thumb_model.data(idx, Qt.ItemDataRole.UserRole)
            if entry and not entry.is_dir:
                paths.append(entry.path)
        return paths

    def set_filter(self, text: str) -> None:
        """Apply filename/metadata filter and emit updated stats."""
        self._thumb_model.set_filter(text)
        self.filter_stats_changed.emit(*self._thumb_model.filter_stats)

    def refresh_filter(self) -> None:
        """Re-apply current filter after entry.search_text updates."""
        self._thumb_model.refresh_filter()
        self.filter_stats_changed.emit(*self._thumb_model.filter_stats)

    def select_path(self, path: Path) -> None:
        """Select an item programmatically without triggering image_activated."""
        vis_row = self._thumb_model.find_visible_row(path)
        if vis_row >= 0:
            self._suppress_selection = True
            idx = self._thumb_model.index(vis_row)
            self.setCurrentIndex(idx)
            self.scrollTo(idx)
            self._suppress_selection = False

    def start_rename(self) -> None:
        """Trigger inline rename for the currently selected item (if any)."""
        idx = self.currentIndex()
        if idx.isValid():
            self.edit(idx)

    def get_selected_paths(self) -> list[Path]:
        """Return current path + any extra Ctrl+clicked paths."""
        paths: list[Path] = []
        idx = self.currentIndex()
        if idx.isValid():
            entry = self._thumb_model.data(idx, Qt.ItemDataRole.UserRole)
            if entry and not entry.is_dir:
                paths.append(entry.path)
        for p in self._extra_selected:
            if p not in paths:
                paths.append(p)
        return paths

    def clear_extra_selection(self) -> None:
        """Clear Ctrl+click extra selection."""
        if self._extra_selected:
            self._extra_selected.clear()
            self.viewport().update()
            self.multi_selection_changed.emit([])

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            idx = self.indexAt(event.pos())
            if idx.isValid():
                entry = self._thumb_model.data(idx, Qt.ItemDataRole.UserRole)
                if entry and not entry.is_dir:
                    path = entry.path
                    if path in self._extra_selected:
                        self._extra_selected.discard(path)
                    else:
                        self._extra_selected.add(path)
                    self.viewport().update()
                    self.multi_selection_changed.emit(self.get_selected_paths())
            return  # don't navigate on Ctrl+click
        # Normal click: clear extra selection and navigate as usual
        self._extra_selected.clear()
        super().mousePressEvent(event)
        self.multi_selection_changed.emit([])

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._suppress_selection or not current.isValid():
            return
        entry: ImageEntry = self._thumb_model.data(current, Qt.ItemDataRole.UserRole)
        if entry:
            if entry.is_dir:
                self.folder_activated.emit(entry.path)
            else:
                self.image_activated.emit(entry.path)
