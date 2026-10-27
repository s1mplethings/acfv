from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..components import EmptyState, MomentList, PageHeader, StateStack, StatusBadge, button, label
from ..controllers import LibraryController, ProductContext
from ..models import OBJECT_ROLE, RecordingModel
from ..player import MediaPlayer
from ..viewmodels import MomentVM, RecordingVM, duration_text


class AddSourceDialog(QDialog):
    local_import = pyqtSignal(str)
    vod_requested = pyqtSignal(str, object, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加来源")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItem("导入本地视频", "local")
        self.mode.addItem("下载 Twitch VOD", "vod")
        self.mode.addItem("Live 监控", "live")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        layout.addWidget(self.mode)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        local = QWidget(); form = QFormLayout(local)
        row = QHBoxLayout(); self.path = QLineEdit(); browse = button("选择文件", self._browse)
        row.addWidget(self.path, 1); row.addWidget(browse)
        form.addRow("视频文件", row)
        form.addRow(label("导入后会通过 canonical LibraryService 注册并创建后台处理任务。", muted=True))
        self.stack.addWidget(local)
        vod = QWidget(); form = QFormLayout(vod)
        self.url = QLineEdit(); self.url.setPlaceholderText("https://www.twitch.tv/videos/…")
        self.range_start = QLineEdit(); self.range_start.setPlaceholderText("可选，秒")
        self.range_end = QLineEdit(); self.range_end.setPlaceholderText("可选，秒")
        form.addRow("VOD URL", self.url); form.addRow("开始", self.range_start); form.addRow("结束", self.range_end)
        form.addRow(label("没有网络或授权 URL 时会显示明确错误，不会伪装成功。", muted=True))
        self.stack.addWidget(vod)
        live = QWidget(); live_layout = QVBoxLayout(live)
        live_layout.addWidget(label("当前离线", role="sectionTitle"))
        live_layout.addWidget(label("选择 Creator 后可配置正式监控；当前没有 live 时不会显示无限 loading。", muted=True))
        live_layout.addStretch(1)
        self.stack.addWidget(live)
        actions = QHBoxLayout(); actions.addStretch(1)
        actions.addWidget(button("取消", self.reject)); actions.addWidget(button("继续", self._accept, primary=True))
        layout.addLayout(actions)

    def _mode_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", "Video (*.mp4 *.mkv *.mov *.webm *.avi)")
        if path:
            self.path.setText(path)

    def _accept(self) -> None:
        mode = self.mode.currentData()
        if mode == "local":
            if not Path(self.path.text()).is_file():
                QMessageBox.warning(self, "导入本地视频", "请选择存在的视频文件。")
                return
            self.local_import.emit(self.path.text())
        elif mode == "vod":
            if not self.url.text().strip():
                QMessageBox.warning(self, "下载 VOD", "请输入 Twitch VOD URL。")
                return
            start = int(float(self.range_start.text()) * 1000) if self.range_start.text().strip() else None
            end = int(float(self.range_end.text()) * 1000) if self.range_end.text().strip() else None
            self.vod_requested.emit(self.url.text().strip(), start, end)
        self.accept()


class RecordingWorkspace(QWidget):
    back_requested = pyqtSignal()
    moment_opened = pyqtSignal(object)
    clip_requested = pyqtSignal(object)
    process_requested = pyqtSignal(str)
    relink_requested = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.recording: RecordingVM | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(button("← 返回 Library", self.back_requested.emit))
        self.title = label("Recording", role="pageTitle")
        top.addWidget(self.title); top.addStretch(1)
        self.status = StatusBadge()
        top.addWidget(self.status)
        self.process_button = button("处理 / 重试", self._process)
        top.addWidget(self.process_button)
        self.relink_button = button("重新关联媒体", self._relink)
        self.relink_button.setVisible(False)
        top.addWidget(self.relink_button)
        layout.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0, 0, 8, 0)
        self.player = MediaPlayer()
        left_layout.addWidget(self.player, 1)
        self.info = label("", muted=True); self.info.setWordWrap(True)
        left_layout.addWidget(self.info)
        split.addWidget(left)
        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(label("Moments", role="sectionTitle"))
        self.moments = MomentList()
        self.moments.play_requested.connect(self.play_moment)
        self.moments.open_requested.connect(self.moment_opened)
        self.moments.clip_requested.connect(self.clip_requested)
        right_layout.addWidget(self.moments, 1)
        split.addWidget(right)
        split.setSizes([760, 430])
        layout.addWidget(split, 1)

    def load(self, recording: RecordingVM, moments: list[MomentVM]) -> None:
        self.recording = recording
        self.title.setText(recording.title)
        self.status.set_state("媒体缺失" if recording.missing_media else recording.status)
        self.info.setText(
            f"{recording.date} · {duration_text(recording.duration_ms)} · {recording.source_type} · {recording.language}"
        )
        self.moments.model.replace(moments)
        self.player.load(recording.media_path)
        self.process_button.setEnabled(recording.status != "处理中")
        self.relink_button.setVisible(recording.missing_media)
        self.player.set_markers(
            recording.duration_ms,
            [(moment.start_ms, moment.end_ms) for moment in moments],
        )

    def play_moment(self, moment: MomentVM) -> None:
        if self.recording and self.player.media_path != self.recording.media_path:
            self.player.load(self.recording.media_path, position_ms=moment.start_ms, autoplay=True)
        else:
            self.player.seek_to(moment.start_ms)
            self.player.player.play()

    def _process(self) -> None:
        if self.recording:
            self.process_requested.emit(self.recording.id)

    def _relink(self) -> None:
        if not self.recording:
            return
        path, _ = QFileDialog.getOpenFileName(self, "重新关联媒体", "", "Video (*.mp4 *.mkv *.mov *.webm *.avi)")
        if path:
            self.relink_requested.emit(self.recording.id, path)


class LibraryPage(QWidget):
    add_source_requested = pyqtSignal()
    vod_requested = pyqtSignal(str, object, object)
    clip_requested = pyqtSignal(object)

    def __init__(self, controller: LibraryController, context: ProductContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.context = context
        self._creator = None
        self._recording_to_open: RecordingVM | None = None
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 20, 24, 16)
        head_row = QHBoxLayout()
        self.header = PageHeader("Creator Library", "选择 Creator，浏览真实 Recording，然后进入播放与 Moment 工作区。")
        head_row.addWidget(self.header, 1)
        head_row.addWidget(button("+ 添加来源", self.open_add_source, primary=True))
        layout.addLayout(head_row)
        self.pages = QStackedWidget(); layout.addWidget(self.pages, 1)
        home = QWidget(); home_layout = QVBoxLayout(home); home_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_box = QGroupBox("Creator Profile")
        self.profile_box.setCheckable(True); self.profile_box.setChecked(False)
        profile_layout = QVBoxLayout(self.profile_box)
        self.profile_status = QLabel("Visual · Not built    Voice · Not built    Trusted Speech · 0m    Lexicon · 0")
        self.profile_status.setWordWrap(True); profile_layout.addWidget(self.profile_status)
        self.profile_build = QPushButton("Build / Update Profile")
        self.profile_build.clicked.connect(self._build_profile); profile_layout.addWidget(self.profile_build, 0, Qt.AlignLeft)
        home_layout.addWidget(self.profile_box)
        self.recording_model = RecordingModel()
        self.recordings = QListView()
        self.recordings.setObjectName("RecordingGrid")
        self.recordings.setModel(self.recording_model)
        self.recordings.setViewMode(QListView.IconMode)
        self.recordings.setResizeMode(QListView.Adjust)
        self.recordings.setMovement(QListView.Static)
        self.recordings.setGridSize(QSize(300, 168))
        self.recordings.setIconSize(QSize(264, 82))
        self.recordings.setUniformItemSizes(True)
        self.recordings.setWordWrap(True)
        self.recordings.doubleClicked.connect(self._open_recording)
        empty = EmptyState("还没有 Recording", "添加本地视频、VOD 或 Live 来源后，内容会出现在这里。", "+ 添加来源")
        empty.action.connect(self.open_add_source)
        self.state = StateStack(self.recordings, empty)
        self.state.error.retry.connect(self.refresh)
        home_layout.addWidget(self.state)
        self.pages.addWidget(home)
        self.workspace = RecordingWorkspace()
        self.workspace.back_requested.connect(lambda: self.pages.setCurrentIndex(0))
        self.workspace.moment_opened.connect(self.context.moment_opened)
        self.workspace.clip_requested.connect(self.clip_requested)
        self.workspace.process_requested.connect(controller.process)
        self.workspace.relink_requested.connect(controller.relink)
        self.pages.addWidget(self.workspace)
        context.creator_changed.connect(self._creator_changed)
        controller.recordings_ready.connect(self._recordings_ready)
        controller.moments_ready.connect(self._moments_ready)
        controller.imported.connect(self._imported)
        controller.thumbnail_ready.connect(self.recording_model.set_thumbnail)
        controller.profile_ready.connect(self._profile_ready)
        controller.processing_started.connect(lambda _row: self.refresh())
        controller.error.connect(self._error)

    def refresh(self) -> None:
        self.state.show_loading("正在读取 Recording…")
        self.controller.load_recordings(getattr(self._creator, "id", None))

    def _creator_changed(self, creator) -> None:
        self._creator = creator
        self.pages.setCurrentIndex(0)
        self.header.subtitle.setText(
            f"当前范围：{creator.name}" if creator else "选择 Creator，浏览真实 Recording，然后进入播放与 Moment 工作区。"
        )
        if creator:
            minutes = int(getattr(creator, "trusted_speech_duration_ms", 0)) // 60000
            self.profile_status.setText(
                f"Status · {getattr(creator, 'profile_status', 'NOT_BUILT')}    "
                f"Visual · {getattr(creator, 'visual_status', 'NOT_BUILT')}    "
                f"Voice · {getattr(creator, 'voice_exemplars', 0)} exemplars    "
                f"Trusted Speech · {minutes}m    Lexicon · {getattr(creator, 'lexicon_entries', 0)}    "
                f"Adaptive ASR · {getattr(creator, 'adaptive_status', 'SHADOW')}"
            )
        else:
            self.profile_status.setText("Select a Creator to inspect its adaptive profile.")
        self.refresh()

    def _recordings_ready(self, rows: list[RecordingVM]) -> None:
        self.recording_model.replace(rows)
        self.state.show_content() if rows else self.state.show_empty()
        for recording in rows:
            if not recording.missing_media:
                self.controller.load_thumbnail(recording)

    def _build_profile(self) -> None:
        if not self._creator:
            return
        self.profile_status.setText("Scanning → Visual Identity → Voice Bootstrap → Trusted Speech → Lexicon")
        self.profile_build.setEnabled(False)
        self.controller.build_profile(self._creator.id)

    def _profile_ready(self, summary: dict) -> None:
        self.profile_build.setEnabled(True)
        minutes = int(summary.get("trusted_speech_duration_ms", 0)) // 60000
        self.profile_status.setText(
            f"Status · {summary.get('status', 'NEEDS_REVIEW')}    Visual · {summary.get('visual_status', 'NOT_BUILT')}    "
            f"Voice · {summary.get('voice_exemplars', 0)} exemplars    Trusted Speech · {minutes}m    "
            f"Lexicon · {summary.get('lexicon_entries', 0)}    Adaptive ASR · {summary.get('adaptive_status', 'SHADOW')}"
        )

    def _open_recording(self, index) -> None:
        recording = index.data(OBJECT_ROLE)
        if not recording:
            return
        self._recording_to_open = recording
        self.context.select_recording(recording)
        self.workspace.title.setText(recording.title)
        self.workspace.status.set_state("加载中")
        self.pages.setCurrentIndex(1)
        self.controller.load_moments(recording.id)

    def _moments_ready(self, rows: list[MomentVM]) -> None:
        if self._recording_to_open:
            self.workspace.load(self._recording_to_open, rows)

    def open_add_source(self) -> None:
        if not self._creator:
            QMessageBox.information(self, "添加来源", "请先选择一个 Creator。")
            return
        dialog = AddSourceDialog(self)
        dialog.local_import.connect(lambda path: self.controller.import_local(path, self._creator.id))
        dialog.vod_requested.connect(self.vod_requested)
        dialog.exec_()

    def _imported(self, recording: RecordingVM) -> None:
        self.refresh()
        self._recording_to_open = recording

    def _error(self, message: str, details: str) -> None:
        if self.pages.currentIndex() == 0:
            self.state.show_error(message, details)
        else:
            QMessageBox.critical(self, "操作失败", message)

