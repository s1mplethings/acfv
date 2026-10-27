from __future__ import annotations

import threading

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from acfv.library import LibraryService, VodDownloadService, ensure_twitch_monitor_target
from acfv.feedback import FeedbackService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex

from .base import TabHandle


class LibraryTab(QWidget):
    vod_downloaded = pyqtSignal(str)
    vod_download_failed = pyqtSignal(str)

    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.service = LibraryService()
        self._recording_ids: list[str] = []
        self.vod_downloaded.connect(self._vod_download_finished)
        self.vod_download_failed.connect(self._vod_download_error)
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.creator_filter = QComboBox()
        self.creator_filter.currentIndexChanged.connect(self.refresh_recordings)
        actions.addWidget(self.creator_filter)
        for label, slot in (
            ("添加 Twitch Creator", self.add_creator),
            ("Download VOD", self.download_vod),
            ("刷新", self.refresh),
            ("Recording 详情", self.open_recording),
            ("处理 / 重试", self.retry_processing),
            ("重建索引", self.reindex),
            ("Creator Preference", self.add_preference),
            ("Analysis Profile", self.set_analysis_profile),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["标题", "下载", "录制", "处理", "索引", "来源", "时长", "日期", "路径"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.open_recording)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        selected = self.creator_filter.currentData()
        self.creator_filter.blockSignals(True)
        self.creator_filter.clear()
        self.creator_filter.addItem("全部 Creator", None)
        for creator in self.service.list_creators():
            self.creator_filter.addItem(creator.display_name, creator.id)
        index = self.creator_filter.findData(selected)
        self.creator_filter.setCurrentIndex(max(0, index))
        self.creator_filter.blockSignals(False)
        self.refresh_recordings()

    def refresh_recordings(self) -> None:
        recordings = self.service.list_recordings(self.creator_filter.currentData())
        downloads = {item.recording_id: item for item in VodDownloadService(self.service).list()}
        self._recording_ids = [item.id for item in recordings]
        self.table.setRowCount(len(recordings))
        for row, recording in enumerate(recordings):
            source = self.service.repository.get_source(recording.source_id) if recording.source_id else None
            values = (
                recording.title,
                downloads[recording.id].status.value if recording.id in downloads else "-",
                recording.recording_status.value,
                recording.processing_status.value,
                recording.index_status.value,
                source.channel_name if source else recording.source_type,
                self._duration(recording.duration_ms),
                recording.started_at.isoformat() if recording.started_at else "",
                recording.local_path or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def download_vod(self) -> None:
        source, accepted = QInputDialog.getText(self, "Download VOD", "Twitch VOD URL or ID:")
        if not accepted or not source.strip():
            return
        range_text, accepted = QInputDialog.getText(
            self, "Download VOD range", "Optional start,end seconds (blank downloads the full VOD):"
        )
        if not accepted:
            return
        try:
            start_ms, end_ms = self._parse_range(range_text)
        except ValueError as exc:
            QMessageBox.warning(self, "Download VOD", str(exc))
            return
        threading.Thread(
            target=self._download_vod_worker,
            args=(source.strip(), start_ms, end_ms),
            daemon=True,
        ).start()

    def _download_vod_worker(self, source: str, start_ms: int | None, end_ms: int | None) -> None:
        try:
            service = VodDownloadService(self.service)
            job = service.discover(source, start_ms=start_ms, end_ms=end_ms)
            job = service.download(job.id, config_manager=self.config_manager)
            self.vod_downloaded.emit(job.id)
        except Exception as exc:
            self.vod_download_failed.emit(str(exc))

    def _vod_download_finished(self, download_id: str) -> None:
        self.refresh()
        QMessageBox.information(self, "Download VOD", f"下载完成并已进入正式处理链。\nDownload ID: {download_id}")

    def _vod_download_error(self, message: str) -> None:
        self.refresh()
        QMessageBox.critical(self, "Download VOD 失败", message)

    @staticmethod
    def _parse_range(value: str) -> tuple[int | None, int | None]:
        text = value.strip()
        if not text:
            return None, None
        parts = [item.strip() for item in text.split(",")]
        if len(parts) != 2:
            raise ValueError("范围格式必须是 start,end 秒，例如 300,900。")
        start = float(parts[0]) if parts[0] else 0.0
        end = float(parts[1]) if parts[1] else None
        if start < 0 or end is None or end <= start:
            raise ValueError("end 必须大于等于零的 start。")
        return int(start * 1000), int(end * 1000)

    def add_creator(self) -> None:
        channel, accepted = QInputDialog.getText(self, "添加 Twitch Creator", "Twitch channel:")
        if not accepted or not channel.strip():
            return
        display_name, accepted = QInputDialog.getText(self, "Creator 名称", "Display name:", text=channel.strip())
        if not accepted:
            return
        self._run_action(lambda: self._create_twitch_creator(display_name, channel))

    def _create_twitch_creator(self, display_name: str, channel: str) -> None:
        creator = self.service.create_creator(display_name or channel)
        normalized = channel.strip().lstrip("@").lower()
        source = self.service.add_source(
            creator.id,
            platform="twitch",
            external_id=normalized,
            channel_name=channel.strip(),
            channel_url=f"https://twitch.tv/{normalized}",
        )
        ensure_twitch_monitor_target(source)

    def open_recording(self, *_args) -> None:
        recording = self._selected_recording()
        if recording is None:
            return
        moments = self.service.repository.list_moments(recording_id=recording.id)
        QMessageBox.information(
            self,
            "Recording 详情",
            f"{recording.title}\n\n路径: {recording.local_path or '-'}\n"
            f"录制: {recording.recording_status.value}\n处理: {recording.processing_status.value}\n"
            f"索引: {recording.index_status.value}\nMoments: {len(moments)}\n"
            f"Artifacts: {recording.artifact_root or '-'}",
        )

    def retry_processing(self) -> None:
        recording = self._selected_recording()
        if recording:
            self._run_action(lambda: self.service.retry_processing(recording.id, config_manager=self.config_manager))

    def reindex(self) -> None:
        self._run_action(lambda: HybridRetrievalService(self.service.repository, PersistentMomentIndex(self.service.repository)).rebuild())

    def add_preference(self) -> None:
        creator_id = self.creator_filter.currentData()
        if not creator_id:
            QMessageBox.information(self, "Creator Preference", "请先选择一个 Creator。")
            return
        text, accepted = QInputDialog.getText(self, "Creator Preference", "明确偏好:")
        if accepted and text.strip():
            self._run_action(lambda: FeedbackService(self.service.repository).add_preference(text.strip(), creator_id=creator_id))

    def set_analysis_profile(self) -> None:
        profile, accepted = QInputDialog.getItem(
            self,
            "Analysis Profile",
            "Profile:",
            ["Auto", "Gaming", "Talking", "Collab", "Other", "Custom"],
            0,
            False,
        )
        if not accepted:
            return
        recording = self._selected_recording(silent=True)
        if recording is not None:
            self._run_action(lambda: self.service.set_analysis_profile(recording.id, profile))
            return
        creator_id = self.creator_filter.currentData()
        if creator_id:
            self._run_action(lambda: self.service.set_creator_analysis_profile(creator_id, profile))
            return
        QMessageBox.information(self, "Analysis Profile", "请选择一个 Recording 或 Creator。")

    def _selected_recording(self, *, silent: bool = False):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._recording_ids):
            if not silent:
                QMessageBox.information(self, "Creator Library", "请先选择一条 Recording。")
            return None
        return self.service.get_recording(self._recording_ids[row])

    def _run_action(self, action) -> None:
        try:
            action()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Creator Library 操作失败", str(exc))

    @staticmethod
    def _duration(duration_ms: int | None) -> str:
        if duration_ms is None:
            return "-"
        seconds = duration_ms // 1000
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def create_library_tab(parent, config_manager) -> TabHandle:
    widget = LibraryTab(config_manager, parent)
    return TabHandle(title="Library", widget=widget, controller=widget)
