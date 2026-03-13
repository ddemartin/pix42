"""About dialog for Pix42."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from config import ASSETS_DIR

_CREDITS = [
    ("PySide6",    "Qt for Python — cross-platform GUI framework"),
    ("Pillow",     "Image reading and processing (JPEG, PNG, TIFF, WebP, …)"),
    ("psd-tools",  "Adobe Photoshop PSD layer compositing"),
    ("rawpy",      "RAW camera file decoding via LibRaw"),
    ("astropy",    "FITS astronomical image support"),
    ("NumPy",      "Numerical array operations"),
    ("psutil",     "System resource monitoring"),
    ("CuPy",       "GPU-accelerated array operations (optional, requires CUDA)"),
]

_STYLE = """
QDialog {
    background: #1e1e1e;
}
QLabel {
    color: #ccc;
    background: transparent;
}
QLabel#appName {
    color: #fff;
    font-size: 22px;
    font-weight: bold;
}
QLabel#tagline {
    color: #888;
    font-size: 11px;
}
QLabel#copyright {
    color: #777;
    font-size: 11px;
}
QLabel#sectionHeader {
    color: #aaa;
    font-size: 11px;
    font-weight: bold;
    border-bottom: 1px solid #333;
    padding-bottom: 2px;
}
QLabel#depName {
    color: #ddd;
    font-size: 11px;
    font-weight: bold;
}
QLabel#depDesc {
    color: #888;
    font-size: 11px;
}
QPushButton#linkBtn {
    background: transparent;
    color: #5a9fd4;
    border: none;
    font-size: 11px;
    padding: 0;
    text-align: left;
}
QPushButton#linkBtn:hover {
    color: #7fbfff;
    text-decoration: underline;
}
QPushButton#coffeeBtn {
    background: #ff5e5b;
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: bold;
    padding: 8px 18px;
}
QPushButton#coffeeBtn:hover  { background: #ff7a77; }
QPushButton#coffeeBtn:pressed { background: #e04040; }
QPushButton#closeBtn {
    background: #333;
    color: #ccc;
    border: 1px solid #444;
    border-radius: 6px;
    font-size: 12px;
    padding: 6px 18px;
}
QPushButton#closeBtn:hover  { background: #444; color: #fff; }
QPushButton#closeBtn:pressed { background: #555; }
QFrame#divider {
    color: #333;
}
"""


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Pix42")
        self.setFixedSize(420, 560)
        self.setModal(True)
        self.setStyleSheet(_STYLE)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 20)
        root.setSpacing(0)

        # --- Icon + app name ---
        header = QHBoxLayout()
        header.setSpacing(16)

        icon_path = ASSETS_DIR / "app" / "icon.svg"
        if icon_path.exists():
            icon_widget = QSvgWidget(str(icon_path))
            icon_widget.setFixedSize(72, 72)
            header.addWidget(icon_widget)
        else:
            placeholder = QLabel("☀")
            placeholder.setFixedSize(72, 72)
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("font-size: 48px; color: #5a9fd4;")
            header.addWidget(placeholder)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name_lbl = QLabel("Pix42")
        name_lbl.setObjectName("appName")
        tag_lbl = QLabel("A fast, modern image viewer")
        tag_lbl.setObjectName("tagline")
        title_col.addWidget(name_lbl)
        title_col.addWidget(tag_lbl)
        title_col.addStretch()
        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)

        root.addSpacing(6)

        # Copyright
        cr_lbl = QLabel("© 2026 De Martin Davide")
        cr_lbl.setObjectName("copyright")
        root.addWidget(cr_lbl)

        root.addSpacing(2)

        # Website link
        site_btn = QPushButton("www.demahub.com")
        site_btn.setObjectName("linkBtn")
        site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.demahub.com")))
        root.addWidget(site_btn)

        root.addSpacing(2)

        # Email link
        mail_btn = QPushButton("ddemartin@gmail.com")
        mail_btn.setObjectName("linkBtn")
        mail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mail_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("mailto:ddemartin@gmail.com")))
        root.addWidget(mail_btn)

        root.addSpacing(20)

        # Divider
        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(div)

        root.addSpacing(14)

        # Credits header
        credits_hdr = QLabel("Open-source dependencies")
        credits_hdr.setObjectName("sectionHeader")
        root.addWidget(credits_hdr)

        root.addSpacing(10)

        for dep_name, dep_desc in _CREDITS:
            row = QHBoxLayout()
            row.setSpacing(0)
            name = QLabel(dep_name)
            name.setObjectName("depName")
            name.setFixedWidth(80)
            desc = QLabel(dep_desc)
            desc.setObjectName("depDesc")
            desc.setWordWrap(True)
            row.addWidget(name)
            row.addWidget(desc, stretch=1)
            root.addLayout(row)
            root.addSpacing(5)

        root.addStretch()

        div2 = QFrame()
        div2.setObjectName("divider")
        div2.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(div2)

        root.addSpacing(14)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        coffee_btn = QPushButton("☕  Buy me a Coffee")
        coffee_btn.setObjectName("coffeeBtn")
        coffee_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        coffee_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://ko-fi.com/ddemartin"))
        )

        close_btn = QPushButton("Close")
        close_btn.setObjectName("closeBtn")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(coffee_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)
