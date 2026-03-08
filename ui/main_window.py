"""Application main window."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRect, QThreadPool, QPoint, Signal, QEvent
from PySide6.QtCore import QFile
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QMouseEvent, QMovie
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStackedWidget, QFileDialog, QMessageBox, QStatusBar, QLabel, QPushButton,
)

from core.image_loader import ImageLoader, ImageHandle
from core.cache_manager import CacheManager
from models.folder_model import FolderModel, _MEDIA_EXTENSIONS
from ui.about_dialog import AboutDialog
from ui.crop_bar import CropBar
from ui.settings_dialog import SettingsDialog
from ui.media_player import MediaPlayer
from ui.image_viewer import ImageViewer
from ui.overlay_bar import OverlayBar
from ui.navigator_widget import NavigatorWidget
from ui.grid_view import GridView
from ui.spinner_widget import SpinnerWidget
from utils.threading import LoadImageWorker, ThumbnailWorker, FullResWorker, ThreadWorker
from utils.settings_manager import SettingsManager

log = logging.getLogger(__name__)


_ALWAYS_ANIMATED = frozenset((".gif",))

_CROPPABLE_SUFFIXES = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp",
})


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
        self.crop_bar     = CropBar(self)
        self.overlay.hide()
        self.crop_bar.hide()

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
        self._tray_available: bool = False
        self._crop_mode_active: bool = False
        self._app = None  # set by LumaApp after construction

        self.setWindowTitle("Luma Viewer")
        self.resize(1280, 800)
        self._build_ui()
        self._build_menus()
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

        splitter_state = self._settings.load_splitter_state()
        if splitter_state:
            self.centralWidget().restoreState(splitter_state)  # type: ignore[union-attr]

        stretch = self._settings.stretch_small
        self._stretch_act.setChecked(stretch)
        self._container.viewer.set_stretch_small(stretch)

        self._container.viewer.set_backdrop_color(QColor(self._settings.backdrop_color))

        if self._settings.filmstrip_visible:
            self._left_panel.show()

        if self._settings.start_fullscreen:
            self.showFullScreen()

        last_folder = self._settings.last_folder
        if last_folder:
            log.info("Restoring last folder: %s", last_folder)
            self._folder_model.load_folder(last_folder)
            self._grid.refresh()
            self._thumbnails_loaded = False
            self._update_nav_bar()
            self._load_current()

    def set_tray_available(self, available: bool) -> None:
        """Called by LumaApp after creating or destroying the tray icon."""
        self._tray_available = available

    def closeEvent(self, event) -> None:
        if self._tray_available and self._settings.close_to_tray:
            # Hide to tray instead of quitting
            event.ignore()
            self.hide()
        else:
            self._settings.save_geometry(self.saveGeometry())
            splitter = self.centralWidget()
            if hasattr(splitter, "saveState"):
                self._settings.save_splitter_state(splitter.saveState())
            super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # ---- left panel ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Nav bar: [↑]  folder name
        nav_bar = QWidget()
        nav_bar.setFixedHeight(28)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(4, 2, 4, 2)
        nav_layout.setSpacing(4)
        self._nav_up_btn = QPushButton("↑")
        self._nav_up_btn.setFixedSize(22, 22)
        self._nav_up_btn.setToolTip("Go to parent folder")
        self._nav_up_btn.setEnabled(False)
        self._nav_label = QLabel("")
        self._nav_label.setStyleSheet("color: #aaa; font-size: 11px;")
        nav_layout.addWidget(self._nav_up_btn)
        nav_layout.addWidget(self._nav_label, stretch=1)
        left_layout.addWidget(nav_bar)

        self._grid = GridView(self._folder_model, left)
        left_layout.addWidget(self._grid, stretch=1)
        left.setMinimumWidth(180)
        left.setMaximumWidth(260)

        # ---- centre ----
        self._container = ViewerContainer()

        # ---- splitter ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._container)
        splitter.setSizes([200, 1080])
        self._left_panel = left
        left.hide()

        self.setCentralWidget(splitter)

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
        open_act = QAction("&Open…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_act)
        open_folder_act = QAction("Open &Folder…", self)
        open_folder_act.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_folder_act.triggered.connect(self.open_folder_dialog)
        file_menu.addAction(open_folder_act)
        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # View
        view_menu = mb.addMenu("&View")
        fit_act = QAction("&Fit to Window", self)
        fit_act.setShortcut(QKeySequence("F"))
        fit_act.triggered.connect(self._container.viewer.set_fit_mode)
        view_menu.addAction(fit_act)

        one_act = QAction("&Actual Size (1:1)", self)
        one_act.setShortcut(QKeySequence("1"))
        one_act.triggered.connect(self._container.viewer.set_one_to_one)
        view_menu.addAction(one_act)

        full_act = QAction("&Fullscreen", self)
        full_act.setShortcut(QKeySequence("F11"))
        full_act.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(full_act)

        view_menu.addSeparator()
        self._stretch_act = QAction("&Stretch Small Images", self)
        self._stretch_act.setCheckable(True)
        self._stretch_act.setShortcut(QKeySequence("S"))
        self._stretch_act.toggled.connect(self._on_stretch_toggled)
        view_menu.addAction(self._stretch_act)

        # Edit
        edit_menu = mb.addMenu("&Edit")
        self._act_crop = QAction("&Crop…", self)
        self._act_crop.setShortcut(QKeySequence("C"))
        self._act_crop.setEnabled(False)
        self._act_crop.triggered.connect(self._enter_crop_mode)
        edit_menu.addAction(self._act_crop)
        edit_menu.addSeparator()
        settings_act = QAction("&Settings…", self)
        settings_act.setShortcut(QKeySequence("Ctrl+,"))
        settings_act.triggered.connect(self._open_settings)
        edit_menu.addAction(settings_act)

        # Help
        help_menu = mb.addMenu("&Help")
        about_act = QAction("&About Luma…", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

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
        self._nav_up_btn.clicked.connect(self._go_up)
        self._container.navigator.pan_requested.connect(self._on_navigator_pan)
        self._container.toggle_filmstrip.connect(self._toggle_filmstrip)
        self._container.media_player.error_occurred.connect(
            lambda msg: self._status_bar.showMessage(f"Media error: {msg}", 5000)
        )

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

    def _open_folder(self, folder: Path) -> None:
        self._container.viewer._stop_movie()
        self._container.media_player.stop()
        self._folder_model.load_folder(folder)
        self._settings.last_folder = folder
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
            self._settings.last_folder = path.parent
            self._grid.refresh()
            self._thumbnails_loaded = False
            self._update_nav_bar()

        self._grid.select_path(path)
        self._load_current()

    # ------------------------------------------------------------------ #
    # Image loading                                                        #
    # ------------------------------------------------------------------ #

    def _load_current(self) -> None:
        if self._crop_mode_active:
            self._exit_crop_mode()
        entry = self._folder_model.current
        if entry is None:
            return
        self._lbl_path.setText(str(entry.path))
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
            self._load_folder_thumbnails()

    def _load_folder_thumbnails(self) -> None:
        """Dispatch one ThumbnailWorker per image in the current folder."""
        for entry in self._folder_model:
            if entry.is_dir:
                continue
            if entry.path.suffix.lower() in _MEDIA_EXTENSIONS:
                continue  # decoders cannot produce thumbnails for media files
            worker = ThumbnailWorker(entry.path, self._loader, thumb_size=256)
            worker.signals.ready.connect(self._on_thumbnail_ready)
            worker.signals.error.connect(self._on_thumbnail_error)
            self._thumb_pool.start(worker)

    def _on_thumbnail_ready(self, path: Path, image: QImage) -> None:
        self._grid.set_thumbnail(path, image)

    def _on_thumbnail_error(self, path: Path, msg: str) -> None:
        log.debug("Thumb error %s: %s", path, msg)

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

    def _load_drives(self) -> None:
        self._container.viewer._stop_movie()
        self._container.media_player.stop()
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
            return
        self._nav_label.setText(folder.name or folder.drive or str(folder))
        self._nav_label.setToolTip(str(folder))
        self._nav_up_btn.setEnabled(True)

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

    def _toggle_filmstrip(self) -> None:
        self._left_panel.setVisible(not self._left_panel.isVisible())

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

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._settings, self._container.viewer, self, app=self._app)
        dlg.exec()

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
            elif self.isFullScreen():
                self.showNormal()
        else:
            super().keyPressEvent(event)
