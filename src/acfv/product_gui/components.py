"""Small reusable product widgets."""

from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .models import MomentModel, OBJECT_ROLE
from .viewmodels import MomentVM, duration_text


def label(text: str, *, role: str | None = None, muted: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if muted:
        widget.setProperty("muted", True)
    return widget


def button(text: str, callback: Callable | None = None, *, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if primary:
        widget.setProperty("primary", True)
    if callback:
        widget.clicked.connect(callback)
    return widget


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(4)
        self.title = label(title, role="pageTitle")
        self.subtitle = label(subtitle, muted=True)
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)


class EmptyState(QFrame):
    action = pyqtSignal()

    def __init__(self, title: str, detail: str, action_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setAlignment(Qt.AlignCenter)
        icon = label("◌")
        icon.setStyleSheet("font-size: 32px; color: #7c5cff")
        layout.addWidget(icon, 0, Qt.AlignHCenter)
        self.title = label(title, role="sectionTitle")
        layout.addWidget(self.title, 0, Qt.AlignHCenter)
        self.message = label(detail, muted=True)
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message)
        self.button = button(action_text, self.action.emit, primary=True)
        self.button.setVisible(bool(action_text))
        layout.addWidget(self.button, 0, Qt.AlignHCenter)


class LoadingState(EmptyState):
    def __init__(self, text: str = "正在加载…", parent=None) -> None:
        super().__init__(text, "请稍候，ACFV 正在读取本地数据。", parent=parent)


class ErrorState(QFrame):
    retry = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("error", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.title = label("操作失败", role="sectionTitle")
        self.message = label("", muted=True)
        self.message.setWordWrap(True)
        self.details = label("", muted=True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details.setWordWrap(True)
        self.details.setVisible(False)
        actions = QHBoxLayout()
        actions.addWidget(button("重试", self.retry.emit, primary=True))
        show = button("显示详情")
        show.clicked.connect(lambda: self.details.setVisible(not self.details.isVisible()))
        actions.addWidget(show)
        actions.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.message)
        layout.addWidget(self.details)
        layout.addLayout(actions)

    def set_error(self, message: str, details: str = "") -> None:
        self.message.setText(message or "发生了未知错误。")
        self.details.setText(details)


class StateStack(QStackedWidget):
    """Consistent loading/error/empty/content state container."""

    def __init__(self, content: QWidget, empty: EmptyState, parent=None) -> None:
        super().__init__(parent)
        self.loading = LoadingState()
        self.error = ErrorState()
        self.empty = empty
        self.content = content
        for widget in (self.loading, self.error, self.empty, self.content):
            self.addWidget(widget)
        self.show_loading()

    def show_loading(self, text: str = "正在加载…") -> None:
        self.loading.title.setText(text)
        self.setCurrentWidget(self.loading)

    def show_error(self, message: str, details: str = "") -> None:
        self.error.set_error(message, details)
        self.setCurrentWidget(self.error)

    def show_empty(self) -> None:
        self.setCurrentWidget(self.empty)

    def show_content(self) -> None:
        self.setCurrentWidget(self.content)


class StatusBadge(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "badge")
        self.set_state(text)

    def set_state(self, state: str) -> None:
        self.setText(state)
        normalized = state.casefold()
        semantic = "failed" if any(word in normalized for word in ("失败", "error", "failed")) else (
            "warning" if any(word in normalized for word in ("警告", "检查", "warning", "review")) else "ready"
        )
        self.setProperty("state", semantic)
        self.style().unpolish(self)
        self.style().polish(self)


class MomentList(QWidget):
    play_requested = pyqtSignal(object)
    open_requested = pyqtSignal(object)
    clip_requested = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.model = MomentModel()
        self.view = QListView()
        self.view.setObjectName("MomentList")
        self.view.setModel(self.model)
        self.view.setUniformItemSizes(True)
        self.view.setSpacing(6)
        self.view.setWordWrap(True)
        self.view.doubleClicked.connect(self._open)
        actions = QHBoxLayout()
        actions.addWidget(button("播放", self._play))
        actions.addWidget(button("打开事件", self._open))
        actions.addWidget(button("创建 Clip", self._clip, primary=True))
        actions.addStretch(1)
        layout.addWidget(self.view, 1)
        layout.addLayout(actions)

    def selected(self) -> MomentVM | None:
        index = self.view.currentIndex()
        return index.data(OBJECT_ROLE) if index.isValid() else None

    def _play(self, *_args) -> None:
        if self.selected():
            self.play_requested.emit(self.selected())

    def _open(self, *_args) -> None:
        if self.selected():
            self.open_requested.emit(self.selected())

    def _clip(self, *_args) -> None:
        if self.selected():
            self.clip_requested.emit(self.selected())


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(label(title, muted=True))
        self.value = label(value, role="sectionTitle")
        layout.addWidget(self.value)

