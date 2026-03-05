"""Minimal media player widget for video and audio files."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSlider, QSizePolicy,
    QStackedWidget, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

_CTRL_STYLE = """
QWidget#ctrlBar {
    background: rgba(28, 28, 28, 0.97);
    border-top: 1px solid #333;
}
QPushButton#mediaBtn {
    background: rgba(45, 45, 45, 0.9);
    color: #ccc;
    border: 1px solid #555;
    border-radius: 4px;
    font-size: 13px;
    padding: 3px 10px;
    min-width: 32px;
}
QPushButton#mediaBtn:hover   { background: rgba(70, 130, 210, 0.85); color: #fff; border-color: #5a9fd4; }
QPushButton#mediaBtn:pressed { background: rgba(50, 100, 170, 0.9); }
QPushButton#mediaBtn:disabled { color: #555; border-color: #444; background: rgba(35,35,35,0.9); }
QSlider::groove:horizontal {
    height: 4px;
    background: #3a3a3a;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #5a9fd4;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    background: #ddd;
    border-radius: 6px;
    margin: -4px 0;
}
QLabel#timeLabel {
    color: #999;
    font-size: 11px;
    min-width: 96px;
}
QLabel#volLabel {
    color: #777;
    font-size: 11px;
}
"""


def _fmt_time(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class MediaPlayer(QWidget):
    """
    Minimal media player: video + audio, with play/pause/stop/seek/volume.

    Signals
    -------
    error_occurred(str)  — emitted when QMediaPlayer reports an error.
    """

    error_occurred = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)

        self._video_widget = QVideoWidget(self)
        self._player.setVideoOutput(self._video_widget)

        # Audio placeholder (shown for audio-only files)
        self._audio_placeholder = QLabel("♪", self)
        self._audio_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._audio_placeholder.setStyleSheet(
            "font-size: 64px; color: #444; background: #1a1a1a;"
        )
        self._audio_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Stack: video widget (0) or audio placeholder (1)
        self._view_stack = QStackedWidget(self)
        self._view_stack.addWidget(self._video_widget)
        self._view_stack.addWidget(self._audio_placeholder)

        # --- Controls ---
        self._play_btn  = QPushButton("▶", self)
        self._pause_btn = QPushButton("⏸", self)
        self._stop_btn  = QPushButton("■", self)
        for btn in (self._play_btn, self._pause_btn, self._stop_btn):
            btn.setObjectName("mediaBtn")

        self._seek = QSlider(Qt.Orientation.Horizontal, self)
        self._seek.setRange(0, 0)
        self._seek.setSingleStep(1000)
        self._seek.setPageStep(5000)

        self._time_lbl = QLabel("0:00 / 0:00", self)
        self._time_lbl.setObjectName("timeLabel")
        self._time_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        vol_lbl = QLabel("Vol", self)
        vol_lbl.setObjectName("volLabel")
        self._vol = QSlider(Qt.Orientation.Horizontal, self)
        self._vol.setRange(0, 100)
        self._vol.setValue(80)
        self._vol.setFixedWidth(80)
        self._vol.setToolTip("Volume")

        ctrl_bar = QWidget(self)
        ctrl_bar.setObjectName("ctrlBar")
        ctrl_bar.setStyleSheet(_CTRL_STYLE)
        ctrl_layout = QHBoxLayout(ctrl_bar)
        ctrl_layout.setContentsMargins(10, 6, 10, 6)
        ctrl_layout.setSpacing(6)
        ctrl_layout.addWidget(self._play_btn)
        ctrl_layout.addWidget(self._pause_btn)
        ctrl_layout.addWidget(self._stop_btn)
        ctrl_layout.addWidget(self._seek, stretch=1)
        ctrl_layout.addWidget(self._time_lbl)
        ctrl_layout.addWidget(vol_lbl)
        ctrl_layout.addWidget(self._vol)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._view_stack, stretch=1)
        root.addWidget(ctrl_bar)

        # Signals
        self._play_btn.clicked.connect(self._player.play)
        self._pause_btn.clicked.connect(self._player.pause)
        self._stop_btn.clicked.connect(self._player.stop)
        self._vol.valueChanged.connect(lambda v: self._audio.setVolume(v / 100.0))
        self._seek.sliderMoved.connect(self._player.setPosition)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

        self._update_buttons(QMediaPlayer.PlaybackState.StoppedState)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def load(self, path: Path) -> None:
        """Load and immediately start playing *path*."""
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def stop(self) -> None:
        """Stop playback and release the source."""
        self._player.stop()
        self._player.setSource(QUrl())

    # ------------------------------------------------------------------ #
    # Slots                                                                #
    # ------------------------------------------------------------------ #

    def _on_position(self, pos: int) -> None:
        self._seek.blockSignals(True)
        self._seek.setValue(pos)
        self._seek.blockSignals(False)
        dur = self._player.duration()
        self._time_lbl.setText(f"{_fmt_time(pos)} / {_fmt_time(dur)}")

    def _on_duration(self, dur: int) -> None:
        self._seek.setRange(0, max(0, dur))

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        self._update_buttons(state)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            has_video = self._player.hasVideo()
            self._view_stack.setCurrentIndex(0 if has_video else 1)

    def _on_error(self, error: QMediaPlayer.Error, msg: str) -> None:
        log.error("Media error %s: %s", error, msg)
        self.error_occurred.emit(msg)

    def _update_buttons(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setEnabled(not playing)
        self._pause_btn.setEnabled(playing)
        self._stop_btn.setEnabled(state != QMediaPlayer.PlaybackState.StoppedState)

    # ------------------------------------------------------------------ #
    # Key handling                                                         #
    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._player.play()
        else:
            super().keyPressEvent(event)
