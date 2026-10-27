from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from acfv.conversation import GroundedConversationService
from acfv.clips import ClipService
from acfv.library import LibraryService
from acfv.llm import get_default_client
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope

from .base import TabHandle


class _SearchWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, query, scope_data, config_manager):
        super().__init__()
        self.query = query
        self.scope_data = scope_data
        self.config_manager = config_manager

    def run(self):
        try:
            library = LibraryService()
            index = PersistentMomentIndex(library.repository)
            retrieval = HybridRetrievalService(library.repository, index)
            try:
                needs_rebuild = not index.manifest_path.is_file()
                if not needs_rebuild:
                    index.rows()
            except RuntimeError:
                needs_rebuild = True
            if needs_rebuild:
                retrieval.rebuild()
            conversation = GroundedConversationService(
                retrieval, llm_client=get_default_client(config_manager=self.config_manager)
            )
            kind, identity = self.scope_data
            scope = SearchScope(kind)
            answer = conversation.ask(
                    self.query,
                    scope=scope,
                    creator_id=identity if scope == SearchScope.CREATOR else None,
                    recording_id=identity if scope in {SearchScope.RECORDING, SearchScope.LIVE_SESSION} else None,
                )
            self.completed.emit({"answer": answer, "runtime": retrieval.runtime_metadata()})
        except Exception as exc:
            self.failed.emit(str(exc))


class _ClipWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, moment_id: str, query: str):
        super().__init__()
        self.moment_id = moment_id
        self.query = query

    def run(self):
        try:
            library = LibraryService()
            service = ClipService(library.repository)
            proposal = service.create_proposal(self.moment_id, query=self.query)
            self.completed.emit(service.render(proposal.id))
        except Exception as exc:
            self.failed.emit(str(exc))


class ConversationTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.library = LibraryService()
        self.results = []
        self.worker = None
        self.clip_worker = None
        layout = QVBoxLayout(self)
        query_row = QHBoxLayout()
        self.scope = QComboBox()
        self.query = QLineEdit()
        self.query.setPlaceholderText("询问 Creator Library 中发生过什么…")
        self.search_button = QPushButton("搜索")
        self.search_button.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        query_row.addWidget(self.scope)
        query_row.addWidget(self.query, 1)
        query_row.addWidget(self.search_button)
        layout.addLayout(query_row)
        self.answer = QLabel("输入问题后，将返回简短回答和真实视频证据。")
        self.answer.setWordWrap(True)
        layout.addWidget(self.answer)
        self.runtime_status = QLabel("Embedding: checking · Reranker: checking · Conversation: checking")
        layout.addWidget(self.runtime_status)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Recording", "状态", "日期", "时间", "摘要", "字幕", "Preview", "Create Clip"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh_creators()

    def refresh_creators(self):
        self.scope.clear()
        self.scope.addItem("整个 Library", (SearchScope.ENTIRE_LIBRARY.value, None))
        for creator in self.library.list_creators():
            self.scope.addItem(f"Creator · {creator.display_name}", (SearchScope.CREATOR.value, creator.id))
        for recording in self.library.list_recordings()[:10]:
            if recording.recording_status.value == "RECORDING":
                self.scope.addItem(f"LIVE · {recording.title}", (SearchScope.LIVE_SESSION.value, recording.id))
            else:
                self.scope.addItem(f"Recording · {recording.title}", (SearchScope.RECORDING.value, recording.id))

    def search(self):
        query = self.query.text().strip()
        if not query or (self.worker and self.worker.isRunning()):
            return
        self.search_button.setEnabled(False)
        self.answer.setText("正在检索证据…")
        self.worker = _SearchWorker(query, self.scope.currentData(), self.config_manager)
        self.worker.completed.connect(self._show_answer)
        self.worker.failed.connect(self._show_error)
        self.worker.finished.connect(lambda: self.search_button.setEnabled(True))
        self.worker.start()

    def _show_answer(self, payload):
        answer = payload["answer"]
        runtime = payload["runtime"]
        self.runtime_status.setText(
            f"Embedding: {runtime.get('retrieval_mode', 'UNKNOWN')} · "
            f"Reranker: {'READY' if runtime.get('reranker_enabled') else 'UNAVAILABLE'} · "
            f"Conversation: {answer.runtime_mode.value}"
        )
        self.answer.setText(f"[{answer.runtime_mode.value}] {answer.answer}")
        self.results = answer.evidence_cards
        self.table.setRowCount(len(self.results))
        for row, result in enumerate(self.results):
            values = (
                result.recording_title,
                result.moment_status,
                result.recorded_at or "",
                f"{result.start_ms / 1000:.1f}s – {result.end_ms / 1000:.1f}s",
                result.summary,
                result.transcript_excerpt,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            preview = QPushButton("Preview")
            preview.clicked.connect(lambda _checked=False, item=result: self.preview(item))
            self.table.setCellWidget(row, 6, preview)
            create = QPushButton("Create Clip")
            create.clicked.connect(lambda _checked=False, item=result: self.create_clip(item))
            self.table.setCellWidget(row, 7, create)
        self.table.resizeColumnsToContents()

    def _show_error(self, message):
        self.answer.setText("检索失败。")
        QMessageBox.critical(self, "Conversation 检索失败", message)

    def preview(self, result):
        recording = self.library.get_recording(result.recording_id)
        if recording is None or not recording.local_path or not Path(recording.local_path).is_file():
            QMessageBox.warning(self, "Preview", "原始 Recording 文件当前不可用。")
            return
        try:
            dialog = EvidencePreviewDialog(recording.local_path, result.start_ms, self)
            dialog.exec_()
        except Exception:
            os.startfile(recording.local_path)

    def create_clip(self, result):
        if self.clip_worker and self.clip_worker.isRunning():
            return
        self.clip_worker = _ClipWorker(result.moment_id, self.query.text().strip())
        self.clip_worker.completed.connect(
            lambda clip: QMessageBox.information(self, "Create Clip", f"切片已生成：\n{clip.output_path}")
        )
        self.clip_worker.failed.connect(
            lambda message: QMessageBox.critical(self, "Create Clip 失败", message)
        )
        self.clip_worker.start()


class EvidencePreviewDialog(QDialog):
    def __init__(self, path: str, start_ms: int, parent=None):
        super().__init__(parent)
        from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
        from PyQt5.QtMultimediaWidgets import QVideoWidget

        self.setWindowTitle(f"Evidence Preview — {start_ms / 1000:.1f}s")
        self.resize(800, 500)
        layout = QVBoxLayout(self)
        video = QVideoWidget()
        layout.addWidget(video)
        self.player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(video)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(Path(path).resolve()))))
        self.player.play()
        QTimer.singleShot(250, lambda: self.player.setPosition(start_ms))

    def closeEvent(self, event):
        self.player.stop()
        super().closeEvent(event)


def create_conversation_tab(parent, config_manager) -> TabHandle:
    widget = ConversationTab(config_manager, parent)
    return TabHandle(title="Conversation", widget=widget, controller=widget)
