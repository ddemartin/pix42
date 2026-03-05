"""Generic thread worker infrastructure built on QThreadPool."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


# ------------------------------------------------------------------ #
# Generic worker                                                       #
# ------------------------------------------------------------------ #

class WorkerSignals(QObject):
    """Signals for ThreadWorker (must live on QObject)."""
    finished = Signal(object)   # result
    error    = Signal(str)      # error message
    progress = Signal(int)      # 0–100


class ThreadWorker(QRunnable):
    """
    Generic one-shot background worker.

    Usage::

        worker = ThreadWorker(my_function, arg1, key=val)
        worker.signals.finished.connect(on_done)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn       = fn
        self._args     = args
        self._kwargs   = kwargs
        self.signals   = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )


# ------------------------------------------------------------------ #
# Specialised image-load worker                                        #
# ------------------------------------------------------------------ #

class LoadImageSignals(QObject):
    finished = Signal(object)   # ImageHandle
    error    = Signal(str)


class LoadImageWorker(QRunnable):
    """
    Loads an image (metadata + preview) on a background thread.

    Emits ``signals.finished(ImageHandle)`` on success or
    ``signals.error(str)`` on failure.
    """

    def __init__(self, path: Path, loader: "Any") -> None:
        super().__init__()
        self._path   = path
        self._loader = loader
        self.signals = LoadImageSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            handle = self._loader.load(self._path)
            self.signals.finished.emit(handle)
        except Exception as exc:
            self.signals.error.emit(
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )


# ------------------------------------------------------------------ #
# Full-resolution refinement worker                                    #
# ------------------------------------------------------------------ #

class FullResSignals(QObject):
    ready = Signal(object, object)   # (Path, QImage)
    error = Signal(object, str)      # (Path, msg)


class FullResWorker(QRunnable):
    """
    Decodes the image at full (or near-full) resolution to refine the preview.

    Uses decode_preview with a very large max_size so no downscaling occurs
    for consumer-sized images. Emits ``signals.ready(path, image)`` on success.
    """

    def __init__(self, path: Path, loader: "Any",
                 cancel: Optional[threading.Event] = None) -> None:
        super().__init__()
        self._path   = path
        self._loader = loader
        self._cancel = cancel
        self.signals = FullResSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        if self._cancel and self._cancel.is_set():
            return
        try:
            image = self._loader.load_full(self._path)
            if self._cancel and self._cancel.is_set():
                return
            self.signals.ready.emit(self._path, image)
        except Exception as exc:
            self.signals.error.emit(self._path, str(exc))


# ------------------------------------------------------------------ #
# Thumbnail worker                                                     #
# ------------------------------------------------------------------ #

class ThumbnailSignals(QObject):
    ready = Signal(object, object)   # (Path, QImage)
    error = Signal(object, str)      # (Path, msg)


class ThumbnailWorker(QRunnable):
    """Generates a thumbnail for one image path."""

    def __init__(self, path: Path, loader: "Any", thumb_size: int = 256) -> None:
        super().__init__()
        self._path       = path
        self._loader     = loader
        self._thumb_size = thumb_size
        self.signals     = ThumbnailSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            decoder = self._loader._select_decoder(self._path)
            thumb   = decoder.decode_preview(self._path, self._thumb_size)
            self.signals.ready.emit(self._path, thumb)
        except Exception as exc:
            self.signals.error.emit(self._path, str(exc))
