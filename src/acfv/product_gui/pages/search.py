from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QMessageBox, QShortcut, QVBoxLayout, QWidget

from acfv.retrieval import SearchScope

from ..components import EmptyState, MomentList, PageHeader, StateStack, button
from ..controllers import ProductContext, SearchController


class SearchPage(QWidget):
    def __init__(self, controller: SearchController, context: ProductContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller; self.context = context
        self._limit = 20
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 20, 24, 16)
        layout.addWidget(PageHeader("搜索 Moment", "用自然语言搜索整个 Library、当前 Creator 或当前 Recording。"))
        row = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItem("全部 Library", SearchScope.ENTIRE_LIBRARY.value)
        self.scope.addItem("当前 Creator", SearchScope.CREATOR.value)
        self.scope.addItem("当前 Recording", SearchScope.RECORDING.value)
        self.query = QLineEdit(); self.query.setPlaceholderText("例如：她当时为什么害怕？")
        self.query.returnPressed.connect(self.run_search)
        row.addWidget(self.scope); row.addWidget(self.query, 1); row.addWidget(button("搜索", self.run_search, primary=True))
        layout.addLayout(row)
        self.results = MomentList()
        self.results.play_requested.connect(self._play)
        self.results.open_requested.connect(context.moment_opened)
        self.results.clip_requested.connect(lambda moment: controller.create_clip(moment.id))
        empty = EmptyState("没有找到结果", "尝试更具体的事件描述，或扩大搜索范围。")
        self.state = StateStack(self.results, empty)
        self.state.error.retry.connect(self.run_search)
        layout.addWidget(self.state, 1)
        self.more = button("加载更多", self.load_more)
        self.more.setVisible(False)
        layout.addWidget(self.more, 0, Qt.AlignHCenter)
        controller.results_ready.connect(self._ready)
        controller.clip_created.connect(self._clip_created)
        controller.error.connect(self.state.show_error)
        QShortcut(QKeySequence.Find, self, activated=lambda: self.query.setFocus())

    def run_search(self) -> None:
        query = self.query.text().strip()
        if not query:
            self.query.setFocus(); return
        kind = self.scope.currentData()
        creator_id = getattr(self.context.creator, "id", None)
        recording_id = getattr(self.context.recording, "id", None)
        if kind == SearchScope.CREATOR.value and not creator_id:
            QMessageBox.information(self, "搜索范围", "请先选择 Creator。")
            return
        if kind == SearchScope.RECORDING.value and not recording_id:
            QMessageBox.information(self, "搜索范围", "请先在 Library 打开一个 Recording。")
            return
        self._limit = 20
        self.state.show_loading("正在搜索并排序相关 Moment…")
        self.controller.search(query, scope=kind, creator_id=creator_id, recording_id=recording_id, limit=self._limit)

    def load_more(self) -> None:
        self._limit += 20
        kind = self.scope.currentData()
        self.controller.search(
            self.query.text().strip(), scope=kind,
            creator_id=getattr(self.context.creator, "id", None),
            recording_id=getattr(self.context.recording, "id", None),
            limit=self._limit,
        )

    def _ready(self, rows) -> None:
        self.results.model.replace(rows)
        self.state.show_content() if rows else self.state.show_empty()
        self.more.setVisible(bool(rows) and len(rows) >= self._limit)

    def _play(self, moment) -> None:
        self.context.moment_opened.emit(moment)

    def _clip_created(self, clip) -> None:
        self.context.clip_opened.emit(clip.id)

