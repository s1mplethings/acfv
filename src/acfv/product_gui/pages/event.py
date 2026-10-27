from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from ..components import PageHeader, StatusBadge, button, label
from ..player import MediaPlayer
from ..viewmodels import MomentVM, RecordingVM, duration_text


class EventPage(QWidget):
    back_requested = pyqtSignal()
    create_clip_requested = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.moment: MomentVM | None = None
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 20, 24, 16)
        row = QHBoxLayout(); row.addWidget(button("← 返回", self.back_requested.emit))
        self.header = PageHeader("Event", "Moment 的视频、上下文和候选操作。")
        row.addWidget(self.header, 1); row.addWidget(button("创建 Clip", self._create, primary=True))
        layout.addLayout(row)
        split = QSplitter()
        self.player = MediaPlayer(); split.addWidget(self.player)
        side = QWidget(); side_layout = QVBoxLayout(side)
        self.time = StatusBadge()
        self.summary = label("", role="sectionTitle"); self.summary.setWordWrap(True)
        self.transcript = QPlainTextEdit(); self.transcript.setReadOnly(True)
        side_layout.addWidget(self.time); side_layout.addWidget(self.summary); side_layout.addWidget(label("Transcript / Context", muted=True)); side_layout.addWidget(self.transcript, 1)
        split.addWidget(side); split.setSizes([760, 420])
        layout.addWidget(split, 1)

    def load(self, moment: MomentVM, recording: RecordingVM | None) -> None:
        self.moment = moment
        self.header.title.setText(moment.summary or "Event")
        self.header.subtitle.setText(moment.recording_title)
        self.time.set_state(f"{duration_text(moment.start_ms)} – {duration_text(moment.end_ms)}")
        self.summary.setText(moment.summary)
        self.transcript.setPlainText(moment.excerpt)
        if recording:
            self.player.load(recording.media_path, position_ms=moment.start_ms, autoplay=True)
            self.player.set_markers(
                recording.duration_ms,
                [(moment.start_ms, moment.end_ms)],
                (moment.start_ms, moment.end_ms),
            )

    def _create(self) -> None:
        if self.moment:
            self.create_clip_requested.emit(self.moment)

