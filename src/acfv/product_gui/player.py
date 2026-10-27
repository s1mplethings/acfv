"""A single reusable media player shared by recording and review workspaces."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .viewmodels import duration_text


class TimelineSlider(QSlider):
    """Compact semantic timeline with Moment and selected-range overlays."""

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self._duration = 0
        self._markers: list[tuple[int, int]] = []
        self._selected: tuple[int, int] | None = None

    def set_markers(self, duration_ms: int, markers=(), selected=None) -> None:
        self._duration = max(0, int(duration_ms))
        self._markers = [(int(start), int(end)) for start, end in markers]
        self._selected = selected
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if not self._duration:
            return
        painter = QPainter(self)
        width = max(1, self.width() - 10)
        if self._selected:
            start, end = self._selected
            x = 5 + round(width * start / self._duration)
            extent = max(2, round(width * (end - start) / self._duration))
            painter.fillRect(x, 2, extent, max(2, self.height() - 4), QColor(124, 92, 255, 70))
        painter.setPen(QPen(QColor("#f5b942"), 2))
        for start, _end in self._markers[:250]:
            x = 5 + round(width * start / self._duration)
            painter.drawLine(x, 2, x, max(2, self.height() - 3))


class MediaPlayer(QWidget):
    media_error = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.video.setMinimumHeight(220)
        self.video.setStyleSheet("background: #050608; border-radius: 10px")
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.toggle)
        self.seek = TimelineSlider()
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("00:00 / 00:00")
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setMaximumWidth(100)
        self.volume.valueChanged.connect(self.player.setVolume)
        self.speed = QComboBox()
        for value in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            self.speed.addItem(f"{value:g}×", value)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(float(self.speed.currentData())))
        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.time)
        controls.addWidget(QLabel("音量"))
        controls.addWidget(self.volume)
        controls.addWidget(self.speed)
        self.external_button = QPushButton("系统播放器打开")
        self.external_button.setVisible(False)
        self.external_button.clicked.connect(self.open_external)
        controls.addWidget(self.external_button)
        self.error_label = QLabel("")
        self.error_label.setProperty("muted", True)
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.error_label)
        layout.addLayout(controls)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(self._duration)
        self.player.stateChanged.connect(self._state)
        self.player.error.connect(lambda *_: self._show_media_error(self.player.errorString()))
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.seek_relative(-5000))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.seek_relative(5000))
        self._path = ""

    @property
    def media_path(self) -> str:
        return self._path

    def load(self, path: str, *, position_ms: int = 0, autoplay: bool = False) -> None:
        self.player.stop()
        self._path = path
        if not path or not Path(path).is_file():
            self.player.setMedia(QMediaContent())
            self._show_media_error("媒体文件不存在，请重新关联文件。")
            return
        self.error_label.setVisible(False)
        self.external_button.setVisible(False)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(Path(path).resolve()))))
        self.player.setPosition(max(0, int(position_ms)))
        if autoplay:
            self.player.play()

    def seek_to(self, position_ms: int) -> None:
        self.player.setPosition(max(0, int(position_ms)))

    def seek_relative(self, delta_ms: int) -> None:
        self.seek_to(self.player.position() + delta_ms)

    def set_markers(self, duration_ms: int, markers=(), selected=None) -> None:
        self.seek.set_markers(duration_ms, markers, selected)

    def open_external(self) -> None:
        if self._path and Path(self._path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._path).resolve())))

    def _show_media_error(self, message: str) -> None:
        detail = message.strip() or "当前 Qt 媒体后端无法解码此文件。"
        self.error_label.setText(f"播放器不可用：{detail}")
        self.error_label.setVisible(True)
        self.external_button.setVisible(bool(self._path and Path(self._path).is_file()))
        self.media_error.emit(detail)

    def toggle(self) -> None:
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        elif self._path:
            self.player.play()

    def _position(self, value: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(value)
        self.time.setText(f"{duration_text(value)} / {duration_text(self.player.duration())}")

    def _duration(self, value: int) -> None:
        self.seek.setRange(0, max(0, value))
        self._position(self.player.position())

    def _state(self, value: int) -> None:
        self.play_button.setText("暂停" if value == QMediaPlayer.PlayingState else "播放")

    def stop(self) -> None:
        self.player.stop()

