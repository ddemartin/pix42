"""Application main window."""
from __future__ import annotations

import logging
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QObject, QRect, QRunnable, QThreadPool, QPoint, QSize, QTimer, Signal, QEvent, Slot
from PySide6.QtCore import QFile, QFileSystemWatcher
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QMouseEvent, QMovie
from PySide6.QtWidgets import (
    QMainWindow, QMenu, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStackedWidget, QFileDialog, QMessageBox, QStatusBar, QLabel, QPushButton,
    QLineEdit, QToolBar, QToolButton,
)

from config import config as app_config, ASSETS_DIR
from core.image_loader import ImageLoader, ImageHandle
from core.cache_manager import CacheManager
from db.database import Database
from db.thumbnail_store import ThumbnailStore
from models.folder_model import FolderModel, _MEDIA_EXTENSIONS, _AUDIO_EXTENSIONS
from ui.about_dialog import AboutDialog
from ui.adjust_bar import AdjustBar
from ui.rotate_bar import RotateBar
from ui.crop_bar import CropBar
from ui.settings_dialog import SettingsDialog
from ui.media_player import MediaPlayer
from ui.image_viewer import ImageViewer
from ui.overlay_bar import OverlayBar
from ui.navigator_widget import NavigatorWidget
from ui.grid_view import GridView
from ui.flip_bar import FlipBar
from ui.metadata_panel import MetadataPanel
from ui.resize_bar import ResizeBar
from ui.slideshow_bar import SlideShowBar
from ui.spinner_widget import SpinnerWidget
from utils.threading import LoadImageWorker, ThumbnailWorker, FullResWorker, ThreadWorker
from utils.settings_manager import SettingsManager

log = logging.getLogger(__name__)


def _default_pictures_dir() -> Optional[Path]:
    import os
    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / "Pictures"
            if p.is_dir():
                return p
    return None


_ALWAYS_ANIMATED = frozenset((".gif",))

_CROPPABLE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp",
})

# Same set — PIL can both read and write these formats
_ADJUSTABLE_SUFFIXES = _CROPPABLE_SUFFIXES

# Rotation works for all PIL-writable formats plus animated GIF
_ROTATABLE_SUFFIXES = _CROPPABLE_SUFFIXES | frozenset({".gif"})

# Flip shares the same set as rotation
_FLIPPABLE_SUFFIXES = _ROTATABLE_SUFFIXES

# Resize works for all PIL-writable formats
_RESIZABLE_SUFFIXES = _CROPPABLE_SUFFIXES


# ------------------------------------------------------------------ #
# PIL image-adjustment helpers                                         #
# ------------------------------------------------------------------ #

def _qimage_to_pil(qimage: QImage):
    import numpy as np
    from PIL import Image
    qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)
    w, h = qimage.width(), qimage.height()
    bpl = qimage.bytesPerLine()  # may include padding bytes for 4-byte row alignment
    arr = np.frombuffer(qimage.constBits(), dtype=np.uint8).reshape((h, bpl))
    arr = np.ascontiguousarray(arr[:, : w * 3].reshape((h, w, 3)))
    return Image.fromarray(arr, "RGB")


def _pil_to_qimage(pil_img) -> QImage:
    import numpy as np
    from PIL import Image
    rgb = pil_img.convert("RGB")
    arr = np.ascontiguousarray(rgb)
    h, w, ch = arr.shape
    return QImage(arr.data, w, h, w * ch, QImage.Format.Format_RGB888).copy()


def _xp_encode(s: str) -> bytes:
    """Encode a string to null-terminated UTF-16LE for Windows XP EXIF tags."""
    return (s + "\x00").encode("utf-16-le")


def _write_exif_jpeg(path: Path, fields: dict) -> None:
    """Losslessly insert/update EXIF tags in a JPEG file using piexif."""
    import piexif
    try:
        exif_dict = piexif.load(str(path))
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}
    ifd = exif_dict.setdefault("0th", {})
    if fields.get("title") is not None:
        ifd[piexif.ImageIFD.XPTitle] = _xp_encode(fields["title"])
    if fields.get("description") is not None:
        ifd[piexif.ImageIFD.ImageDescription] = fields["description"].encode("utf-8")
    if fields.get("keywords") is not None:
        ifd[piexif.ImageIFD.XPKeywords] = _xp_encode(fields["keywords"])
    if fields.get("copyright") is not None:
        ifd[piexif.ImageIFD.Copyright] = fields["copyright"].encode("utf-8")
    if fields.get("artist") is not None:
        ifd[piexif.ImageIFD.Artist] = fields["artist"].encode("utf-8")
    piexif.insert(piexif.dump(exif_dict), str(path))


def _write_exif_pillow(path: Path, fields: dict) -> None:
    """Write EXIF tags via Pillow (re-encodes file; lossless for TIFF/PNG/WebP)."""
    from PIL import Image
    with Image.open(path) as img:
        exif = img.getexif()
        if fields.get("title") is not None:
            exif[40091] = _xp_encode(fields["title"])
        if fields.get("description") is not None:
            exif[270] = fields["description"]
        if fields.get("keywords") is not None:
            exif[40094] = _xp_encode(fields["keywords"])
        if fields.get("copyright") is not None:
            exif[33432] = fields["copyright"]
        if fields.get("artist") is not None:
            exif[315] = fields["artist"]
        suffix = path.suffix.lower()
        save_kwargs: dict = {"exif": exif.tobytes()}
        if suffix in {".tif", ".tiff"}:
            save_kwargs["compression"] = "tiff_lzw"
        img.save(path, **save_kwargs)


def _apply_adjustments(pil_img, brightness: int, contrast: int,
                       gamma_slider: int, saturation: int):
    """Apply adjustments to a PIL Image and return the modified copy.

    brightness, contrast, saturation: -100..+100 (0 = no change)
    gamma_slider: 10..300 (100 = gamma 1.0, no change)
    """
    from PIL import ImageEnhance
    img = pil_img.convert("RGB")
    if brightness != 0:
        img = ImageEnhance.Brightness(img).enhance(max(0.0, 1.0 + brightness / 100.0))
    if contrast != 0:
        img = ImageEnhance.Contrast(img).enhance(max(0.01, 1.0 + contrast / 100.0))
    if gamma_slider != 100:
        gamma = gamma_slider / 100.0
        inv_g = 1.0 / gamma
        lut = [min(255, int((i / 255.0) ** inv_g * 255 + 0.5)) for i in range(256)]
        img = img.point(lut * 3)
    if saturation != 0:
        img = ImageEnhance.Color(img).enhance(max(0.0, 1.0 + saturation / 100.0))
    return img


# ------------------------------------------------------------------ #
# Adjustment background worker                                         #
# ------------------------------------------------------------------ #

class _AdjustSignals(QObject):
    done = Signal(int, QImage)  # (sequence, result)


class _AdjustWorker(QRunnable):
    def __init__(self, pil_img, params: tuple, seq: int) -> None:
        super().__init__()
        self._pil    = pil_img
        self._params = params
        self._seq    = seq
        self.signals = _AdjustSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = _apply_adjustments(self._pil, *self._params)
            qimg   = _pil_to_qimage(result)
            self.signals.done.emit(self._seq, qimg)
        except RuntimeError:
            pass
        except Exception:
            pass


# ------------------------------------------------------------------ #
# Resize helpers                                                       #
# ------------------------------------------------------------------ #

def _apply_resize(pil_img, params: dict):
    """Return a resized PIL Image according to *params* from ResizeBar.get_params()."""
    from PIL import Image
    mode_id  = params["mode_id"]
    w, h     = params["w"], params["h"]
    resample = params["resample"]
    ow, oh   = pil_img.width, pil_img.height

    if mode_id == 0:        # Pixels — exact target size
        new_w, new_h = w, h
    elif mode_id == 1:      # Percent
        new_w = max(1, round(ow * w / 100))
        new_h = max(1, round(oh * h / 100))
    else:                   # Max fit — scale to fit within w × h box
        ratio = min(w / ow, h / oh)
        new_w = max(1, round(ow * ratio))
        new_h = max(1, round(oh * ratio))

    return pil_img.resize((new_w, new_h), resample=resample)


def _save_resized(pil_img, dest: Path, src_suffix: str) -> None:
    """Save *pil_img* to *dest* with format-appropriate kwargs."""
    kwargs: dict = {}
    out_sfx = dest.suffix.lower()
    if out_sfx in (".jpg", ".jpeg"):
        kwargs["quality"] = 95
    elif out_sfx in (".tif", ".tiff"):
        kwargs["compression"] = "tiff_lzw"
    pil_img.save(dest, **kwargs)


class _ResizeSignals(QObject):
    finished = Signal(int, int)   # (done_count, error_count)


class _ResizeBatchWorker(QRunnable):
    """Batch-resize a list of (src, dest) pairs in a background thread."""

    def __init__(self, jobs: list, params: dict) -> None:
        super().__init__()
        self._jobs   = jobs    # [(Path src, Path dest), ...]
        self._params = params
        self.signals = _ResizeSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        from PIL import Image
        done = errors = 0
        for src, dest in self._jobs:
            try:
                with Image.open(src) as img:
                    out = _apply_resize(img.copy(), self._params)
                    _save_resized(out, dest, src.suffix.lower())
                done += 1
            except RuntimeError:
                return
            except Exception:
                errors += 1
        try:
            self.signals.finished.emit(done, errors)
        except RuntimeError:
            pass


def _is_animated(path: Path) -> bool:
    """True if *path* should be played as an animation via QMovie."""
    suffix = path.suffix.lower()
    if suffix in _ALWAYS_ANIMATED:
        return True
    if suffix == ".webp":
        try:
            from PIL import Image
            with Image.open(path) as img:
                return getattr(img, "n_frames", 1) > 1
        except Exception:
            pass
    return False


def _fmt_size(n_bytes: int) -> str:
    for unit, threshold in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n_bytes >= threshold:
            return f"{n_bytes / threshold:.1f} {unit}"
    return f"{n_bytes} B"


def _build_meta_search_string(meta: "ImageMetadata") -> str:
    """Combine EXIF/metadata fields into a single lowercase searchable string."""
    exif = meta.exif or {}

    def _xp(v) -> str:
        if isinstance(v, bytes):
            return v.decode("utf-16-le").rstrip("\x00")
        return str(v).rstrip("\x00") if v else ""

    parts = [
        _xp(exif.get("XPTitle", "")),
        str(exif.get("ImageDescription", "") or ""),
        _xp(exif.get("XPKeywords", "")),
        str(exif.get("Copyright", "") or ""),
        str(exif.get("Artist", "") or ""),
        str(exif.get("Make", "") or ""),
        str(exif.get("Model", "") or ""),
    ]
    return " ".join(p.strip() for p in parts if p.strip()).lower()


# ------------------------------------------------------------------ #
# Metadata scan worker                                                  #
# ------------------------------------------------------------------ #

class _MetaScanSignals(QObject):
    meta_ready = Signal(int, str, int)  # (entry_index, search_string, seq)
    finished   = Signal(int)            # seq


class _MetaScanWorker(QRunnable):
    """Read metadata for all files and emit search strings."""

    def __init__(self, folder_model, loader, seq: int, stop: "threading.Event") -> None:
        super().__init__()
        self._entries = list(folder_model)   # snapshot — safe across folder changes
        self._loader  = loader
        self._seq     = seq
        self._stop    = stop
        self.signals  = _MetaScanSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        for i, entry in enumerate(self._entries):
            if self._stop.is_set():
                break
            if entry.is_dir or entry.search_text:
                continue
            try:
                meta = self._loader.read_metadata(entry.path)
                s    = _build_meta_search_string(meta)
                self.signals.meta_ready.emit(i, s, self._seq)
            except RuntimeError:
                return
            except Exception:
                pass
        try:
            self.signals.finished.emit(self._seq)
        except RuntimeError:
            pass


class ExpandedGridOverlay(QWidget):
    """
    Full-window thumbnail browser overlay.

    Covers the entire central area when the user clicks the expand button on
    the filmstrip nav bar. Clicking a thumbnail emits ``image_selected`` and
    the overlay is dismissed; clicking a folder navigates into it.
    """

    image_selected  = Signal(Path)
    folder_selected = Signal(Path)
    close_requested = Signal()
    scroll_changed  = Signal()
    rename_done     = Signal(Path, Path)
    rename_failed   = Signal(str)

    def __init__(self, folder_model: FolderModel, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Header bar
        self._header = QWidget(self)
        self._header.setFixedHeight(36)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(8)

        self._close_btn = QPushButton("✕", self._header)
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setToolTip("Close grid view  (Esc)")
        self._close_btn.clicked.connect(self.close_requested)

        self._folder_lbl = QLabel("", self._header)

        self._search_input = QLineEdit(self._header)
        self._search_input.setPlaceholderText("Search…")
        self._search_input.setFixedWidth(200)
        self._search_input.setFixedHeight(24)

        self._search_count = QLabel("", self._header)
        self._search_count.setStyleSheet("font-size: 10px; min-width: 40px;")

        hl.addWidget(self._close_btn)
        hl.addWidget(self._folder_lbl, stretch=1)
        hl.addWidget(self._search_input)
        hl.addWidget(self._search_count)

        # Grid
        self._theme = "dark"
        self._inner_grid = GridView(folder_model, self)
        self._inner_grid.image_activated.connect(self.image_selected)
        self._inner_grid.folder_activated.connect(self.folder_selected)
        self._inner_grid.scroll_changed.connect(self.scroll_changed)
        self._inner_grid.rename_done.connect(self.rename_done)
        self._inner_grid.rename_failed.connect(self.rename_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._inner_grid, stretch=1)
        self.apply_theme("dark")

    def refresh(self) -> None:
        self._inner_grid.refresh()

    def select_path(self, path: Path) -> None:
        self._inner_grid.select_path(path)

    def set_thumbnail(self, path: Path, image: QImage) -> None:
        self._inner_grid.set_thumbnail(path, image)

    def get_visible_paths(self) -> list[Path]:
        return self._inner_grid.get_visible_paths()

    def start_rename(self) -> None:
        self._inner_grid.start_rename()

    def set_folder_label(self, text: str, tooltip: str = "") -> None:
        self._folder_lbl.setText(text)
        self._folder_lbl.setToolTip(tooltip)

    def set_filter(self, text: str) -> None:
        """Apply filter and sync search box text."""
        self._inner_grid.set_filter(text)
        if self._search_input.text() != text:
            self._search_input.blockSignals(True)
            self._search_input.setText(text)
            self._search_input.blockSignals(False)

    def set_search_count(self, visible: int, total: int) -> None:
        self._search_count.setText(f"{visible}/{total}" if visible != total else "")

    def refresh_filter(self) -> None:
        self._inner_grid.refresh_filter()

    def get_filter_stats(self) -> tuple[int, int]:
        return self._inner_grid._thumb_model.filter_stats

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self._inner_grid.apply_theme(theme)
        if theme == "light":
            hdr_bg, hdr_border = "#e8e8e8", "#ccc"
            close_style = (
                "QPushButton { background: rgba(220,220,220,0.9); color: #444;"
                " border: 1px solid #bbb; border-radius: 4px; font-size: 12px; }"
                "QPushButton:hover { background: rgba(180,50,50,0.9); color: #fff; }"
                "QPushButton:pressed { background: rgba(200,60,60,0.9); }"
            )
            folder_color = "#333"
            search_style = (
                "QLineEdit { background: #fff; color: #222; border: 1px solid #bbb;"
                " border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
                "QLineEdit:focus { border-color: #4a8ccf; }"
            )
            count_color = "#888"
        else:
            hdr_bg, hdr_border = "#252525", "#3a3a3a"
            close_style = (
                "QPushButton { background: rgba(60,60,60,0.9); color: #bbb;"
                " border: 1px solid #555; border-radius: 4px; font-size: 12px; }"
                "QPushButton:hover { background: rgba(180,50,50,0.9); color: #fff; }"
                "QPushButton:pressed { background: rgba(200,60,60,0.9); }"
            )
            folder_color = "#ccc"
            search_style = (
                "QLineEdit { background: #1a1a1a; color: #ddd; border: 1px solid #444;"
                " border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
                "QLineEdit:focus { border-color: #4a8ccf; }"
            )
            count_color = "#666"

        self._header.setStyleSheet(f"background: {hdr_bg}; border-bottom: 1px solid {hdr_border};")
        self._close_btn.setStyleSheet(close_style)
        self._folder_lbl.setStyleSheet(f"color: {folder_color}; font-size: 11px;")
        self._search_input.setStyleSheet(search_style)
        self._search_count.setStyleSheet(f"color: {count_color}; font-size: 10px; min-width: 40px;")
        self.update()

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        bg = QColor(245, 245, 245) if self._theme == "light" else QColor(18, 18, 18)
        painter.fillRect(self.rect(), bg)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._search_input.text():
                self._search_input.clear()
            else:
                self.close_requested.emit()
        elif event.key() == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._search_input.setFocus()
            self._search_input.selectAll()
        else:
            super().keyPressEvent(event)


class ViewerContainer(QWidget):
    """
    Wrapper that holds ImageViewer + OverlayBar + NavigatorWidget overlaid.

    OverlayBar  — bottom centre, shown on mouse movement.
    Hamburger   — top-left, toggles the filmstrip panel.
    NavigatorWidget — top-left, below the hamburger button.
    """

    toggle_filmstrip = Signal()

    _HAMBURGER_SIZE = 28
    _MARGIN = 8

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.viewer       = ImageViewer(self)
        self.media_player = MediaPlayer(self)
        self.overlay      = OverlayBar(self)
        self.navigator    = NavigatorWidget(self)
        self.spinner      = SpinnerWidget(self)
        self.crop_bar      = CropBar(self)
        self.adjust_bar    = AdjustBar(self)
        self.rotate_bar    = RotateBar(self)
        self.flip_bar      = FlipBar(self)
        self.resize_bar    = ResizeBar(self)
        self.slideshow_bar = SlideShowBar(self)
        self.overlay.hide()
        self.crop_bar.hide()
        self.adjust_bar.hide()
        self.rotate_bar.hide()
        self.flip_bar.hide()
        self.resize_bar.hide()
        self.slideshow_bar.hide()

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.viewer)       # index 0
        self._stack.addWidget(self.media_player) # index 1

        self._hamburger = QPushButton("☰", self)
        self._hamburger.setFixedSize(self._HAMBURGER_SIZE, self._HAMBURGER_SIZE)
        self._hamburger.setToolTip("Toggle filmstrip")
        self._hamburger.setStyleSheet("""
            QPushButton {
                background: rgba(30,30,30,0.85);
                color: #bbb;
                border: 1px solid #555;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover   { background: rgba(60,60,60,0.95); color: #fff; }
            QPushButton:pressed { background: rgba(70,120,200,0.9); }
        """)
        self._hamburger.clicked.connect(self.toggle_filmstrip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self.setLayout(layout)
        self.setMouseTracking(True)
        # Intercept mouse moves from viewer regardless of Qt propagation quirks
        self.viewer.installEventFilter(self)

    def show_image_mode(self) -> None:
        self.media_player.stop()
        self._stack.setCurrentWidget(self.viewer)
        self.navigator.show()
        self.navigator.raise_()

    def show_media_mode(self) -> None:
        self.overlay.hide()
        self.navigator.hide()
        self._stack.setCurrentWidget(self.media_player)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_overlays()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewer and event.type() == QEvent.Type.MouseMove:
            if self._stack.currentWidget() is self.viewer:
                self.overlay.show_bar()
                self._reposition_overlays()
        return False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._stack.currentWidget() is self.viewer:
            self.overlay.show_bar()
            self._reposition_overlays()
        super().mouseMoveEvent(event)

    def _reposition_overlays(self) -> None:
        m = self._MARGIN
        # Hamburger — top-left
        hs = self._HAMBURGER_SIZE
        self._hamburger.setGeometry(m, m, hs, hs)
        # Navigator — below hamburger
        nw = self.navigator.width()
        nh = self.navigator.height()
        self.navigator.setGeometry(m, m + hs + m, nw, nh)
        # Bottom-centre toolbar
        ow = self.overlay.sizeHint().width()
        oh = self.overlay.sizeHint().height()
        self.overlay.setGeometry(
            (self.width() - ow) // 2,
            self.height() - oh - 12,
            ow, oh,
        )
        # Spinner — bottom-right corner
        sw = self.spinner.width()
        sh = self.spinner.height()
        self.spinner.setGeometry(self.width() - sw - m, self.height() - sh - m, sw, sh)
        # CropBar — top-centre (only when visible)
        if self.crop_bar.isVisible():
            cw = self.crop_bar.sizeHint().width()
            ch = self.crop_bar.sizeHint().height()
            self.crop_bar.setGeometry((self.width() - cw) // 2, m, cw, ch)
        # AdjustBar — top-centre (only when visible)
        if self.adjust_bar.isVisible():
            aw = max(self.adjust_bar.sizeHint().width(), min(480, self.width() - 40))
            ah = self.adjust_bar.sizeHint().height()
            self.adjust_bar.setGeometry((self.width() - aw) // 2, m, aw, ah)
        # RotateBar — top-centre (only when visible)
        if self.rotate_bar.isVisible():
            rw = self.rotate_bar.sizeHint().width()
            rh = self.rotate_bar.sizeHint().height()
            self.rotate_bar.setGeometry((self.width() - rw) // 2, m, rw, rh)
        # FlipBar — top-centre (only when visible)
        if self.flip_bar.isVisible():
            fw = self.flip_bar.sizeHint().width()
            fh = self.flip_bar.sizeHint().height()
            self.flip_bar.setGeometry((self.width() - fw) // 2, m, fw, fh)
        # ResizeBar — top-centre (only when visible)
        if self.resize_bar.isVisible():
            rw = max(self.resize_bar.sizeHint().width(), min(560, self.width() - 40))
            rh = self.resize_bar.sizeHint().height()
            self.resize_bar.setGeometry((self.width() - rw) // 2, m, rw, rh)
        # SlideShowBar — top-centre (only when visible)
        if self.slideshow_bar.isVisible():
            sw = self.slideshow_bar.sizeHint().width()
            sh = self.slideshow_bar.sizeHint().height()
            self.slideshow_bar.setGeometry((self.width() - sw) // 2, m, sw, sh)


class MainWindow(QMainWindow):
    """
    Top-level application window.

    Layout
    ------
    Left panel  : GridView (filmstrip)
    Centre      : ViewerContainer (ImageViewer + OverlayBar)
    Status bar  : path / zoom / dimensions
    """

    def __init__(self) -> None:
        super().__init__()
        self._settings     = SettingsManager()
        self._folder_model = FolderModel()
        self._cache        = CacheManager(max_ram_entries=64, max_ram_mb=512.0)
        self._loader       = ImageLoader(cache=self._cache)
        _db                = Database(app_config.cache.db_path)
        self._thumb_store  = ThumbnailStore(_db)
        # 1-thread pool for fast preview loading — never blocked by full-res.
        self._preview_pool = QThreadPool()
        self._preview_pool.setMaxThreadCount(1)
        # 1-thread pool for full-resolution refinement.
        self._fullres_pool = QThreadPool()
        self._fullres_pool.setMaxThreadCount(1)
        # Background pool for thumbnail generation.
        self._thumb_pool   = QThreadPool()
        self._thumb_pool.setMaxThreadCount(max(1, QThreadPool.globalInstance().maxThreadCount() - 2))
        # Speculative prefetch pool — kept separate so it never blocks preview loading.
        self._prefetch_pool = QThreadPool()
        self._prefetch_pool.setMaxThreadCount(1)
        # Cancellation token for the current full-res worker.
        self._fullres_cancel: Optional["threading.Event"] = None
        self._current_handle: Optional[ImageHandle] = None
        self._thumbnails_loaded: bool = False
        # Priority queue for thumbnail generation (managed manually).
        self._thumb_queue:    deque[Path] = deque()
        self._thumb_done:     set[Path]   = set()
        self._thumb_inflight: int         = 0
        self._tray_available: bool = False
        self._crop_mode_active: bool = False
        self._adjust_mode_active: bool = False
        self._rotate_mode_active: bool = False
        self._flip_mode_active: bool = False
        self._resize_mode_active: bool = False
        self._slideshow_active: bool = False
        self._slideshow_playing: bool = False
        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.timeout.connect(self._slideshow_advance)
        self._adjust_original_qimage: Optional[QImage] = None
        self._adjust_preview_pil = None   # PIL.Image of displayed frame
        self._adjust_seq: int = 0         # stale-result guard
        # 1-thread pool for adjustment workers (separate from preview/fullres)
        self._adjust_pool = QThreadPool()
        self._adjust_pool.setMaxThreadCount(1)
        self._adjust_timer = QTimer(self)
        self._adjust_timer.setSingleShot(True)
        self._adjust_timer.timeout.connect(self._dispatch_adjust)
        self._app = None  # set by LumaApp after construction
        # Search state
        self._search_meta_mode: bool = False
        self._search_seq: int = 0
        self._search_stop: Optional[threading.Event] = None
        self._search_pool = QThreadPool()
        self._search_pool.setMaxThreadCount(1)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._start_meta_scan)
        self._search_refresh_timer = QTimer(self)
        self._search_refresh_timer.setSingleShot(True)
        self._search_refresh_timer.setInterval(250)
        self._search_refresh_timer.timeout.connect(self._do_search_refresh)

        # Folder watcher: detects files added / removed while the folder is open.
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_dir_changed)
        self._watcher_timer = QTimer(self)
        self._watcher_timer.setSingleShot(True)
        self._watcher_timer.setInterval(500)
        self._watcher_timer.timeout.connect(self._apply_folder_changes)

        self.setWindowTitle("Pix42")
        self.resize(1280, 800)
        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()
        self._restore_session()

    # ------------------------------------------------------------------ #
    # Session save / restore                                               #
    # ------------------------------------------------------------------ #

    def _restore_session(self) -> None:
        """Restore window geometry and last open folder from settings.ini."""
        geom = self._settings.load_geometry()
        if geom:
            self.restoreGeometry(geom)

        stretch = self._settings.stretch_small
        self._stretch_act.setChecked(stretch)
        self._container.viewer.set_stretch_small(stretch)

        self._container.viewer.set_backdrop_color(QColor(self._settings.backdrop_color))

        if self._settings.filmstrip_visible:
            self._left_panel.show()

        if self._settings.metadata_panel_visible:
            self._meta_panel.show()
            self._meta_panel_act.blockSignals(True)
            self._meta_panel_act.setChecked(True)
            self._meta_panel_act.blockSignals(False)

        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._apply_saved_splitter_sizes)

        if self._settings.start_fullscreen:
            self.showFullScreen()

        last_image = self._settings.last_image if self._settings.restore_last_image else None
        last_folder = (
            last_image.parent
            if last_image is not None
            else self._settings.last_folder or _default_pictures_dir()
        )
        if last_folder:
            log.info("Restoring last folder: %s", last_folder)
            self._load_folder_into_model(last_folder)
            self._watch_folder(last_folder)
            if last_image is not None:
                self._folder_model.go_to_path(last_image)
            self._grid.refresh()
            self._thumbnails_loaded = False
            self._update_nav_bar()
            if last_image is not None:
                self._grid.select_path(last_image)
            self._load_current()

    def _apply_saved_splitter_sizes(self) -> None:
        """Apply saved panel widths after the window layout is computed."""
        splitter = self.centralWidget()
        total = sum(splitter.sizes())
        if total <= 0:
            return
        filmstrip_w = self._settings.filmstrip_width if self._left_panel.isVisible() else 0
        meta_w = self._settings.metadata_panel_width if self._meta_panel.isVisible() else 0
        viewer_w = max(200, total - filmstrip_w - meta_w)
        splitter.setSizes([filmstrip_w, viewer_w, meta_w])

    def set_tray_available(self, available: bool) -> None:
        """Called by LumaApp after creating or destroying the tray icon."""
        self._tray_available = available

    def apply_theme(self, theme: str) -> None:
        """Propagate theme change to child widgets that have hardcoded styles."""
        self._grid.apply_theme(theme)
        self._meta_panel.apply_theme(theme)
        self._expanded_overlay.apply_theme(theme)

    def closeEvent(self, event) -> None:
        if self._tray_available and self._settings.close_to_tray:
            # Hide to tray instead of quitting
            event.ignore()
            self.hide()
            return
        # Cancel all pending background work so threads can exit promptly
        self._adjust_timer.stop()
        self._search_timer.stop()
        self._search_refresh_timer.stop()
        self._watcher_timer.stop()
        self._slideshow_timer.stop()
        if self._fullres_cancel is not None:
            self._fullres_cancel.set()
        self._cancel_meta_scan()
        for pool in (
            self._preview_pool, self._fullres_pool,
            self._thumb_pool, self._prefetch_pool, self._adjust_pool,
            self._search_pool,
        ):
            pool.clear()
        self._settings.save_geometry(self.saveGeometry())
        splitter = self.centralWidget()
        if hasattr(splitter, "sizes"):
            sizes = splitter.sizes()
            if len(sizes) == 3:
                if sizes[0] > 0:
                    self._settings.filmstrip_width = sizes[0]
                if sizes[2] > 0:
                    self._settings.metadata_panel_width = sizes[2]
        self._settings.filmstrip_visible = self._left_panel.isVisible()
        super().closeEvent(event)
        # setQuitOnLastWindowClosed(False) is set globally for tray support,
        # so we must quit the event loop explicitly when actually closing.
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # ---- left panel ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Nav bar: [↑]  folder name  [grid]
        _tb_dir = ASSETS_DIR / "icons" / "toolbar"

        def _nav_icon(name: str) -> QIcon:
            p = _tb_dir / name
            return QIcon(str(p)) if p.exists() else QIcon()

        nav_bar = QWidget()
        nav_bar.setFixedHeight(34)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(4, 3, 4, 3)
        nav_layout.setSpacing(4)
        self._nav_up_btn = QPushButton()
        self._nav_up_btn.setIcon(_nav_icon("folder-up.svg"))
        self._nav_up_btn.setIconSize(QSize(20, 20))
        self._nav_up_btn.setFixedSize(28, 28)
        self._nav_up_btn.setToolTip("Go to parent folder")
        self._nav_up_btn.setEnabled(False)
        self._nav_label = QLabel("")
        self._nav_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._nav_expand_btn = QPushButton()
        self._nav_expand_btn.setIcon(_nav_icon("grid.svg"))
        self._nav_expand_btn.setIconSize(QSize(20, 20))
        self._nav_expand_btn.setFixedSize(28, 28)
        self._nav_expand_btn.setToolTip("Open full-window thumbnail browser")
        nav_layout.addWidget(self._nav_up_btn)
        nav_layout.addWidget(self._nav_label, stretch=1)
        nav_layout.addWidget(self._nav_expand_btn)
        left_layout.addWidget(nav_bar)

        # Search bar (below nav bar, hidden by default)
        search_bar = QWidget()
        search_bar.setFixedHeight(28)
        search_bar.setStyleSheet("background: #252525; border-bottom: 1px solid #2e2e2e;")
        sl = QHBoxLayout(search_bar)
        sl.setContentsMargins(4, 3, 4, 3)
        sl.setSpacing(2)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setStyleSheet("""
            QLineEdit {
                background: #1a1a1a; color: #ddd; border: 1px solid #3a3a3a;
                border-radius: 3px; padding: 1px 5px; font-size: 11px;
            }
            QLineEdit:focus { border-color: #4a8ccf; }
        """)
        self._search_meta_btn = QPushButton("M")
        self._search_meta_btn.setFixedSize(20, 20)
        self._search_meta_btn.setCheckable(True)
        self._search_meta_btn.setToolTip("Include metadata in search")
        self._search_meta_btn.setStyleSheet("""
            QPushButton { background: #2a2a2a; color: #888; border: 1px solid #3a3a3a;
                          border-radius: 3px; font-size: 10px; font-weight: bold; }
            QPushButton:checked { background: #1a4a7a; color: #4af; border-color: #4a8ccf; }
            QPushButton:hover   { color: #ccc; }
        """)
        self._search_clear_btn = QPushButton("✕")
        self._search_clear_btn.setFixedSize(20, 20)
        self._search_clear_btn.setToolTip("Clear search")
        self._search_clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #666; border: none; font-size: 11px; }"
            "QPushButton:hover { color: #ccc; }"
        )
        self._search_count_lbl = QLabel("")
        self._search_count_lbl.setStyleSheet("color: #666; font-size: 10px; min-width: 30px;")
        self._search_count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sl.addWidget(self._search_edit, stretch=1)
        sl.addWidget(self._search_meta_btn)
        sl.addWidget(self._search_clear_btn)
        sl.addWidget(self._search_count_lbl)
        self._search_bar = search_bar
        search_bar.hide()
        left_layout.addWidget(search_bar)

        self._grid = GridView(self._folder_model, left)
        left_layout.addWidget(self._grid, stretch=1)

        # Bottom of strip: "Next folder" button
        self._nav_next_folder_btn = QPushButton()
        self._nav_next_folder_btn.setIcon(_nav_icon("folder-next.svg"))
        self._nav_next_folder_btn.setIconSize(QSize(20, 20))
        self._nav_next_folder_btn.setFixedHeight(28)
        self._nav_next_folder_btn.setToolTip("Next sibling folder")
        self._nav_next_folder_btn.setEnabled(False)
        self._nav_next_folder_btn.setStyleSheet("""
            QPushButton {
                background: #252525; color: #888; border: none;
                border-top: 1px solid #2e2e2e;
                border-radius: 0;
            }
            QPushButton:enabled:hover  { background: #2e2e2e; color: #ccc; }
            QPushButton:enabled:pressed { background: #333; }
            QPushButton:disabled { opacity: 0.35; }
        """)
        left_layout.addWidget(self._nav_next_folder_btn)

        left.setMinimumWidth(180)
        left.setMaximumWidth(260)

        # ---- centre ----
        self._container = ViewerContainer()
        self._container.media_player.apply_settings(self._settings)

        # ---- right panel: metadata ----
        self._meta_panel = MetadataPanel()

        # ---- splitter ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._container)
        splitter.addWidget(self._meta_panel)
        splitter.setSizes([200, 1080, 0])
        self._left_panel = left
        left.hide()
        self._meta_panel.hide()

        self.setCentralWidget(splitter)

        # ---- expanded grid overlay (child of MainWindow, covers central widget) ----
        self._expanded_overlay = ExpandedGridOverlay(self._folder_model, self)
        self._expanded_overlay.hide()

        # ---- status bar ----
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._lbl_path  = QLabel("")
        self._lbl_dims  = QLabel("")
        self._lbl_zoom  = QLabel("100%")
        self._status_bar.addWidget(self._lbl_path,  stretch=3)
        self._status_bar.addPermanentWidget(self._lbl_dims)
        self._status_bar.addPermanentWidget(self._lbl_zoom)

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        self._open_act = QAction("&Open…", self)
        self._open_act.setShortcut(QKeySequence.StandardKey.Open)
        self._open_act.triggered.connect(self.open_file_dialog)
        file_menu.addAction(self._open_act)
        self._open_folder_act = QAction("Open &Folder…", self)
        self._open_folder_act.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self._open_folder_act.triggered.connect(self.open_folder_dialog)
        file_menu.addAction(self._open_folder_act)
        file_menu.addSeparator()
        self._quit_act = QAction("&Quit", self)
        self._quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        self._quit_act.triggered.connect(self.close)
        file_menu.addAction(self._quit_act)

        # View
        view_menu = mb.addMenu("&View")
        self._fit_act = QAction("&Fit to Window", self)
        self._fit_act.setShortcut(QKeySequence("F"))
        self._fit_act.triggered.connect(self._container.viewer.set_fit_mode)
        view_menu.addAction(self._fit_act)

        self._one_act = QAction("&Actual Size (1:1)", self)
        self._one_act.setShortcut(QKeySequence("1"))
        self._one_act.triggered.connect(self._container.viewer.set_one_to_one)
        view_menu.addAction(self._one_act)

        self._full_act = QAction("&Fullscreen", self)
        self._full_act.setShortcut(QKeySequence("F11"))
        self._full_act.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(self._full_act)

        self._slideshow_act = QAction("S&lideshow", self)
        self._slideshow_act.setShortcut(QKeySequence("F5"))
        self._slideshow_act.triggered.connect(self._enter_slideshow)
        view_menu.addAction(self._slideshow_act)

        view_menu.addSeparator()
        self._stretch_act = QAction("&Stretch Small Images", self)
        self._stretch_act.setCheckable(True)
        self._stretch_act.setShortcut(QKeySequence("S"))
        self._stretch_act.toggled.connect(self._on_stretch_toggled)
        view_menu.addAction(self._stretch_act)

        self._meta_panel_act = QAction("&Metadata Panel", self)
        self._meta_panel_act.setCheckable(True)
        self._meta_panel_act.setShortcut(QKeySequence("Ctrl+I"))
        self._meta_panel_act.toggled.connect(self._on_metadata_panel_toggled)
        view_menu.addAction(self._meta_panel_act)

        self._search_act = QAction("&Search…", self)
        self._search_act.setShortcut(QKeySequence("Ctrl+F"))
        self._search_act.triggered.connect(self._toggle_search_bar)
        view_menu.addAction(self._search_act)

        # Edit
        edit_menu = mb.addMenu("&Edit")
        self._act_crop = QAction("&Crop…", self)
        self._act_crop.setShortcut(QKeySequence("C"))
        self._act_crop.setEnabled(False)
        self._act_crop.triggered.connect(self._enter_crop_mode)
        edit_menu.addAction(self._act_crop)
        self._act_adjust = QAction("&Adjust…", self)
        self._act_adjust.setShortcut(QKeySequence("A"))
        self._act_adjust.setEnabled(False)
        self._act_adjust.triggered.connect(self._enter_adjust_mode)
        edit_menu.addAction(self._act_adjust)
        self._act_rotate = QAction("&Rotate…", self)
        self._act_rotate.setShortcut(QKeySequence("R"))
        self._act_rotate.setEnabled(False)
        self._act_rotate.triggered.connect(self._enter_rotate_mode)
        edit_menu.addAction(self._act_rotate)
        self._act_flip = QAction("F&lip…", self)
        self._act_flip.setShortcut(QKeySequence("L"))
        self._act_flip.setEnabled(False)
        self._act_flip.triggered.connect(self._enter_flip_mode)
        edit_menu.addAction(self._act_flip)
        self._act_resize = QAction("Resi&ze…", self)
        self._act_resize.setShortcut(QKeySequence("Z"))
        self._act_resize.setEnabled(False)
        self._act_resize.triggered.connect(self._enter_resize_mode)
        edit_menu.addAction(self._act_resize)
        edit_menu.addSeparator()
        self._rename_act = QAction("Re&name", self)
        self._rename_act.setShortcut(QKeySequence("F2"))
        self._rename_act.triggered.connect(self._start_rename)
        edit_menu.addAction(self._rename_act)
        edit_menu.addSeparator()
        self._settings_act = QAction("&Settings…", self)
        self._settings_act.setShortcut(QKeySequence("Ctrl+,"))
        self._settings_act.triggered.connect(self._open_settings)
        edit_menu.addAction(self._settings_act)

        # Help
        help_menu = mb.addMenu("&Help")
        self._about_act = QAction("&About Pix42…", self)
        self._about_act.triggered.connect(self._show_about)
        help_menu.addAction(self._about_act)

        self.menuBar().hide()

    def _build_toolbar(self) -> None:
        overlay_dir = ASSETS_DIR / "icons" / "overlay"
        tb_dir      = ASSETS_DIR / "icons" / "toolbar"

        def _icon(path) -> QIcon:
            return QIcon(str(path)) if path.exists() else QIcon()

        tb = QToolBar("Main Toolbar", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self._toolbar = tb

        # --- File ---
        self._open_act.setIcon(_icon(tb_dir / "open_file.svg"))
        self._open_act.setToolTip("Open File  (Ctrl+O)")
        tb.addAction(self._open_act)

        self._open_folder_act.setIcon(_icon(tb_dir / "open_folder.svg"))
        self._open_folder_act.setToolTip("Open Folder  (Ctrl+Shift+O)")
        tb.addAction(self._open_folder_act)

        tb.addSeparator()

        # --- View ---
        self._fit_act.setIcon(_icon(overlay_dir / "fit.svg"))
        self._fit_act.setToolTip("Fit to Window  (F)")
        tb.addAction(self._fit_act)

        self._one_act.setIcon(_icon(tb_dir / "actual_size.svg"))
        self._one_act.setToolTip("Actual Size 1:1  (1)")
        tb.addAction(self._one_act)

        self._full_act.setIcon(_icon(overlay_dir / "fullscreen.svg"))
        self._full_act.setToolTip("Fullscreen  (F11)")
        tb.addAction(self._full_act)

        tb.addSeparator()

        # --- Edit (enable/disable synced automatically via QAction) ---
        self._act_crop.setIcon(_icon(tb_dir / "crop.svg"))
        self._act_crop.setToolTip("Crop  (C)")
        tb.addAction(self._act_crop)

        self._act_adjust.setIcon(_icon(tb_dir / "adjust.svg"))
        self._act_adjust.setToolTip("Adjust  (A)")
        tb.addAction(self._act_adjust)

        self._act_rotate.setIcon(_icon(tb_dir / "rotate.svg"))
        self._act_rotate.setToolTip("Rotate  (R)")
        tb.addAction(self._act_rotate)

        self._act_flip.setIcon(_icon(tb_dir / "flip.svg"))
        self._act_flip.setToolTip("Flip  (L)")
        tb.addAction(self._act_flip)

        self._act_resize.setIcon(_icon(tb_dir / "resize.svg"))
        self._act_resize.setToolTip("Resize  (Z)")
        tb.addAction(self._act_resize)

        tb.addSeparator()

        # --- Extra ---
        self._search_act.setIcon(_icon(tb_dir / "search.svg"))
        self._search_act.setToolTip("Search  (Ctrl+F)")
        tb.addAction(self._search_act)

        self._slideshow_act.setIcon(_icon(tb_dir / "slideshow.svg"))
        self._slideshow_act.setToolTip("Slideshow  (F5)")
        tb.addAction(self._slideshow_act)

        self._meta_panel_act.setIcon(_icon(tb_dir / "metadata.svg"))
        self._meta_panel_act.setToolTip("Metadata Panel  (Ctrl+I)")
        tb.addAction(self._meta_panel_act)

        tb.addSeparator()

        # --- More (overflow) ---
        more_btn = QToolButton(tb)
        more_btn.setIcon(_icon(tb_dir / "more.svg"))
        more_btn.setToolTip("More")
        more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(more_btn)
        more_menu.addAction(self._rename_act)
        more_menu.addSeparator()
        more_menu.addAction(self._stretch_act)
        more_menu.addSeparator()
        more_menu.addAction(self._settings_act)
        more_menu.addSeparator()
        more_menu.addAction(self._about_act)
        more_menu.addSeparator()
        more_menu.addAction(self._quit_act)
        more_btn.setMenu(more_menu)
        tb.addWidget(more_btn)

    def _connect_signals(self) -> None:
        overlay = self._container.overlay
        viewer  = self._container.viewer

        overlay.prev_requested.connect(self._go_prev)
        overlay.next_requested.connect(self._go_next)
        overlay.zoom_in_requested.connect(viewer.zoom_in)
        overlay.zoom_out_requested.connect(viewer.zoom_out)
        overlay.fit_requested.connect(viewer.set_fit_mode)
        overlay.one_to_one_requested.connect(viewer.set_one_to_one)
        overlay.fullscreen_requested.connect(self._toggle_fullscreen)

        viewer.zoom_changed.connect(self._on_zoom_changed)
        viewer.pan_changed.connect(self._on_pan_changed)
        viewer.delete_requested.connect(self._delete_current_file)

        self._grid.image_activated.connect(self.open_path)
        self._grid.folder_activated.connect(self._open_folder)
        self._grid.scroll_changed.connect(self._reprioritize_thumbnails)
        self._nav_up_btn.clicked.connect(self._go_up)
        self._nav_expand_btn.clicked.connect(self._open_expanded_grid)
        self._nav_next_folder_btn.clicked.connect(self._go_next_folder)
        self._container.navigator.pan_requested.connect(self._on_navigator_pan)
        self._container.toggle_filmstrip.connect(self._toggle_filmstrip)
        self._container.media_player.error_occurred.connect(
            lambda msg: self._status_bar.showMessage(f"Media error: {msg}", 5000)
        )
        self._expanded_overlay.image_selected.connect(self._on_expanded_image_selected)
        self._expanded_overlay.folder_selected.connect(self._on_expanded_folder_selected)
        self._expanded_overlay.close_requested.connect(self._close_expanded_grid)
        self._expanded_overlay.scroll_changed.connect(self._reprioritize_thumbnails_expanded)
        self._grid.rename_done.connect(self._on_rename_done)
        self._grid.rename_failed.connect(self._on_rename_failed)
        self._expanded_overlay.rename_done.connect(self._on_rename_done)
        self._expanded_overlay.rename_failed.connect(self._on_rename_failed)
        self._grid.multi_selection_changed.connect(self._meta_panel.set_selected_paths)
        self._meta_panel.closed.connect(lambda: self._meta_panel_act.setChecked(False))
        self._meta_panel.save_requested.connect(self._save_metadata)
        self._grid.filter_stats_changed.connect(self._on_filter_stats_changed)
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._search_meta_btn.toggled.connect(self._on_meta_search_toggled)
        self._search_clear_btn.clicked.connect(self._clear_search)
        self._expanded_overlay._search_input.textChanged.connect(self._on_overlay_search_changed)
        ss = self._container.slideshow_bar
        ss.play_pause_requested.connect(self._slideshow_toggle_play)
        ss.stop_requested.connect(self._exit_slideshow)
        ss.order_toggled.connect(self._slideshow_order_toggled)
        ss.interval_changed.connect(self._slideshow_interval_changed)

    # ------------------------------------------------------------------ #
    # File opening                                                         #
    # ------------------------------------------------------------------ #

    def open_file_dialog(self) -> None:
        start_dir = str(self._settings.last_folder or "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", start_dir,
            "All supported (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp "
            "*.psd "
            "*.cr2 *.cr3 *.nef *.arw *.dng *.rw2 *.fit *.fits *.fts "
            "*.mp4 *.avi *.mov *.mkv *.wmv *.webm *.m4v *.flv *.mpeg *.mpg "
            "*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.opus)"
            ";;Images (*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp *.psd "
            "*.cr2 *.cr3 *.nef *.arw *.dng *.rw2 *.fit *.fits *.fts)"
            ";;Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm *.m4v *.flv *.mpeg *.mpg)"
            ";;Audio (*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.opus)"
            ";;All Files (*)",
        )
        if path:
            self.open_path(Path(path))

    def open_folder_dialog(self) -> None:
        start_dir = str(self._settings.last_folder or "")
        folder = QFileDialog.getExistingDirectory(
            self, "Open Folder", start_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._open_folder(Path(folder))

    def _load_folder_into_model(self, folder: Path) -> None:
        """Call the right FolderModel loader based on the recursive setting."""
        if self._settings.filmstrip_recursive:
            self._folder_model.load_folder_recursive(folder)
        else:
            self._folder_model.load_folder(folder)

    def _open_folder(self, folder: Path) -> None:
        self._container.viewer._stop_movie()
        self._container.media_player.stop()
        self._load_folder_into_model(folder)
        self._watch_folder(folder)
        self._settings.last_folder = folder
        self._grid.clear_extra_selection()
        self._cancel_meta_scan()
        self._grid.refresh()
        self._thumbnails_loaded = False
        self._update_nav_bar()
        if self._folder_model.current is not None:
            self._grid.select_path(self._folder_model.current.path)
            self._load_current()
        else:
            self._container.show_image_mode()

    def open_path(self, path: Path) -> None:
        """Load *path*. Reloads the folder only when it actually changes."""
        current = self._folder_model.current
        same_folder = current is not None and current.path.parent == path.parent

        if same_folder:
            # Navigate within the already-loaded folder — thumbnails are preserved
            self._folder_model.go_to_path(path)
        else:
            self._folder_model.load_single_file(path)
            self._watch_folder(path.parent)
            self._settings.last_folder = path.parent
            self._grid.refresh()
            self._thumbnails_loaded = False
            self._update_nav_bar()

        self._grid.select_path(path)
        self._load_current()

    # ------------------------------------------------------------------ #
    # Image loading                                                        #
    # ------------------------------------------------------------------ #

    def _exit_all_edit_modes(self) -> None:
        if self._crop_mode_active:
            self._exit_crop_mode()
        if self._adjust_mode_active:
            self._exit_adjust_mode()
        if self._rotate_mode_active:
            self._exit_rotate_mode()
        if self._flip_mode_active:
            self._exit_flip_mode()
        if self._resize_mode_active:
            self._exit_resize_mode()

    def _load_current(self) -> None:
        self._exit_all_edit_modes()
        entry = self._folder_model.current
        if entry is None:
            return
        self._lbl_path.setText(str(entry.path))
        if not entry.is_dir and self._settings.restore_last_image:
            self._settings.last_image = entry.path
        # Cancel any in-flight full-res worker for the previous image.
        if self._fullres_cancel is not None:
            self._fullres_cancel.set()
        self._fullres_cancel = None

        if entry.path.suffix.lower() in _MEDIA_EXTENSIONS:
            self._container.spinner.stop()
            self._container.show_media_mode()
            self._container.media_player.load(entry.path)
            try:
                self._lbl_dims.setText(_fmt_size(entry.path.stat().st_size))
            except OSError:
                self._lbl_dims.setText("")
            self._lbl_zoom.setText("")
            self._start_thumbnails_if_needed()
            return

        self._container.show_image_mode()
        self._container.spinner.start()
        worker = LoadImageWorker(entry.path, self._loader)
        worker.signals.finished.connect(self._on_image_loaded)
        worker.signals.error.connect(self._on_load_error)
        self._preview_pool.start(worker)

    def _on_image_loaded(self, handle: "ImageHandle") -> None:
        self._current_handle = handle
        m = handle.metadata
        animated = _is_animated(handle.path)
        suffix = handle.path.suffix.lower()
        self._act_crop.setEnabled(suffix in _CROPPABLE_SUFFIXES and not animated)
        self._act_adjust.setEnabled(suffix in _ADJUSTABLE_SUFFIXES and not animated)
        self._act_rotate.setEnabled(suffix in _ROTATABLE_SUFFIXES)
        self._act_flip.setEnabled(suffix in _FLIPPABLE_SUFFIXES)
        self._act_resize.setEnabled(suffix in _RESIZABLE_SUFFIXES and not animated)
        if handle.preview and not handle.preview.isNull():
            self._container.viewer.set_native_size(m.width, m.height)
            if animated:
                self._container.viewer.load_movie(QMovie(str(handle.path)))
            else:
                self._container.viewer.load_image(handle.preview)
            self._container.navigator.set_image(handle.preview)
        try:
            file_size = _fmt_size(handle.path.stat().st_size)
        except OSError:
            file_size = ""
        dims_text = f"{m.width} × {m.height}"
        if file_size:
            dims_text += f"   {file_size}"
        if m.format_name:
            dims_text += f"   {m.format_name}"
        self._lbl_dims.setText(dims_text)
        self._on_zoom_changed(self._container.viewer.effective_zoom)
        self._update_navigator_rect()
        self._meta_panel.set_image(handle.path, m)

        # Prefetch previews for adjacent images while the current one is displayed.
        self._schedule_prefetch()

        # Animated files need no full-res refinement — QMovie handles playback directly.
        if animated:
            self._container.spinner.stop()
            self._start_thumbnails_if_needed()
            return

        # Kick off full-resolution refinement when the preview was downscaled.
        # Runs for both NORMAL and TILED modes — decode_full caps at 16 K px
        # so memory usage stays bounded even for very large images.
        if (m.width > 0 and m.height > 0
                and max(m.width, m.height) > self._loader._preview_size
                and not self._loader.has_fullres(handle.path)):
            cancel = threading.Event()
            self._fullres_cancel = cancel
            worker = FullResWorker(handle.path, self._loader, cancel)
            worker.signals.ready.connect(self._on_fullres_ready)
            self._fullres_pool.start(worker)
        else:
            # No refinement needed: image is already at full quality.
            self._container.spinner.stop()
            self._start_thumbnails_if_needed()

    def _on_fullres_ready(self, path: Path, image: QImage) -> None:
        """Refine the viewer with full-resolution pixels, preserving zoom/pan."""
        if (self._current_handle is None
                or self._current_handle.path != path
                or image.isNull()):
            self._container.spinner.stop()
            return
        self._current_handle.preview = image
        self._container.viewer.refine_image(image)
        self._container.navigator.set_image(image)
        self._update_navigator_rect()
        self._container.spinner.stop()
        self._start_thumbnails_if_needed()

    def _on_load_error(self, msg: str) -> None:
        log.error("Load error: %s", msg)
        self._container.spinner.stop()
        self._status_bar.showMessage(f"Error: {msg}", 5000)
        self._start_thumbnails_if_needed()  # don't leave thumbnails blocked on error

    def _schedule_prefetch(self) -> None:
        """Queue preview decoding for the next and previous images into the cache."""
        idx = self._folder_model.current_index
        for offset in (1, -1):
            i = idx + offset
            if 0 <= i < self._folder_model.count:
                entry = self._folder_model[i]
                if entry.is_dir:
                    continue
                worker = ThreadWorker(self._loader.prefetch, entry.path)
                self._prefetch_pool.start(worker)

    # ------------------------------------------------------------------ #
    # Thumbnail loading                                                    #
    # ------------------------------------------------------------------ #

    def _start_thumbnails_if_needed(self) -> None:
        if not self._thumbnails_loaded:
            self._thumbnails_loaded = True
            self._thumb_queue.clear()
            self._thumb_done.clear()
            self._thumb_inflight = 0
            self._load_folder_thumbnails()

    def _load_folder_thumbnails(self) -> None:
        """Build the priority queue (visible rows first) and kick off initial workers."""
        all_paths = [
            entry.path
            for entry in self._folder_model
            if not entry.is_dir
            and entry.path.suffix.lower() not in _AUDIO_EXTENSIONS
        ]
        if not all_paths:
            return

        visible_set = set(self._grid.get_visible_paths())
        priority = [p for p in all_paths if p in visible_set]
        rest     = [p for p in all_paths if p not in visible_set]
        self._thumb_queue = deque(priority + rest)

        for _ in range(self._thumb_pool.maxThreadCount()):
            self._dispatch_next_thumb()

    def _dispatch_next_thumb(self) -> None:
        """Pop one path from the queue and submit a worker, skipping done paths."""
        while self._thumb_queue:
            path = self._thumb_queue.popleft()
            if path in self._thumb_done:
                continue
            self._thumb_done.add(path)
            self._thumb_inflight += 1
            worker = ThumbnailWorker(
                path, self._loader, thumb_size=256, thumb_store=self._thumb_store
            )
            worker.signals.ready.connect(self._on_thumbnail_ready)
            worker.signals.error.connect(self._on_thumbnail_error)
            self._thumb_pool.start(worker)
            return

    def _reprioritize_thumbnails(self) -> None:
        """Move currently visible paths to the front of the pending queue."""
        if not self._thumb_queue:
            return
        visible_set  = set(self._grid.get_visible_paths())
        pending      = [p for p in self._thumb_queue if p not in visible_set]
        front        = [p for p in self._thumb_queue if p in visible_set]
        self._thumb_queue = deque(front + pending)

    def _on_thumbnail_ready(self, path: Path, image: QImage) -> None:
        self._grid.set_thumbnail(path, image)
        self._expanded_overlay.set_thumbnail(path, image)
        self._thumb_inflight = max(0, self._thumb_inflight - 1)
        self._dispatch_next_thumb()

    def _on_thumbnail_error(self, path: Path, msg: str) -> None:
        log.debug("Thumb error %s: %s", path, msg)
        self._thumb_inflight = max(0, self._thumb_inflight - 1)
        self._dispatch_next_thumb()

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    def _go_next(self) -> None:
        entry = self._folder_model.go_next()
        if entry:
            self._grid.select_path(entry.path)
        self._load_current()

    def _go_prev(self) -> None:
        entry = self._folder_model.go_prev()
        if entry:
            self._grid.select_path(entry.path)
        self._load_current()

    def _go_up(self) -> None:
        folder = self._folder_model.current_folder
        if folder is None:
            return  # already at Computer view
        if len(folder.parts) <= 1:  # drive root (e.g. C:\) or filesystem root
            self._load_drives()
        else:
            self._open_folder(folder.parent)

    @staticmethod
    def _next_sibling_folder(folder: Path) -> Optional[Path]:
        """Return the next sibling directory after *folder*, or None."""
        parent = folder.parent
        if parent == folder:
            return None
        try:
            siblings = sorted(p for p in parent.iterdir() if p.is_dir())
        except OSError:
            return None
        for i, p in enumerate(siblings):
            if p == folder and i + 1 < len(siblings):
                return siblings[i + 1]
        return None

    def _go_next_folder(self) -> None:
        folder = self._folder_model.current_folder
        if folder is None:
            return
        nxt = self._next_sibling_folder(folder)
        if nxt:
            self._open_folder(nxt)

    def _load_drives(self) -> None:
        self._container.viewer._stop_movie()
        self._container.media_player.stop()
        self._watch_folder(None)
        self._folder_model.load_drives()
        self._grid.refresh()
        self._thumbnails_loaded = True
        self._update_nav_bar()
        self._container.show_image_mode()

    def _update_nav_bar(self) -> None:
        folder = self._folder_model.current_folder
        if folder is None:
            self._nav_label.setText("Computer")
            self._nav_label.setToolTip("")
            self._nav_up_btn.setEnabled(False)
            self._nav_next_folder_btn.setEnabled(False)
            return
        self._nav_label.setText(folder.name or folder.drive or str(folder))
        self._nav_label.setToolTip(str(folder))
        self._nav_up_btn.setEnabled(True)
        has_next = self._next_sibling_folder(folder) is not None
        self._nav_next_folder_btn.setEnabled(has_next)

    # ------------------------------------------------------------------ #
    # Folder watcher                                                       #
    # ------------------------------------------------------------------ #

    def _watch_folder(self, folder: Optional[Path]) -> None:
        """Set *folder* as the watched directory, replacing any previous watch."""
        dirs = self._fs_watcher.directories()
        if dirs:
            self._fs_watcher.removePaths(dirs)
        if folder is not None:
            self._fs_watcher.addPath(str(folder))

    def _on_dir_changed(self) -> None:
        """Slot: filesystem change detected — debounce before processing."""
        self._watcher_timer.start()

    def _apply_folder_changes(self) -> None:
        """Sync the folder model with what's on disk and refresh the grid."""
        added, removed = self._folder_model.sync_folder()
        if not added and not removed:
            return

        current = self._folder_model.current
        self._grid.refresh()
        if current is not None:
            self._grid.select_path(current.path)

        # Enqueue thumbnails for newly arrived files without discarding existing ones.
        for path in added:
            if path.suffix.lower() not in _AUDIO_EXTENSIONS:
                self._thumb_queue.appendleft(path)
        if added:
            self._dispatch_next_thumb()

        n = len(added)
        if n:
            self._status_bar.showMessage(
                f"{n} new file{'s' if n > 1 else ''} detected", 4000
            )

    # ------------------------------------------------------------------ #
    # Zoom / pan callbacks                                                 #
    # ------------------------------------------------------------------ #

    def _on_zoom_changed(self, zoom: float) -> None:
        self._lbl_zoom.setText(f"{zoom * 100:.0f}%")
        self._container.overlay.set_zoom_label(zoom)
        self._update_navigator_rect()

    def _on_pan_changed(self) -> None:
        self._update_navigator_rect()

    def _update_navigator_rect(self) -> None:
        """Push current viewport rect (in image-pixel coords) to the navigator."""
        viewer = self._container.viewer
        handle = self._current_handle
        if handle is None or handle.preview is None or handle.preview.isNull():
            return
        iw = handle.preview.width()
        ih = handle.preview.height()
        if iw == 0 or ih == 0:
            return
        r = viewer.viewport_image_rect()
        self._container.navigator.set_viewport_rect(r.x(), r.y(), r.width(), r.height(), iw, ih)

    def _on_navigator_pan(self, cx: float, cy: float) -> None:
        self._container.viewer.center_on_fraction(cx, cy)

    # ------------------------------------------------------------------ #
    # Misc                                                                 #
    # ------------------------------------------------------------------ #

    def _on_stretch_toggled(self, checked: bool) -> None:
        self._container.viewer.set_stretch_small(checked)
        self._settings.stretch_small = checked

    def _on_metadata_panel_toggled(self, checked: bool) -> None:
        splitter = self.centralWidget()
        sizes = splitter.sizes()
        if checked:
            self._meta_panel.show()
            if len(sizes) == 3 and sizes[2] < 10:
                panel_w = self._settings.metadata_panel_width
                total = sizes[1] + sizes[2]
                splitter.setSizes([sizes[0], max(200, total - panel_w), panel_w])
        else:
            if len(sizes) == 3 and sizes[2] > 0:
                self._settings.metadata_panel_width = sizes[2]
            self._meta_panel.hide()
        self._settings.metadata_panel_visible = checked

    # ------------------------------------------------------------------ #
    # Search                                                               #
    # ------------------------------------------------------------------ #

    def _toggle_search_bar(self) -> None:
        if self._expanded_overlay.isVisible():
            self._expanded_overlay._search_input.setFocus()
            self._expanded_overlay._search_input.selectAll()
            return
        if not self._left_panel.isVisible():
            self._left_panel.show()
        if self._search_bar.isHidden():
            self._search_bar.show()
            self._search_edit.setFocus()
            self._search_edit.selectAll()
        else:
            self._clear_search()
            self._search_bar.hide()

    def _clear_search(self) -> None:
        self._search_edit.blockSignals(True)
        self._search_edit.clear()
        self._search_edit.blockSignals(False)
        self._apply_search_filter("")
        self._search_count_lbl.setText("")

    def _on_search_text_changed(self, text: str) -> None:
        self._apply_search_filter(text)
        if self._search_meta_mode and text.strip():
            self._search_timer.start()
        else:
            self._search_timer.stop()

    def _on_overlay_search_changed(self, text: str) -> None:
        if self._search_edit.text() != text:
            self._search_edit.blockSignals(True)
            self._search_edit.setText(text)
            self._search_edit.blockSignals(False)
        self._apply_search_filter(text)
        if self._search_meta_mode and text.strip():
            self._search_timer.start()
        else:
            self._search_timer.stop()

    def _apply_search_filter(self, text: str) -> None:
        self._grid.set_filter(text)
        self._expanded_overlay.set_filter(text)
        vis, total = self._grid._thumb_model.filter_stats
        self._update_search_count(vis, total)

    def _update_search_count(self, visible: int, total: int) -> None:
        label = f"{visible}/{total}" if visible != total and self._search_edit.text() else ""
        self._search_count_lbl.setText(label)
        self._expanded_overlay.set_search_count(visible, total)

    def _on_filter_stats_changed(self, visible: int, total: int) -> None:
        self._update_search_count(visible, total)

    def _on_meta_search_toggled(self, checked: bool) -> None:
        self._search_meta_mode = checked
        if checked and self._search_edit.text().strip():
            self._start_meta_scan()
        elif not checked and self._search_stop:
            self._cancel_meta_scan()

    def _cancel_meta_scan(self) -> None:
        if self._search_stop:
            self._search_stop.set()
            self._search_stop = None
        self._search_seq += 1

    def _start_meta_scan(self) -> None:
        text = self._search_edit.text().strip()
        if not text:
            return
        self._cancel_meta_scan()  # also increments _search_seq
        stop = threading.Event()
        self._search_stop = stop
        worker = _MetaScanWorker(self._folder_model, self._loader, self._search_seq, stop)
        worker.signals.meta_ready.connect(self._on_meta_scan_result)
        worker.signals.finished.connect(self._on_meta_scan_done)
        self._search_pool.start(worker)

    def _on_meta_scan_result(self, idx: int, search_text: str, seq: int) -> None:
        if seq != self._search_seq:
            return
        if 0 <= idx < self._folder_model.count:
            self._folder_model[idx].search_text = search_text
        if not self._search_refresh_timer.isActive():
            self._search_refresh_timer.start()

    def _on_meta_scan_done(self, seq: int) -> None:
        if seq != self._search_seq:
            return
        self._do_search_refresh()

    def _do_search_refresh(self) -> None:
        self._grid.refresh_filter()
        self._expanded_overlay.refresh_filter()
        vis, total = self._grid._thumb_model.filter_stats
        self._update_search_count(vis, total)

    def _toggle_filmstrip(self) -> None:
        if self._left_panel.isVisible():
            splitter = self.centralWidget()
            if hasattr(splitter, "sizes"):
                w = splitter.sizes()[0]
                if w > 0:
                    self._settings.filmstrip_width = w
            self._left_panel.hide()
            self._settings.filmstrip_visible = False
        else:
            w = self._settings.filmstrip_width
            splitter = self.centralWidget()
            if hasattr(splitter, "sizes"):
                sizes = splitter.sizes()
                total = sizes[0] + sizes[1]
                splitter.setSizes([w, max(200, total - w), sizes[2]])
            self._left_panel.show()
            self._settings.filmstrip_visible = True

    def _start_rename(self) -> None:
        if self._expanded_overlay.isVisible():
            self._expanded_overlay.start_rename()
        else:
            self._grid.start_rename()

    def _on_rename_done(self, old_path: Path, new_path: Path) -> None:
        self._cache.invalidate(old_path)
        self._thumb_done.discard(old_path)
        self._thumb_done.add(new_path)
        entry = self._folder_model.current
        if entry and entry.path == new_path:
            self._lbl_path.setText(str(new_path))

    def _on_rename_failed(self, msg: str) -> None:
        self._status_bar.showMessage(f"Rename failed: {msg}", 4000)

    # ------------------------------------------------------------------ #
    # Slideshow                                                            #
    # ------------------------------------------------------------------ #

    def _enter_slideshow(self) -> None:
        if self._slideshow_active:
            return
        if self._folder_model.current is None:
            return
        self._exit_all_edit_modes()
        self._slideshow_active = True
        self._slideshow_playing = False
        bar = self._container.slideshow_bar
        bar.reset()
        bar.show()
        bar.raise_()
        self._container._reposition_overlays()

    def _exit_slideshow(self) -> None:
        if not self._slideshow_active:
            return
        self._slideshow_active = False
        self._slideshow_playing = False
        self._slideshow_timer.stop()
        self._container.slideshow_bar.hide()

    def _slideshow_toggle_play(self) -> None:
        self._slideshow_playing = not self._slideshow_playing
        if self._slideshow_playing:
            interval_ms = self._container.slideshow_bar.interval * 1000
            self._slideshow_timer.start(interval_ms)
        else:
            self._slideshow_timer.stop()

    def _slideshow_order_toggled(self) -> None:
        pass  # bar already tracks its own state; advance uses bar.is_random

    def _slideshow_interval_changed(self, seconds: int) -> None:
        if self._slideshow_playing:
            self._slideshow_timer.setInterval(seconds * 1000)

    def _slideshow_advance(self) -> None:
        import random as _random
        file_indices = [
            i for i in range(self._folder_model.count)
            if not self._folder_model[i].is_dir
        ]
        if not file_indices:
            return
        bar = self._container.slideshow_bar
        current_idx = self._folder_model.current_index
        if bar.is_random:
            choices = [i for i in file_indices if i != current_idx]
            if not choices:
                return
            target = _random.choice(choices)
        else:
            try:
                pos = file_indices.index(current_idx)
            except ValueError:
                pos = -1
            target = file_indices[(pos + 1) % len(file_indices)]
        self._folder_model.go_to(target)
        entry = self._folder_model.current
        if entry:
            self._grid.select_path(entry.path)
        self._load_current()

    # ------------------------------------------------------------------ #
    # Expanded grid overlay                                                #
    # ------------------------------------------------------------------ #

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._expanded_overlay.isVisible():
            cw = self.centralWidget()
            if cw:
                self._expanded_overlay.setGeometry(cw.geometry())

    def _open_expanded_grid(self) -> None:
        cw = self.centralWidget()
        if cw:
            self._expanded_overlay.setGeometry(cw.geometry())
        self._expanded_overlay.set_folder_label(
            self._nav_label.text(), self._nav_label.toolTip()
        )
        self._expanded_overlay.refresh()
        entry = self._folder_model.current
        if entry:
            self._expanded_overlay.select_path(entry.path)
        self._expanded_overlay.show()
        self._expanded_overlay.raise_()
        self._expanded_overlay.setFocus()

    def _close_expanded_grid(self) -> None:
        self._expanded_overlay.hide()
        entry = self._folder_model.current
        if entry:
            self._grid.select_path(entry.path)

    def _on_expanded_image_selected(self, path: Path) -> None:
        self._close_expanded_grid()
        self.open_path(path)

    def _on_expanded_folder_selected(self, path: Path) -> None:
        self._open_folder(path)
        self._expanded_overlay.refresh()
        self._expanded_overlay.set_folder_label(
            self._nav_label.text(), self._nav_label.toolTip()
        )

    def _reprioritize_thumbnails_expanded(self) -> None:
        if not self._thumb_queue:
            return
        visible_set = set(self._expanded_overlay.get_visible_paths())
        pending = [p for p in self._thumb_queue if p not in visible_set]
        front   = [p for p in self._thumb_queue if p in visible_set]
        self._thumb_queue = deque(front + pending)

    # ------------------------------------------------------------------ #
    # Metadata save                                                        #
    # ------------------------------------------------------------------ #

    def _save_metadata(self, fields: dict, paths: list[Path]) -> None:
        """Write editable EXIF fields to one or more files."""
        errors: list[str] = []
        saved = 0
        for path in paths:
            suffix = path.suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp"}:
                continue
            try:
                if suffix in {".jpg", ".jpeg"}:
                    _write_exif_jpeg(path, fields)
                else:
                    _write_exif_pillow(path, fields)
                self._cache.invalidate(path)
                saved += 1
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        if errors:
            QMessageBox.warning(
                self, "Save Metadata",
                "Could not save to some files:\n" + "\n".join(errors[:5]),
            )
        if saved:
            self._status_bar.showMessage(f"Metadata saved to {saved} file(s).", 3000)
            # Refresh metadata panel for current image if it was among saved files
            entry = self._folder_model.current
            if entry and entry.path in paths:
                self._load_current()

    def _delete_current_file(self) -> None:
        entry = self._folder_model.current
        if entry is None:
            return
        path = entry.path
        needs_confirm = (
            self._settings.confirm_delete_folder if entry.is_dir
            else self._settings.confirm_delete_file
        )
        if needs_confirm:
            label = "folder" if entry.is_dir else "file"
            reply = QMessageBox.question(
                self,
                "Move to Trash",
                f"Move {label} to Trash:\n{path.name}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._container.viewer._stop_movie()
        self._container.media_player.stop()

        ok = QFile.moveToTrash(str(path))
        if not ok:
            QMessageBox.warning(self, "Error", f"Could not move file to Trash:\n{path}")
            return

        self._cache.invalidate(path)
        next_entry = self._folder_model.remove_current()
        self._grid.refresh()
        self._thumbnails_loaded = False

        if next_entry is not None:
            self._grid.select_path(next_entry.path)
            self._load_current()
        else:
            self._container.viewer.clear()
            self._lbl_path.setText("")
            self._lbl_dims.setText("")
            self._lbl_zoom.setText("")

    # ------------------------------------------------------------------ #
    # Crop                                                                 #
    # ------------------------------------------------------------------ #

    def _enter_crop_mode(self) -> None:
        if self._current_handle is None or self._crop_mode_active:
            return
        if self._slideshow_active:
            self._exit_slideshow()
        self._crop_mode_active = True
        viewer   = self._container.viewer
        crop_bar = self._container.crop_bar
        suffix = self._current_handle.path.suffix.lower()
        crop_bar.set_overwrite_allowed(suffix in _CROPPABLE_SUFFIXES)
        crop_bar.clear_selection()
        crop_bar.show()
        crop_bar.raise_()
        self._container._reposition_overlays()
        self._container.overlay.hide()
        viewer.set_crop_mode(True)
        viewer.crop_selection_changed.connect(self._on_crop_selection)
        crop_bar.cancel_requested.connect(self._exit_crop_mode)
        crop_bar.save_as_requested.connect(self._on_crop_save_as)
        crop_bar.overwrite_requested.connect(self._on_crop_overwrite)

    def _exit_crop_mode(self) -> None:
        if not self._crop_mode_active:
            return
        self._crop_mode_active = False
        viewer   = self._container.viewer
        crop_bar = self._container.crop_bar
        viewer.set_crop_mode(False)
        crop_bar.hide()
        try:
            viewer.crop_selection_changed.disconnect(self._on_crop_selection)
            crop_bar.cancel_requested.disconnect(self._exit_crop_mode)
            crop_bar.save_as_requested.disconnect(self._on_crop_save_as)
            crop_bar.overwrite_requested.disconnect(self._on_crop_overwrite)
        except RuntimeError:
            pass

    def _on_crop_selection(self, w: int, h: int) -> None:
        self._container.crop_bar.update_selection(w, h)

    def _on_crop_save_as(self) -> None:
        rect = self._container.viewer.get_crop_rect()
        if rect is None or self._current_handle is None:
            return
        path = self._current_handle.path
        suffix = path.suffix.lower()
        fmt_filters = {
            ".jpg":  "JPEG (*.jpg *.jpeg)",
            ".jpeg": "JPEG (*.jpg *.jpeg)",
            ".png":  "PNG (*.png)",
            ".bmp":  "BMP (*.bmp)",
            ".tif":  "TIFF (*.tif *.tiff)",
            ".tiff": "TIFF (*.tif *.tiff)",
            ".webp": "WebP (*.webp)",
        }
        default_filter = fmt_filters.get(suffix, "PNG (*.png)")
        all_filter = "All images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)"
        filters = f"{default_filter};;{all_filter}"
        default_path = str(path.parent / (path.stem + "_crop" + path.suffix))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Cropped Image", default_path, filters
        )
        if out_path:
            self._save_crop(Path(out_path), rect)

    def _on_crop_overwrite(self) -> None:
        rect = self._container.viewer.get_crop_rect()
        if rect is None or self._current_handle is None:
            return
        self._save_crop(self._current_handle.path, rect, invalidate=True)

    def _save_crop(self, dest: Path, rect: QRect, *, invalidate: bool = False) -> None:
        if self._current_handle is None:
            return
        from PIL import Image
        try:
            src = self._current_handle.path
            with Image.open(src) as img:
                box = (rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())
                cropped = img.crop(box)
                kwargs: dict = {}
                suffix = dest.suffix.lower()
                if suffix in (".jpg", ".jpeg"):
                    kwargs["quality"] = 95
                    exif = img.info.get("exif")
                    if exif:
                        kwargs["exif"] = exif
                elif suffix in (".tif", ".tiff"):
                    kwargs["compression"] = "tiff_lzw"
                cropped.save(dest, **kwargs)
            if invalidate:
                self._cache.invalidate(src)
                self._load_current()
            else:
                self._exit_crop_mode()
            self._status_bar.showMessage(f"Saved: {dest.name}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Crop Failed", str(exc))

    # ------------------------------------------------------------------ #
    # Adjust                                                               #
    # ------------------------------------------------------------------ #

    def _enter_adjust_mode(self) -> None:
        if self._current_handle is None or self._adjust_mode_active:
            return
        if self._slideshow_active:
            self._exit_slideshow()
        viewer = self._container.viewer
        if viewer._image is None or viewer._image.isNull():
            return
        self._adjust_mode_active = True
        self._adjust_seq = 0
        self._adjust_original_qimage = viewer._image
        self._adjust_preview_pil = _qimage_to_pil(viewer._image)

        adjust_bar = self._container.adjust_bar
        suffix = self._current_handle.path.suffix.lower()
        adjust_bar.set_overwrite_allowed(suffix in _ADJUSTABLE_SUFFIXES)
        adjust_bar.show()
        adjust_bar.raise_()
        self._container._reposition_overlays()
        self._container.overlay.hide()

        adjust_bar.params_changed.connect(self._on_adjust_params_changed)
        adjust_bar.cancel_requested.connect(self._exit_adjust_mode)
        adjust_bar.save_as_requested.connect(self._on_adjust_save_as)
        adjust_bar.overwrite_requested.connect(self._on_adjust_overwrite)

    def _exit_adjust_mode(self, *, restore: bool = True) -> None:
        if not self._adjust_mode_active:
            return
        self._adjust_mode_active = False
        self._adjust_timer.stop()
        adjust_bar = self._container.adjust_bar
        adjust_bar.hide()
        try:
            adjust_bar.params_changed.disconnect(self._on_adjust_params_changed)
            adjust_bar.cancel_requested.disconnect(self._exit_adjust_mode)
            adjust_bar.save_as_requested.disconnect(self._on_adjust_save_as)
            adjust_bar.overwrite_requested.disconnect(self._on_adjust_overwrite)
        except RuntimeError:
            pass
        if restore and self._adjust_original_qimage is not None:
            self._container.viewer.set_preview(self._adjust_original_qimage)
        self._adjust_original_qimage = None
        self._adjust_preview_pil = None

    def _on_adjust_params_changed(self) -> None:
        self._adjust_timer.start(120)  # debounce 120 ms

    def _dispatch_adjust(self) -> None:
        if not self._adjust_mode_active or self._adjust_preview_pil is None:
            return
        self._adjust_seq += 1
        seq    = self._adjust_seq
        params = self._container.adjust_bar.get_params()
        worker = _AdjustWorker(self._adjust_preview_pil, params, seq)
        worker.signals.done.connect(self._on_adjust_result)
        self._adjust_pool.start(worker)

    def _on_adjust_result(self, seq: int, qimage: QImage) -> None:
        if seq != self._adjust_seq or not self._adjust_mode_active:
            return
        self._container.viewer.set_preview(qimage)

    def _on_adjust_save_as(self) -> None:
        if self._current_handle is None or self._container.adjust_bar.is_identity():
            return
        path   = self._current_handle.path
        suffix = path.suffix.lower()
        fmt_filters = {
            ".jpg":  "JPEG (*.jpg *.jpeg)",
            ".jpeg": "JPEG (*.jpg *.jpeg)",
            ".png":  "PNG (*.png)",
            ".bmp":  "BMP (*.bmp)",
            ".tif":  "TIFF (*.tif *.tiff)",
            ".tiff": "TIFF (*.tif *.tiff)",
            ".webp": "WebP (*.webp)",
        }
        default_filter = fmt_filters.get(suffix, "PNG (*.png)")
        all_filter = "All images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)"
        default_path = str(path.parent / (path.stem + "_adjusted" + path.suffix))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Adjusted Image", default_path,
            f"{default_filter};;{all_filter}",
        )
        if out_path:
            self._save_adjusted(Path(out_path))

    def _on_adjust_overwrite(self) -> None:
        if self._current_handle is None:
            return
        self._save_adjusted(self._current_handle.path, invalidate=True)

    def _save_adjusted(self, dest: Path, *, invalidate: bool = False) -> None:
        if self._current_handle is None:
            return
        from PIL import Image
        try:
            src    = self._current_handle.path
            params = self._container.adjust_bar.get_params()
            with Image.open(src) as img:
                result = _apply_adjustments(img, *params)
                kwargs: dict = {}
                suffix = dest.suffix.lower()
                if suffix in (".jpg", ".jpeg"):
                    kwargs["quality"] = 95
                    exif = img.info.get("exif")
                    if exif:
                        kwargs["exif"] = exif
                elif suffix in (".tif", ".tiff"):
                    kwargs["compression"] = "tiff_lzw"
                result.save(dest, **kwargs)
            if invalidate:
                self._cache.invalidate(src)
                self._exit_adjust_mode(restore=False)
                self._load_current()
            else:
                self._exit_adjust_mode(restore=False)
            self._status_bar.showMessage(f"Saved: {dest.name}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Adjust Failed", str(exc))

    # ------------------------------------------------------------------ #
    # Rotate                                                               #
    # ------------------------------------------------------------------ #

    def _enter_rotate_mode(self) -> None:
        if self._current_handle is None or self._rotate_mode_active:
            return
        if self._slideshow_active:
            self._exit_slideshow()
        suffix = self._current_handle.path.suffix.lower()
        if suffix not in _ROTATABLE_SUFFIXES:
            return
        self._rotate_mode_active = True
        rotate_bar = self._container.rotate_bar
        rotate_bar.set_overwrite_allowed(True)
        rotate_bar.update_angle(0)
        self._container.viewer.set_rotation(0)
        rotate_bar.show()
        rotate_bar.raise_()
        self._container._reposition_overlays()
        self._container.overlay.hide()
        rotate_bar.rotate_ccw_requested.connect(self._on_rotate_ccw)
        rotate_bar.rotate_cw_requested.connect(self._on_rotate_cw)
        rotate_bar.cancel_requested.connect(self._exit_rotate_mode)
        rotate_bar.save_as_requested.connect(self._on_rotate_save_as)
        rotate_bar.overwrite_requested.connect(self._on_rotate_overwrite)

    def _exit_rotate_mode(self) -> None:
        if not self._rotate_mode_active:
            return
        self._rotate_mode_active = False
        rotate_bar = self._container.rotate_bar
        rotate_bar.hide()
        self._container.viewer.set_rotation(0)
        try:
            rotate_bar.rotate_ccw_requested.disconnect(self._on_rotate_ccw)
            rotate_bar.rotate_cw_requested.disconnect(self._on_rotate_cw)
            rotate_bar.cancel_requested.disconnect(self._exit_rotate_mode)
            rotate_bar.save_as_requested.disconnect(self._on_rotate_save_as)
            rotate_bar.overwrite_requested.disconnect(self._on_rotate_overwrite)
        except RuntimeError:
            pass

    def _on_rotate_ccw(self) -> None:
        viewer = self._container.viewer
        new_rot = (viewer.get_rotation() - 90) % 360
        viewer.set_rotation(new_rot)
        self._container.rotate_bar.update_angle(new_rot)

    def _on_rotate_cw(self) -> None:
        viewer = self._container.viewer
        new_rot = (viewer.get_rotation() + 90) % 360
        viewer.set_rotation(new_rot)
        self._container.rotate_bar.update_angle(new_rot)

    def _on_rotate_save_as(self) -> None:
        if self._current_handle is None:
            return
        path   = self._current_handle.path
        suffix = path.suffix.lower()
        fmt_filters = {
            ".jpg":  "JPEG (*.jpg *.jpeg)",
            ".jpeg": "JPEG (*.jpg *.jpeg)",
            ".png":  "PNG (*.png)",
            ".bmp":  "BMP (*.bmp)",
            ".tif":  "TIFF (*.tif *.tiff)",
            ".tiff": "TIFF (*.tif *.tiff)",
            ".webp": "WebP (*.webp)",
            ".gif":  "GIF (*.gif)",
        }
        default_filter = fmt_filters.get(suffix, "PNG (*.png)")
        all_filter = "All images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.gif)"
        default_path = str(path.parent / (path.stem + "_rotated" + path.suffix))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Rotated Image", default_path,
            f"{default_filter};;{all_filter}",
        )
        if out_path:
            self._save_rotated(Path(out_path))

    def _on_rotate_overwrite(self) -> None:
        if self._current_handle is None:
            return
        self._save_rotated(self._current_handle.path, invalidate=True)

    def _save_rotated(self, dest: Path, *, invalidate: bool = False) -> None:
        if self._current_handle is None:
            return
        from PIL import Image
        rotation = self._container.viewer.get_rotation()
        if rotation == 0:
            return
        src    = self._current_handle.path
        suffix = src.suffix.lower()
        try:
            if suffix == ".gif":
                self._save_rotated_gif(src, dest, rotation)
            else:
                with Image.open(src) as img:
                    rotated = img.rotate(-rotation, expand=True)
                    kwargs: dict = {}
                    out_suffix = dest.suffix.lower()
                    if out_suffix in (".jpg", ".jpeg"):
                        kwargs["quality"] = 95
                        exif = img.info.get("exif")
                        if exif:
                            kwargs["exif"] = exif
                    elif out_suffix in (".tif", ".tiff"):
                        kwargs["compression"] = "tiff_lzw"
                    rotated.save(dest, **kwargs)
            if invalidate:
                self._container.viewer._stop_movie()
                self._cache.invalidate(src)
                self._exit_rotate_mode()
                self._load_current()
            else:
                self._exit_rotate_mode()
            self._status_bar.showMessage(f"Saved: {dest.name}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Rotate Failed", str(exc))

    def _save_rotated_gif(self, src: Path, dest: Path, rotation: int) -> None:
        from PIL import Image
        with Image.open(src) as pil_img:
            n_frames = getattr(pil_img, "n_frames", 1)
            frames: list = []
            durations: list = []
            for i in range(n_frames):
                pil_img.seek(i)
                frame = pil_img.convert("RGBA")
                frames.append(frame.rotate(-rotation, expand=True))
                durations.append(pil_img.info.get("duration", 100))
        if frames:
            frames[0].save(
                dest, format="GIF", save_all=True,
                append_images=frames[1:],
                loop=0,
                duration=durations,
                disposal=2,
            )

    # ------------------------------------------------------------------ #
    # Flip                                                                 #
    # ------------------------------------------------------------------ #

    def _enter_flip_mode(self) -> None:
        if self._current_handle is None or self._flip_mode_active:
            return
        if self._slideshow_active:
            self._exit_slideshow()
        suffix = self._current_handle.path.suffix.lower()
        if suffix not in _FLIPPABLE_SUFFIXES:
            return
        self._flip_mode_active = True
        flip_bar = self._container.flip_bar
        flip_bar.reset()
        flip_bar.set_overwrite_allowed(suffix in _CROPPABLE_SUFFIXES)
        flip_bar.show()
        flip_bar.raise_()
        self._container._reposition_overlays()
        self._container.overlay.hide()
        flip_bar.flip_h_requested.connect(self._on_flip_h)
        flip_bar.flip_v_requested.connect(self._on_flip_v)
        flip_bar.cancel_requested.connect(self._exit_flip_mode)
        flip_bar.save_as_requested.connect(self._on_flip_save_as)
        flip_bar.overwrite_requested.connect(self._on_flip_overwrite)

    def _exit_flip_mode(self) -> None:
        if not self._flip_mode_active:
            return
        self._flip_mode_active = False
        flip_bar = self._container.flip_bar
        flip_bar.hide()
        self._container.viewer.set_flip(False, False)
        try:
            flip_bar.flip_h_requested.disconnect(self._on_flip_h)
            flip_bar.flip_v_requested.disconnect(self._on_flip_v)
            flip_bar.cancel_requested.disconnect(self._exit_flip_mode)
            flip_bar.save_as_requested.disconnect(self._on_flip_save_as)
            flip_bar.overwrite_requested.disconnect(self._on_flip_overwrite)
        except RuntimeError:
            pass

    def _on_flip_h(self) -> None:
        bar = self._container.flip_bar
        self._container.viewer.set_flip(bar.flip_h, bar.flip_v)

    def _on_flip_v(self) -> None:
        bar = self._container.flip_bar
        self._container.viewer.set_flip(bar.flip_h, bar.flip_v)

    def _on_flip_save_as(self) -> None:
        if self._current_handle is None:
            return
        path   = self._current_handle.path
        suffix = path.suffix.lower()
        fmt_filters = {
            ".jpg":  "JPEG (*.jpg *.jpeg)",
            ".jpeg": "JPEG (*.jpg *.jpeg)",
            ".png":  "PNG (*.png)",
            ".bmp":  "BMP (*.bmp)",
            ".tif":  "TIFF (*.tif *.tiff)",
            ".tiff": "TIFF (*.tif *.tiff)",
            ".webp": "WebP (*.webp)",
            ".gif":  "GIF (*.gif)",
        }
        default_filter = fmt_filters.get(suffix, "PNG (*.png)")
        all_filter = "All images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.gif)"
        default_path = str(path.parent / (path.stem + "_flipped" + path.suffix))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Flipped Image", default_path,
            f"{default_filter};;{all_filter}",
        )
        if out_path:
            self._save_flipped(Path(out_path))

    def _on_flip_overwrite(self) -> None:
        if self._current_handle is None:
            return
        self._save_flipped(self._current_handle.path, invalidate=True)

    def _save_flipped(self, dest: Path, *, invalidate: bool = False) -> None:
        if self._current_handle is None:
            return
        from PIL import Image, ImageOps
        bar    = self._container.flip_bar
        flip_h = bar.flip_h
        flip_v = bar.flip_v
        if not flip_h and not flip_v:
            return
        src    = self._current_handle.path
        suffix = src.suffix.lower()
        try:
            if suffix == ".gif":
                self._save_flipped_gif(src, dest, flip_h, flip_v)
            else:
                with Image.open(src) as img:
                    if flip_h:
                        img = ImageOps.mirror(img)
                    if flip_v:
                        img = ImageOps.flip(img)
                    kwargs: dict = {}
                    out_suffix = dest.suffix.lower()
                    if out_suffix in (".jpg", ".jpeg"):
                        kwargs["quality"] = 95
                        exif = img.info.get("exif")
                        if exif:
                            kwargs["exif"] = exif
                    elif out_suffix in (".tif", ".tiff"):
                        kwargs["compression"] = "tiff_lzw"
                    img.save(dest, **kwargs)
            if invalidate:
                self._container.viewer._stop_movie()
                self._cache.invalidate(src)
                self._exit_flip_mode()
                self._load_current()
            else:
                self._exit_flip_mode()
            self._status_bar.showMessage(f"Saved: {dest.name}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Flip Failed", str(exc))

    def _save_flipped_gif(self, src: Path, dest: Path, flip_h: bool, flip_v: bool) -> None:
        from PIL import Image, ImageOps
        with Image.open(src) as pil_img:
            n_frames = getattr(pil_img, "n_frames", 1)
            frames: list = []
            durations: list = []
            for i in range(n_frames):
                pil_img.seek(i)
                frame = pil_img.convert("RGBA")
                if flip_h:
                    frame = ImageOps.mirror(frame)
                if flip_v:
                    frame = ImageOps.flip(frame)
                frames.append(frame)
                durations.append(pil_img.info.get("duration", 100))
        if frames:
            frames[0].save(
                dest, format="GIF", save_all=True,
                append_images=frames[1:],
                loop=0,
                duration=durations,
                disposal=2,
            )

    # ------------------------------------------------------------------ #
    # Resize                                                               #
    # ------------------------------------------------------------------ #

    def _enter_resize_mode(self) -> None:
        if self._current_handle is None or self._resize_mode_active:
            return
        if self._slideshow_active:
            self._exit_slideshow()
        suffix = self._current_handle.path.suffix.lower()
        if suffix not in _RESIZABLE_SUFFIXES:
            return
        self._resize_mode_active = True
        resize_bar = self._container.resize_bar
        resize_bar.reset()
        m = self._current_handle.metadata
        resize_bar.set_original_size(m.width, m.height)
        resize_bar.set_overwrite_allowed(suffix in _CROPPABLE_SUFFIXES)
        resize_bar.show()
        resize_bar.raise_()
        self._container._reposition_overlays()
        self._container.overlay.hide()
        resize_bar.cancel_requested.connect(self._exit_resize_mode)
        resize_bar.save_as_requested.connect(self._on_resize_save_as)
        resize_bar.overwrite_requested.connect(self._on_resize_overwrite)

    def _exit_resize_mode(self) -> None:
        if not self._resize_mode_active:
            return
        self._resize_mode_active = False
        resize_bar = self._container.resize_bar
        resize_bar.hide()
        try:
            resize_bar.cancel_requested.disconnect(self._exit_resize_mode)
            resize_bar.save_as_requested.disconnect(self._on_resize_save_as)
            resize_bar.overwrite_requested.disconnect(self._on_resize_overwrite)
        except RuntimeError:
            pass

    def _on_resize_save_as(self) -> None:
        if self._current_handle is None:
            return
        params = self._container.resize_bar.get_params()
        if params["batch"]:
            self._do_resize_batch(overwrite=False, params=params)
        else:
            path   = self._current_handle.path
            suffix = params["suffix"] or "_resized"
            default_path = str(path.parent / (path.stem + suffix + path.suffix))
            fmt_filters = {
                ".jpg":  "JPEG (*.jpg *.jpeg)",
                ".jpeg": "JPEG (*.jpg *.jpeg)",
                ".png":  "PNG (*.png)",
                ".bmp":  "BMP (*.bmp)",
                ".tif":  "TIFF (*.tif *.tiff)",
                ".tiff": "TIFF (*.tif *.tiff)",
                ".webp": "WebP (*.webp)",
            }
            sfx = path.suffix.lower()
            default_filter = fmt_filters.get(sfx, "PNG (*.png)")
            all_filter = "All images (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)"
            out_path, _ = QFileDialog.getSaveFileName(
                self, "Save Resized Image", default_path,
                f"{default_filter};;{all_filter}",
            )
            if out_path:
                self._do_resize_single(Path(out_path), params, invalidate=False)

    def _on_resize_overwrite(self) -> None:
        if self._current_handle is None:
            return
        params = self._container.resize_bar.get_params()
        if params["batch"]:
            self._do_resize_batch(overwrite=True, params=params)
        else:
            self._do_resize_single(self._current_handle.path, params, invalidate=True)

    def _do_resize_single(self, dest: Path, params: dict, *, invalidate: bool) -> None:
        if self._current_handle is None:
            return
        from PIL import Image
        src = self._current_handle.path
        try:
            with Image.open(src) as img:
                out = _apply_resize(img.copy(), params)
                _save_resized(out, dest, src.suffix.lower())
            if invalidate:
                self._cache.invalidate(src)
                self._exit_resize_mode()
                self._load_current()
            else:
                self._exit_resize_mode()
            self._status_bar.showMessage(f"Saved: {dest.name}", 4000)
        except Exception as exc:
            QMessageBox.warning(self, "Resize Failed", str(exc))

    def _do_resize_batch(self, *, overwrite: bool, params: dict) -> None:
        suffix = params["suffix"] or "_resized"
        jobs: list = []
        for entry in self._folder_model._entries:
            if entry.is_dir:
                continue
            src = entry.path
            if src.suffix.lower() not in _RESIZABLE_SUFFIXES:
                continue
            dest = src if overwrite else src.parent / (src.stem + suffix + src.suffix)
            jobs.append((src, dest))
        if not jobs:
            return
        n = len(jobs)
        self._status_bar.showMessage(f"Resizing {n} image(s)…")
        worker = _ResizeBatchWorker(jobs, params)
        worker.signals.finished.connect(self._on_resize_batch_done)
        self._exit_resize_mode()
        # Reuse the adjust pool (1-thread, sequential)
        self._adjust_pool.start(worker)

    def _on_resize_batch_done(self, done: int, errors: int) -> None:
        if errors:
            self._status_bar.showMessage(
                f"Resize complete: {done} saved, {errors} error(s).", 6000
            )
        else:
            self._status_bar.showMessage(f"Resize complete: {done} image(s) saved.", 4000)
        # Invalidate cache for current image in case it was overwritten
        if self._current_handle is not None:
            self._cache.invalidate(self._current_handle.path)
            self._load_current()

    def _open_settings(self) -> None:
        prev_recursive = self._settings.filmstrip_recursive
        dlg = SettingsDialog(self._settings, self._container.viewer, self, app=self._app)
        dlg.exec()
        if self._settings.filmstrip_recursive != prev_recursive:
            folder = self._folder_model.current_folder
            if folder is not None:
                self._load_folder_into_model(folder)
                self._grid.refresh()
                self._thumbnails_loaded = False
                entry = self._folder_model.current
                if entry:
                    self._grid.select_path(entry.path)

    def _show_about(self) -> None:
        dlg = AboutDialog(self)
        dlg.exec()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Right:
            self._go_next()
        elif key == Qt.Key.Key_Left:
            self._go_prev()
        elif key == Qt.Key.Key_Delete:
            self._delete_current_file()
        elif key == Qt.Key.Key_F11:
            self._toggle_fullscreen()
        elif key == Qt.Key.Key_Escape:
            if self._crop_mode_active:
                self._exit_crop_mode()
            elif self._adjust_mode_active:
                self._exit_adjust_mode()
            elif self._rotate_mode_active:
                self._exit_rotate_mode()
            elif self._flip_mode_active:
                self._exit_flip_mode()
            elif self._resize_mode_active:
                self._exit_resize_mode()
            elif self._slideshow_active:
                self._exit_slideshow()
            elif self.isFullScreen():
                self.showNormal()
        else:
            super().keyPressEvent(event)
