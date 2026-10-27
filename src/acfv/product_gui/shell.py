"""Slim application shell: navigation, Creator context, pages, and activity."""

from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .backend import ProductBackend
from .components import button, label
from .controllers import (
    ActivityController,
    ConversationController,
    LibraryController,
    ProductContext,
    ReviewController,
    SearchController,
    JobsController,
)
from .models import CreatorModel, JobModel, OBJECT_ROLE
from .pages import ConversationPage, EventPage, LibraryPage, ReviewPage, SearchPage
from .theme import stylesheet
from .workers import GuiExecutor


LOGGER = logging.getLogger(__name__)
PAGE_NAMES = ("library", "search", "conversation", "review")


class ActivityBar(QFrame):
    def __init__(self, activity: ActivityController, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self); layout.setContentsMargins(12, 6, 12, 8); layout.setSpacing(4)
        header = QHBoxLayout()
        self.toggle = QPushButton("活动 · 暂无任务")
        self.toggle.setProperty("nav", True)
        self.toggle.clicked.connect(self._toggle)
        header.addWidget(self.toggle, 1)
        header.addWidget(label("后台任务始终可见；失败不会静默消失。", muted=True))
        layout.addLayout(header)
        self.model = JobModel()
        self.view = QListView(); self.view.setModel(self.model); self.view.setMaximumHeight(170); self.view.setVisible(False)
        layout.addWidget(self.view)
        actions = QHBoxLayout()
        self.cancel = button("安全取消", self._cancel_selected)
        self.cancel.setEnabled(False)
        self.cancel.setToolTip("仅 backend 明确支持安全取消的任务可用")
        actions.addWidget(self.cancel); actions.addStretch(1); layout.addLayout(actions)
        self.view.selectionModel().currentChanged.connect(self._selection_changed)
        activity.changed.connect(self.update_jobs)
        self._timer = QTimer(self); self._timer.setInterval(1000); self._timer.timeout.connect(lambda: self.update_jobs(activity.jobs)); self._timer.start()

    def _toggle(self) -> None:
        self.view.setVisible(not self.view.isVisible())

    def update_jobs(self, jobs) -> None:
        self.model.replace(jobs)
        active = sum(job.state not in {"已完成", "失败"} for job in jobs)
        failures = sum(job.state == "失败" for job in jobs)
        summary = f"活动 · {active} 个进行中" if active else "活动 · 暂无进行中的任务"
        if failures:
            summary += f" · {failures} 个失败"
        self.toggle.setText(summary)

    def _selection_changed(self, current, _previous) -> None:
        job = current.data(OBJECT_ROLE) if current.isValid() else None
        self.cancel.setEnabled(bool(job and job.cancellable))

    def _cancel_selected(self) -> None:
        index = self.view.currentIndex(); job = index.data(OBJECT_ROLE) if index.isValid() else None
        if job and job.cancellable:
            self.activity.cancel_requested.emit(job.id)


class ProductMainWindow(QMainWindow):
    """Own only shell-level state; page controllers own all workflows."""

    def __init__(self, config_manager=None, *, backend: ProductBackend | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ProductMainWindow")
        self.setWindowTitle("ACFV · Creator Video Workspace")
        self.setMinimumSize(1120, 680)
        self.resize(1440, 900)
        self.setStyleSheet(stylesheet())
        self.settings = QSettings("ACFV", "ProductGUI")
        self.backend = backend or ProductBackend.from_environment(config_manager=config_manager)
        self.executor = GuiExecutor(max_workers=4, parent=self)
        self.activity = ActivityController(self)
        self.context = ProductContext(self)
        self.library_controller = LibraryController(self.backend, self.executor, self.activity, self)
        self.search_controller = SearchController(self.backend, self.executor, self.activity, self)
        self.conversation_controller = ConversationController(self.backend, self.executor, self.activity, self)
        self.review_controller = ReviewController(self.backend, self.executor, self.activity, self)
        self.jobs_controller = JobsController(self.backend, self.executor, self.activity, self)
        self._event_moment = None
        self._nav_history: list[str] = []
        self._build_ui()
        self._connect()
        self._restore_shell_state()
        self.library_controller.load_creators()
        self.review_page.refresh(None)
        self.job_timer = QTimer(self); self.job_timer.setInterval(1500); self.job_timer.timeout.connect(self.jobs_controller.poll); self.job_timer.start()

    def _build_ui(self) -> None:
        central = QWidget(); outer = QVBoxLayout(central); outer.setContentsMargins(10, 10, 10, 10); outer.setSpacing(8)
        self.setCentralWidget(central)
        self.main_splitter = QSplitter(Qt.Horizontal)
        sidebar = QFrame(); sidebar.setProperty("card", True); sidebar.setMinimumWidth(205); sidebar.setMaximumWidth(285)
        side = QVBoxLayout(sidebar); side.setContentsMargins(12, 14, 12, 12); side.setSpacing(8)
        brand = label("ACFV", role="pageTitle"); side.addWidget(brand)
        side.addWidget(label("Creator Library", muted=True))
        self.creator_model = CreatorModel()
        self.creators = QListView(); self.creators.setModel(self.creator_model); self.creators.setUniformItemSizes(True); self.creators.setWordWrap(True)
        self.creators.clicked.connect(self._creator_selected)
        side.addWidget(self.creators, 1)
        side.addWidget(button("+ 添加来源", self._add_source))
        separator = QFrame(); separator.setFrameShape(QFrame.HLine); side.addWidget(separator)
        self.nav_buttons: dict[str, QPushButton] = {}
        for name, title in (("library", "Library"), ("search", "Search"), ("conversation", "Conversation"), ("review", "Review")):
            nav = QPushButton(title); nav.setCheckable(True); nav.setProperty("nav", True)
            nav.clicked.connect(lambda _checked=False, page=name: self.navigate(page))
            side.addWidget(nav); self.nav_buttons[name] = nav
        side.addWidget(label("离线优先 · 本地内容可继续使用", muted=True))
        self.main_splitter.addWidget(sidebar)
        self.workspace = QStackedWidget()
        self.library_page = LibraryPage(self.library_controller, self.context)
        self.search_page = SearchPage(self.search_controller, self.context)
        self.conversation_page = ConversationPage(self.conversation_controller, self.context)
        self.review_page = ReviewPage(self.review_controller, self.context)
        self.event_page = EventPage()
        self.pages = {
            "library": self.library_page,
            "search": self.search_page,
            "conversation": self.conversation_page,
            "review": self.review_page,
            "event": self.event_page,
        }
        for page in self.pages.values():
            self.workspace.addWidget(page)
        self.main_splitter.addWidget(self.workspace); self.main_splitter.setSizes([235, 1200])
        outer.addWidget(self.main_splitter, 1)
        self.activity_bar = ActivityBar(self.activity); outer.addWidget(self.activity_bar)

    def _connect(self) -> None:
        self.library_controller.creators_ready.connect(self._creators_ready)
        self.library_controller.recording_ready.connect(self._event_recording_ready)
        self.library_controller.vod_completed.connect(lambda _row: self.library_page.refresh())
        self.library_page.vod_requested.connect(self.library_controller.download_vod)
        self.library_page.clip_requested.connect(lambda moment: self.search_controller.create_clip(moment.id))
        self.context.moment_opened.connect(self.open_event)
        self.context.clip_opened.connect(self.open_review)
        self.search_controller.clip_created.connect(lambda clip: self.open_review(clip.id))
        self.event_page.back_requested.connect(self.go_back)
        self.event_page.create_clip_requested.connect(lambda moment: self.search_controller.create_clip(moment.id))
        self.context.page_requested.connect(self.navigate)

    def navigate(self, name: str) -> None:
        if name not in self.pages:
            return
        current = self.current_page_name()
        if current and current != name:
            self._nav_history.append(current)
            self._nav_history = self._nav_history[-10:]
        self.workspace.setCurrentWidget(self.pages[name])
        for key, action in self.nav_buttons.items():
            action.setChecked(key == name)
        if name == "review":
            self.review_page.refresh(getattr(self.context.creator, "id", None))
        self.settings.setValue("last_page", name if name in PAGE_NAMES else "library")

    def current_page_name(self) -> str:
        current = self.workspace.currentWidget()
        return next((name for name, page in self.pages.items() if page is current), "")

    def go_back(self) -> None:
        self.navigate(self._nav_history.pop() if self._nav_history else "library")

    def open_event(self, moment) -> None:
        self._event_moment = moment
        recording = self.context.recording
        if recording and recording.id == moment.recording_id:
            self.event_page.load(moment, recording)
            self.navigate("event")
        else:
            self.library_controller.load_recording(moment.recording_id)

    def _event_recording_ready(self, recording) -> None:
        if self._event_moment and self._event_moment.recording_id == recording.id:
            self.event_page.load(self._event_moment, recording)
            self.navigate("event")

    def open_review(self, clip_id: str) -> None:
        self.review_page.open_clip(clip_id)
        self.navigate("review")

    def _creators_ready(self, rows) -> None:
        self.creator_model.replace(rows)
        if not rows:
            self.context.select_creator(None); self.navigate("library"); return
        wanted = str(self.settings.value("last_creator", ""))
        row = next((index for index, item in enumerate(rows) if item.id == wanted), 0)
        index = self.creator_model.index(row, 0)
        self.creators.setCurrentIndex(index)
        self.context.select_creator(rows[row])

    def _creator_selected(self, index) -> None:
        creator = index.data(OBJECT_ROLE)
        if creator:
            self.context.select_creator(creator)
            self.settings.setValue("last_creator", creator.id)

    def _add_source(self) -> None:
        self.navigate("library")
        self.library_page.open_add_source()

    def apply_deep_link(self, payload: dict[str, Any]) -> None:
        recording_id = payload.get("recording_id")
        if recording_id:
            self.library_controller.load_recording(str(recording_id))
        if payload.get("open_review"):
            self.navigate("review")
        event_plan = payload.get("event_plan")
        output_root = payload.get("output_root")
        if event_plan and output_root:
            # Compatibility: old deep links remain available through the
            # canonical workflow, while normal product use opens DB-backed clips.
            try:
                from acfv.clips import GuiVariantWorkflowService
                workflow = GuiVariantWorkflowService(event_plan, output_root, repository=self.backend.library.repository)
                clip_id = workflow.plan.clip_id
                if self.backend.library.repository.get_clip(clip_id):
                    self.open_review(clip_id)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Review Deep Link", str(exc))

    def _restore_shell_state(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self.settings.value("main_splitter")
        if splitter:
            self.main_splitter.restoreState(splitter)
        self.navigate(str(self.settings.value("last_page", "library")))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("main_splitter", self.main_splitter.saveState())
        if self.context.creator:
            self.settings.setValue("last_creator", self.context.creator.id)
        self.library_page.workspace.player.stop()
        self.event_page.player.stop()
        self.review_page.player.stop()
        self.executor.shutdown(wait=False)
        LOGGER.info("GUI shell closed cleanly")
        super().closeEvent(event)

