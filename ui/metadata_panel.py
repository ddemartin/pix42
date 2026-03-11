"""Metadata viewer/editor panel (right-side dock)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QSizePolicy,
)

from core.decoder_base import ImageMetadata

# Formats we can write EXIF tags to
_WRITABLE_SUFFIXES = frozenset({".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp"})

# Formats where piexif handles lossless JPEG in-place edit
_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})


def _decode_xp_tag(val) -> str:
    """Decode a Windows XP* EXIF tag (UTF-16LE bytes) to a plain string."""
    if isinstance(val, bytes):
        return val.decode("utf-16-le").rstrip("\x00")
    return str(val).rstrip("\x00") if val else ""


def _fmt_exposure(val) -> str:
    try:
        if isinstance(val, tuple):
            n, d = val[0], val[1]
        else:
            n, d = float(val), 1
        if d == 0:
            return "?"
        v = n / d
        if v >= 1:
            return f"{v:.1f}s"
        return f"1/{round(d / n)}s"
    except Exception:
        return str(val)


def _fmt_fnumber(val) -> str:
    try:
        if isinstance(val, tuple):
            v = val[0] / val[1]
        else:
            v = float(val)
        return f"f/{v:.1f}"
    except Exception:
        return str(val)


def _fmt_focal(val) -> str:
    try:
        if isinstance(val, tuple):
            v = val[0] / val[1]
        else:
            v = float(val)
        return f"{v:.0f} mm"
    except Exception:
        return str(val)


class _SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            "color: #777; font-size: 10px; font-weight: bold; "
            "padding: 10px 0 3px 0; letter-spacing: 1px;"
        )


class _InfoRow(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(6)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #777; font-size: 11px;")
        lbl.setFixedWidth(70)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value = QLabel("—")
        self._value.setStyleSheet("color: #bbb; font-size: 11px;")
        self._value.setWordWrap(True)
        self._value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(lbl)
        layout.addWidget(self._value, stretch=1)

    def set_value(self, text: str) -> None:
        self._value.setText(text or "—")


class _EditRow(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(2)
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888; font-size: 10px;")
        self._edit = QLineEdit()
        self._edit.setStyleSheet("""
            QLineEdit {
                background: #2a2a2a;
                color: #ddd;
                border: 1px solid #3a3a3a;
                border-radius: 3px;
                padding: 4px 7px;
                font-size: 11px;
            }
            QLineEdit:focus { border-color: #4a8ccf; }
            QLineEdit:disabled { color: #555; background: #222; }
        """)
        layout.addWidget(lbl)
        layout.addWidget(self._edit)

    @property
    def edit(self) -> QLineEdit:
        return self._edit

    def value(self) -> str:
        return self._edit.text()

    def set_value(self, text: str) -> None:
        self._edit.setText(text)

    def set_enabled(self, enabled: bool) -> None:
        self._edit.setEnabled(enabled)


class MetadataPanel(QWidget):
    """Right-side metadata viewer and editor."""

    closed = Signal()
    save_requested = Signal(dict, list)  # (fields: dict[str,str], paths: list[Path])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Optional[Path] = None
        self._selected_paths: list[Path] = []
        self._build_ui()
        self.setMinimumWidth(190)
        self.setMaximumWidth(320)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header ----
        header = QWidget()
        header.setStyleSheet("background: #252525; border-bottom: 1px solid #333;")
        header.setFixedHeight(28)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 4, 0)
        hl.setSpacing(4)
        title = QLabel("Metadata")
        title.setStyleSheet("color: #ccc; font-size: 12px; font-weight: bold;")
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setToolTip("Close panel")
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #777; border: none; font-size: 16px; }"
            "QPushButton:hover { color: #fff; }"
        )
        close_btn.clicked.connect(self.closed)
        hl.addWidget(title, stretch=1)
        hl.addWidget(close_btn)
        layout.addWidget(header)

        # ---- scroll area ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #1e1e1e; } QScrollBar:vertical { width: 6px; }")
        content = QWidget()
        content.setStyleSheet("background: #1e1e1e;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(10, 0, 10, 10)
        cl.setSpacing(0)

        # Camera (read-only)
        cl.addWidget(_SectionLabel("Camera"))
        self._row_camera   = _InfoRow("Camera")
        self._row_datetime = _InfoRow("Date")
        self._row_shutter  = _InfoRow("Shutter")
        self._row_aperture = _InfoRow("Aperture")
        self._row_iso      = _InfoRow("ISO")
        self._row_focal    = _InfoRow("Focal")
        for row in (self._row_camera, self._row_datetime, self._row_shutter,
                    self._row_aperture, self._row_iso, self._row_focal):
            cl.addWidget(row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333; margin: 6px 0;")
        cl.addWidget(sep)

        # Edit (writable)
        cl.addWidget(_SectionLabel("Edit"))
        self._edit_title       = _EditRow("Title")
        self._edit_description = _EditRow("Description")
        self._edit_keywords    = _EditRow("Keywords")
        self._edit_keywords.edit.setPlaceholderText("e.g. sunset; travel; landscape")
        self._edit_copyright   = _EditRow("Copyright")
        self._edit_artist      = _EditRow("Artist")
        for row in (self._edit_title, self._edit_description, self._edit_keywords,
                    self._edit_copyright, self._edit_artist):
            cl.addWidget(row)

        cl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # ---- footer ----
        footer = QWidget()
        footer.setStyleSheet("background: #252525; border-top: 1px solid #333;")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(8, 6, 8, 8)
        fl.setSpacing(4)
        self._save_btn = QPushButton("Save to current file")
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet("""
            QPushButton {
                background: #2e6da4; color: #fff; border: none;
                border-radius: 4px; padding: 5px 10px; font-size: 11px;
            }
            QPushButton:hover { background: #3a7fc1; }
            QPushButton:disabled { background: #2a2a2a; color: #555; }
        """)
        self._save_btn.clicked.connect(self._on_save)
        self._note_lbl = QLabel("")
        self._note_lbl.setStyleSheet("color: #666; font-size: 10px;")
        self._note_lbl.setWordWrap(True)
        fl.addWidget(self._save_btn)
        fl.addWidget(self._note_lbl)
        layout.addWidget(footer)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_image(self, path: Optional[Path], metadata: Optional[ImageMetadata]) -> None:
        """Populate panel for the given image."""
        self._current_path = path
        self._clear()
        if path is None or metadata is None:
            self._save_btn.setEnabled(False)
            return

        exif = metadata.exif or {}

        # Camera
        make  = str(exif.get("Make",  "") or "").strip()
        model = str(exif.get("Model", "") or "").strip()
        camera = f"{make} {model}".strip() if make or model else "—"
        self._row_camera.set_value(camera)

        # Date
        dt = exif.get("DateTimeOriginal") or exif.get("DateTime", "")
        if dt:
            # EXIF datetime: "YYYY:MM:DD HH:MM:SS" → readable
            dt = str(dt).replace(":", "-", 2)
        self._row_datetime.set_value(str(dt) if dt else "—")

        # Exposure
        exp = exif.get("ExposureTime")
        self._row_shutter.set_value(_fmt_exposure(exp) if exp is not None else "—")

        # Aperture
        fn = exif.get("FNumber")
        self._row_aperture.set_value(_fmt_fnumber(fn) if fn is not None else "—")

        # ISO
        iso = exif.get("ISOSpeedRatings")
        self._row_iso.set_value(str(iso) if iso is not None else "—")

        # Focal length
        focal = exif.get("FocalLength")
        focal35 = exif.get("FocalLengthIn35mmFilm")
        if focal is not None:
            txt = _fmt_focal(focal)
            if focal35:
                txt += f"  ({focal35} mm equiv)"
            self._row_focal.set_value(txt)
        else:
            self._row_focal.set_value("—")

        # Editable fields
        self._edit_title.set_value(_decode_xp_tag(exif.get("XPTitle") or ""))
        self._edit_description.set_value(str(exif.get("ImageDescription", "") or "").strip())
        self._edit_keywords.set_value(_decode_xp_tag(exif.get("XPKeywords") or ""))
        self._edit_copyright.set_value(str(exif.get("Copyright", "") or "").strip())
        self._edit_artist.set_value(str(exif.get("Artist", "") or "").strip())

        writable = path.suffix.lower() in _WRITABLE_SUFFIXES
        for row in (self._edit_title, self._edit_description, self._edit_keywords,
                    self._edit_copyright, self._edit_artist):
            row.set_enabled(writable)
        self._save_btn.setEnabled(writable)
        if not writable:
            self._note_lbl.setText(
                f"Editing not supported for {path.suffix.upper() or 'this format'}"
            )
        else:
            self._update_save_label()

    def set_selected_paths(self, paths: list[Path]) -> None:
        """Called when filmstrip multi-selection changes."""
        self._selected_paths = paths
        self._update_save_label()

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _update_save_label(self) -> None:
        n = len(self._selected_paths)
        if n > 1:
            self._save_btn.setText(f"Save to {n} selected files")
        else:
            self._save_btn.setText("Save to current file")
        if self._current_path and self._current_path.suffix.lower() in _WRITABLE_SUFFIXES:
            self._note_lbl.setText("")

    def _clear(self) -> None:
        for row in (self._row_camera, self._row_datetime, self._row_shutter,
                    self._row_aperture, self._row_iso, self._row_focal):
            row.set_value("—")
        for row in (self._edit_title, self._edit_description, self._edit_keywords,
                    self._edit_copyright, self._edit_artist):
            row.set_value("")
            row.set_enabled(False)
        self._note_lbl.setText("")

    def _on_save(self) -> None:
        fields = {
            "title":       self._edit_title.value(),
            "description": self._edit_description.value(),
            "keywords":    self._edit_keywords.value(),
            "copyright":   self._edit_copyright.value(),
            "artist":      self._edit_artist.value(),
        }
        if len(self._selected_paths) > 1:
            paths = self._selected_paths
        else:
            paths = [self._current_path] if self._current_path else []
        if paths:
            self.save_requested.emit(fields, paths)
