"""Page controllers coordinating view state with canonical backend adapters."""

from __future__ import annotations

import time
import uuid
from typing import Any

from PyQt5.QtCore import QObject, pyqtSignal

from .backend import ProductBackend
from .viewmodels import JobVM
from .workers import GuiExecutor, RequestToken


class ProductContext(QObject):
    creator_changed = pyqtSignal(object)
    recording_changed = pyqtSignal(object)
    moment_opened = pyqtSignal(object)
    clip_opened = pyqtSignal(str)
    page_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.creator = None
        self.recording = None

    def select_creator(self, creator: Any | None) -> None:
        if getattr(self.creator, "id", None) == getattr(creator, "id", None):
            return
        self.creator = creator
        self.recording = None
        self.creator_changed.emit(creator)
        self.recording_changed.emit(None)

    def select_recording(self, recording: Any | None) -> None:
        self.recording = recording
        self.recording_changed.emit(recording)


class ActivityController(QObject):
    changed = pyqtSignal(object)
    cancel_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._jobs: dict[str, JobVM] = {}
        self._started: dict[str, float] = {}
        self._backend_job_ids: set[str] = set()

    @property
    def jobs(self) -> list[JobVM]:
        for job_id, started in self._started.items():
            if job_id in self._jobs and self._jobs[job_id].state in {"排队中", "处理中"}:
                self._jobs[job_id].elapsed_seconds = time.monotonic() - started
        return list(reversed(list(self._jobs.values())))

    def begin(self, label: str, context: str, *, cancellable: bool = False) -> str:
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = JobVM(job_id, label, context, state="处理中", cancellable=cancellable)
        self._started[job_id] = time.monotonic()
        self.changed.emit(self.jobs)
        return job_id

    def progress(self, job_id: str, value: Any) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        if isinstance(value, dict):
            job.state = str(value.get("message") or value.get("stage") or "处理中")
            percent = value.get("percent")
            job.progress = float(percent) if percent is not None else None
        self.changed.emit(self.jobs)

    def succeed(self, job_id: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id].state = "已完成"
            self._jobs[job_id].progress = 100.0
            self.changed.emit(self.jobs)

    def fail(self, job_id: str, message: str) -> None:
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.state = "失败"
            job.error = message
            job.retryable = True
            self.changed.emit(self.jobs)

    def track_backend(self, job_id: str, label: str, context: str) -> None:
        if not job_id:
            return
        self._jobs[job_id] = JobVM(job_id, label, context, state="排队中", cancellable=True)
        self._backend_job_ids.add(job_id)
        self._started[job_id] = time.monotonic()
        self.changed.emit(self.jobs)

    def update_backend(self, job_id: str, view: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        backend_job = view.get("job") or {}
        state = str(backend_job.get("status") or "unknown")
        labels = {"pending": "排队中", "running": "处理中", "cancelling": "取消中", "cancelled": "已取消", "succeeded": "已完成", "failed": "失败"}
        job.state = labels.get(state, state)
        job.progress = float((view.get("overall_progress") or {}).get("percent") or 0)
        job.error = str(backend_job.get("error_summary") or "")
        job.cancellable = state in {"pending", "running"}
        job.retryable = state == "failed"
        if state in {"cancelled", "succeeded", "failed"}:
            self._backend_job_ids.discard(job_id)
        self.changed.emit(self.jobs)


class Controller(QObject):
    busy = pyqtSignal(str)
    error = pyqtSignal(str, str)

    def __init__(self, backend: ProductBackend, executor: GuiExecutor, activity: ActivityController, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.executor = executor
        self.activity = activity
        self._jobs_by_token: dict[RequestToken, str] = {}
        executor.task_failed.connect(self._failed)
        executor.task_progress.connect(self._progress)

    def _submit(self, channel: str, label: str, context: str, operation, *args, with_progress=False, **kwargs) -> RequestToken:
        job_id = self.activity.begin(label, context)
        self.busy.emit(channel)
        if with_progress:
            kwargs["_with_progress"] = True
        token = self.executor.submit(channel, operation, *args, **kwargs)
        self._jobs_by_token[token] = job_id
        return token

    def _complete(self, token: RequestToken) -> None:
        job_id = self._jobs_by_token.pop(token, None)
        if job_id:
            self.activity.succeed(job_id)

    def _failed(self, token: RequestToken, message: str, details: str) -> None:
        if token not in self._jobs_by_token:
            return
        job_id = self._jobs_by_token.pop(token)
        self.activity.fail(job_id, message)
        self.error.emit(message, details)

    def _progress(self, token: RequestToken, value: Any) -> None:
        job_id = self._jobs_by_token.get(token)
        if job_id:
            self.activity.progress(job_id, value)


class LibraryController(Controller):
    creators_ready = pyqtSignal(object)
    recordings_ready = pyqtSignal(object)
    moments_ready = pyqtSignal(object)
    imported = pyqtSignal(object)
    processing_started = pyqtSignal(object)
    recording_ready = pyqtSignal(object)
    vod_completed = pyqtSignal(object)
    thumbnail_ready = pyqtSignal(str, str)
    profile_ready = pyqtSignal(object)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.executor.result_ready.connect(self._result)

    def load_creators(self) -> None:
        self._submit("library.creators", "加载 Creator", "Creator Library", self.backend.creators)

    def load_recordings(self, creator_id: str | None) -> None:
        self._submit("library.recordings", "加载 Recording", creator_id or "全部 Creator", self.backend.recordings, creator_id)

    def build_profile(self, creator_id: str) -> None:
        self._submit("library.creator-profile", "构建 Creator Profile", creator_id, self.backend.build_creator_profile, creator_id)

    def load_thumbnail(self, recording) -> None:
        self.executor.submit(f"library.thumbnail.{recording.id}", self.backend.recording_thumbnail, recording)

    def load_moments(self, recording_id: str) -> None:
        self._submit("library.moments", "加载 Moment", recording_id, self.backend.moments, recording_id)

    def load_recording(self, recording_id: str) -> None:
        self._submit("library.recording", "加载 Recording", recording_id, self.backend.recording, recording_id)

    def import_local(self, path: str, creator_id: str) -> None:
        self._submit("library.import", "导入本地视频", path, self.backend.import_local, path, creator_id)

    def process(self, recording_id: str) -> None:
        self._submit("library.process", "处理 Recording", recording_id, self.backend.process_recording, recording_id)

    def relink(self, recording_id: str, path: str) -> None:
        self._submit("library.relink", "重新关联媒体", path, self.backend.relink_recording, recording_id, path)

    def download_vod(self, url: str, start_ms: int | None, end_ms: int | None) -> None:
        self._submit(
            "library.vod", "下载 Twitch VOD", url, self.backend.download_vod, url,
            start_ms=start_ms, end_ms=end_ms, with_progress=True,
        )

    def _result(self, token: RequestToken, value: Any) -> None:
        if token.channel.startswith("library.thumbnail."):
            self.thumbnail_ready.emit(str(value[0]), str(value[1]))
            return
        if token not in self._jobs_by_token:
            return
        self._complete(token)
        signals = {
            "library.creators": self.creators_ready,
            "library.recordings": self.recordings_ready,
            "library.moments": self.moments_ready,
            "library.recording": self.recording_ready,
            "library.import": self.imported,
            "library.process": self.processing_started,
            "library.relink": self.recording_ready,
            "library.vod": self.vod_completed,
            "library.creator-profile": self.profile_ready,
        }
        signal = signals.get(token.channel)
        if signal:
            signal.emit(value)
            if token.channel in {"library.import", "library.process"} and getattr(value, "job_id", ""):
                self.activity.track_backend(value.job_id, "Processing", value.title)


class SearchController(Controller):
    results_ready = pyqtSignal(object)
    clip_created = pyqtSignal(object)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.executor.result_ready.connect(self._result)
        self.last_query = ""

    def search(self, query: str, *, scope: str, creator_id: str | None, recording_id: str | None, limit: int = 20) -> None:
        self.last_query = query.strip()
        self._submit(
            "search.query", "搜索", self.last_query, self.backend.search, self.last_query,
            scope=scope, creator_id=creator_id, recording_id=recording_id, limit=limit,
        )

    def create_clip(self, moment_id: str) -> None:
        self._submit("search.clip", "创建 Clip", moment_id, self.backend.create_clip, moment_id, self.last_query)

    def _result(self, token: RequestToken, value: Any) -> None:
        if token.channel == "search.query" and token in self._jobs_by_token:
            self._complete(token)
            self.results_ready.emit(value)
        elif token.channel == "search.clip" and token in self._jobs_by_token:
            self._complete(token)
            self.clip_created.emit(value)


class ConversationController(Controller):
    answer_ready = pyqtSignal(object)
    clip_created = pyqtSignal(object)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.executor.result_ready.connect(self._result)

    def ask(self, query: str, *, scope: str, creator_id: str | None, recording_id: str | None) -> None:
        self._submit(
            "conversation.ask", "寻找证据", query, self.backend.ask, query,
            scope=scope, creator_id=creator_id, recording_id=recording_id,
        )

    def create_clip(self, moment_id: str, query: str) -> None:
        self._submit("conversation.clip", "创建 Clip", moment_id, self.backend.create_clip, moment_id, query)

    def _result(self, token: RequestToken, value: Any) -> None:
        if token.channel == "conversation.ask" and token in self._jobs_by_token:
            self._complete(token)
            self.answer_ready.emit(value)
        elif token.channel == "conversation.clip" and token in self._jobs_by_token:
            self._complete(token)
            self.clip_created.emit(value)


class ReviewController(Controller):
    clips_ready = pyqtSignal(object)
    snapshot_ready = pyqtSignal(object)
    variant_ready = pyqtSignal(object)
    cues_saved = pyqtSignal(object)
    render_ready = pyqtSignal(object)
    decision_ready = pyqtSignal(object)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.executor.result_ready.connect(self._result)

    def load_clips(self, creator_id: str | None = None) -> None:
        self._submit("review.clips", "加载 Review", creator_id or "全部 Creator", self.backend.clip_rows, creator_id)

    def open_clip(self, clip_id: str) -> None:
        self._submit("review.open", "打开 Clip", clip_id, self.backend.review_snapshot, clip_id)

    def select_variant(self, workflow, profile: str) -> None:
        self._submit("review.variant", "切换时长", profile, self.backend.select_variant, workflow, profile)

    def save_cues(self, workflow, profile: str, edits: list[dict[str, str]]) -> None:
        self._submit("review.save", "保存字幕", profile, self.backend.save_cues, workflow, profile, edits)

    def rerender(self, workflow, profile: str, start_ms: int, end_ms: int) -> None:
        self._submit(
            "review.render", "渲染新版本", profile, self.backend.rerender, workflow, profile,
            start_ms=start_ms, end_ms=end_ms, with_progress=True,
        )

    def generate(self, workflow, profile: str) -> None:
        self._submit(
            "review.generate", "生成时长版本", profile, self.backend.generate_variant, workflow, profile,
            with_progress=True,
        )

    def decide(self, workflow, decision: str, reason: str = "") -> None:
        self._submit("review.decision", "保存 Review", decision, self.backend.decide, workflow, decision, reason)

    def _result(self, token: RequestToken, value: Any) -> None:
        if token not in self._jobs_by_token:
            return
        self._complete(token)
        mapping = {
            "review.clips": self.clips_ready,
            "review.open": self.snapshot_ready,
            "review.variant": self.variant_ready,
            "review.save": self.cues_saved,
            "review.render": self.render_ready,
            "review.generate": self.render_ready,
            "review.decision": self.decision_ready,
        }
        signal = mapping.get(token.channel)
        if signal:
            signal.emit(value)


class JobsController(QObject):
    """Poll and cancel durable backend jobs without blocking the GUI thread."""

    def __init__(self, backend: ProductBackend, executor: GuiExecutor, activity: ActivityController, parent=None) -> None:
        super().__init__(parent)
        self.backend = backend; self.executor = executor; self.activity = activity
        executor.result_ready.connect(self._result)
        executor.task_failed.connect(self._failed)
        activity.cancel_requested.connect(self.cancel)

    def poll(self) -> None:
        for job_id in tuple(self.activity._backend_job_ids):
            job = self.activity._jobs.get(job_id)
            if job and job.state in {"排队中", "处理中", "取消中"}:
                self.executor.submit(f"jobs.poll.{job_id}", self.backend.job_view, job_id)

    def cancel(self, job_id: str) -> None:
        job = self.activity._jobs.get(job_id)
        if job and job.cancellable and job_id in self.activity._backend_job_ids:
            self.executor.submit(f"jobs.cancel.{job_id}", self.backend.cancel_job, job_id)

    def _result(self, token: RequestToken, value: Any) -> None:
        if token.channel.startswith("jobs.poll."):
            self.activity.update_backend(token.channel.removeprefix("jobs.poll."), value)
        elif token.channel.startswith("jobs.cancel."):
            job_id = token.channel.removeprefix("jobs.cancel.")
            job = self.activity._jobs.get(job_id)
            if job:
                job.state = "取消中"; job.cancellable = False; self.activity.changed.emit(self.activity.jobs)

    def _failed(self, token: RequestToken, message: str, _details: str) -> None:
        if token.channel.startswith("jobs."):
            self.activity.fail(token.channel.rsplit(".", 1)[-1], message)

