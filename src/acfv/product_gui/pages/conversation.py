from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QShortcut, QVBoxLayout, QWidget

from acfv.retrieval import SearchScope

from ..components import EmptyState, MomentList, PageHeader, StateStack, button, label
from ..controllers import ConversationController, ProductContext


class ConversationPage(QWidget):
    def __init__(self, controller: ConversationController, context: ProductContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller; self.context = context; self._last_query = ""
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 20, 24, 16)
        layout.addWidget(PageHeader("基于视频证据提问", "回答与可播放证据并列呈现；没有足够证据时会明确说明。"))
        row = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem("全部 Library", SearchScope.ENTIRE_LIBRARY.value)
        self.scope.addItem("当前 Creator", SearchScope.CREATOR.value)
        self.scope.addItem("当前 Recording", SearchScope.RECORDING.value)
        self.query = QPlainTextEdit(); self.query.setPlaceholderText("你想从视频里确认什么？")
        self.query.setMaximumHeight(82)
        send = button("提问", self.ask, primary=True)
        row.addWidget(self.scope); row.addWidget(self.query, 1); row.addWidget(send)
        layout.addLayout(row)
        content = QWidget(); content_layout = QVBoxLayout(content); content_layout.setContentsMargins(0, 0, 0, 0)
        self.mode = label("", muted=True)
        self.answer = label("", role="sectionTitle"); self.answer.setWordWrap(True); self.answer.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_layout.addWidget(self.mode); content_layout.addWidget(self.answer)
        content_layout.addWidget(label("Evidence", role="sectionTitle"))
        self.evidence = MomentList()
        self.evidence.play_requested.connect(context.moment_opened)
        self.evidence.open_requested.connect(context.moment_opened)
        self.evidence.clip_requested.connect(lambda moment: controller.create_clip(moment.id, self._last_query))
        content_layout.addWidget(self.evidence, 1)
        empty = EmptyState("等待问题", "输入问题后，ACFV 会检索真实视频证据。")
        self.state = StateStack(content, empty); self.state.show_empty()
        layout.addWidget(self.state, 1)
        controller.answer_ready.connect(self._ready)
        controller.clip_created.connect(lambda clip: context.clip_opened.emit(clip.id))
        controller.error.connect(self.state.show_error)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.ask)

    def ask(self) -> None:
        query = self.query.toPlainText().strip()
        if not query:
            self.query.setFocus(); return
        self._last_query = query
        kind = self.scope.currentData()
        creator_id = getattr(self.context.creator, "id", None)
        recording_id = getattr(self.context.recording, "id", None)
        if kind == SearchScope.CREATOR.value and not creator_id:
            self.state.show_error("请先选择 Creator。", "当前问题要求 Creator scope。")
            return
        if kind == SearchScope.RECORDING.value and not recording_id:
            self.state.show_error("请先打开 Recording。", "当前问题要求 Recording scope。")
            return
        self.state.show_loading("正在检索证据并组织回答…")
        self.controller.ask(query, scope=kind, creator_id=creator_id, recording_id=recording_id)

    def _ready(self, payload) -> None:
        self.answer.setText(payload["answer"])
        mode = payload["runtime_mode"]
        self.mode.setText("基于证据的回答" if payload["grounded"] else f"{mode} · 未生成无依据结论")
        self.evidence.model.replace(payload["evidence"])
        self.state.show_content()

