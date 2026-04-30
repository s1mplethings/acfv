from __future__ import annotations

from pathlib import Path
import json

import pytest

from acfv.app.gui_job_controller import GuiJobController


class _Service:
    def __init__(self):
        self.cancelled = []
        self.created = []

    def create_job(self, **kwargs):
        self.created.append(kwargs)
        return {"job_id": "job-1", "status": "pending", "current_stage": "queued", "progress": {}}

    def get_job_status(self, job_id: str):
        return {
            "job_id": job_id,
            "status": "running",
            "current_stage": "transcribe_chunks",
            "progress": {"current": 1, "total": 4, "message": "chunk_0001 started", "percent": 25.0},
            "error_summary": None,
            "run_dir": "E:/runs/job-1",
            "output_dir": "E:/runs/job-1",
            "updated_at": "2026-04-09T12:00:00+00:00",
            "progress_seq": 1,
        }

    def get_runtime_state(self, job_id: str):
        return {
            "transcribe_runtime": {
                "status": "running",
                "total_chunks": 4,
                "completed_chunks": 1,
                "failed_chunks": 0,
                "running_chunks": 1,
                "updated_at": "2026-04-09T12:00:00+00:00",
            },
            "render_runtime": {},
        }

    def cancel_job(self, job_id: str):
        self.cancelled.append(job_id)
        return {"job_id": job_id, "status": "cancelling"}

    def get_logs(self, job_id: str):
        return [f"log:{job_id}"]


def test_gui_job_controller_reads_job_and_runtime_summaries():
    controller = GuiJobController(service_module=_Service())
    view = controller.get_job_view("job-1")

    assert view["job"]["current_stage"] == "transcribe_chunks"
    assert view["runtime"]["transcribe"]["total"] == 4
    assert view["runtime"]["transcribe"]["completed"] == 1
    assert view["runtime"]["transcribe"]["running"] == 1
    assert view["active_runtime"] is True
    assert view["result_dir"] == "E:/runs/job-1"
    assert view["overall_progress"]["stage"] == "transcribe_chunks"
    assert view["overall_progress"]["percent"] > 25.0


def test_gui_job_controller_create_job_uses_backend_service():
    service = _Service()
    controller = GuiJobController(service_module=service)

    result = controller.create_job(video_path="demo.mp4", config_manager=object())

    assert result["job_id"] == "job-1"
    assert service.created[0]["video_path"] == "demo.mp4"


def test_gui_job_controller_cancel_uses_backend_service():
    service = _Service()
    controller = GuiJobController(service_module=service)

    result = controller.cancel_job("job-9")

    assert service.cancelled == ["job-9"]
    assert result["status"] == "cancelling"


class _SequenceService(_Service):
    def __init__(self, jobs):
        super().__init__()
        self.jobs = list(jobs)

    def get_job_status(self, job_id: str):
        if len(self.jobs) > 1:
            return self.jobs.pop(0)
        return self.jobs[0]

    def get_runtime_state(self, job_id: str):
        return {}


def _job(stage, percent, *, updated_at, progress_seq, job_id="job-1", status="running"):
    return {
        "job_id": job_id,
        "status": status,
        "current_stage": stage,
        "progress": {"current": int(percent), "total": 100, "message": "", "percent": float(percent)},
        "error_summary": None,
        "run_dir": "E:/runs/job-1",
        "output_dir": "E:/runs/job-1",
        "updated_at": updated_at,
        "progress_seq": progress_seq,
    }


def test_overall_progress_is_monotonic_within_same_job():
    service = _SequenceService(
        [
            _job("transcribe_chunks", 80, updated_at="2026-04-09T12:00:00+00:00", progress_seq=10),
            _job("transcribe_chunks", 0, updated_at="2026-04-09T12:00:01+00:00", progress_seq=11),
        ]
    )
    controller = GuiJobController(service_module=service)

    first = controller.get_job_view("job-1")["overall_progress"]["percent"]
    second = controller.get_job_view("job-1")["overall_progress"]["percent"]

    assert second == first
    assert second > 0


def test_stage_initialization_zero_does_not_reset_overall_progress():
    service = _SequenceService(
        [
            _job("extract_audio", 100, updated_at="2026-04-09T12:00:00+00:00", progress_seq=10),
            _job("build_audio_chunk_manifest", 0, updated_at="2026-04-09T12:00:01+00:00", progress_seq=11),
        ]
    )
    controller = GuiJobController(service_module=service)

    first = controller.get_job_view("job-1")["overall_progress"]["percent"]
    second = controller.get_job_view("job-1")["overall_progress"]["percent"]

    assert first == 20.0
    assert second == 20.0


def test_out_of_order_job_snapshot_does_not_override_progress():
    service = _SequenceService(
        [
            _job("transcribe_chunks", 50, updated_at="2026-04-09T12:00:05+00:00", progress_seq=5),
            _job("transcribe_chunks", 100, updated_at="2026-04-09T12:00:04+00:00", progress_seq=4),
        ]
    )
    controller = GuiJobController(service_module=service)

    first = controller.get_job_view("job-1")["overall_progress"]["percent"]
    second = controller.get_job_view("job-1")["overall_progress"]

    assert second["percent"] == first
    assert second["stale"] is True
    assert second["accepted"] is False


def test_legacy_progress_callbacks_do_not_write_main_progress_bar():
    pytest.importorskip("PyQt5.QtCore")
    from acfv.steps.local_video_manager.impl import LocalVideoManager

    class _MainWindow:
        def __init__(self):
            self.progress_values = []
            self.details = []

        def update_progress_percent(self, percent):
            self.progress_values.append(percent)

        def update_detailed_progress(self, message):
            self.details.append(message)

    manager = LocalVideoManager.__new__(LocalVideoManager)
    manager.main_window = _MainWindow()

    manager._update_progress_ui("extract_audio", 0, 10, "初始化")
    manager._handle_progress_update("extract_audio", 0, 10, "初始化")
    manager._handle_legacy_percent_update(0)
    manager._handle_legacy_stage_progress("extract_audio", 0, 0.0)

    assert manager.main_window.progress_values == []
    assert manager.main_window.details


def test_apply_job_view_progress_is_the_adapter_write_entry():
    pytest.importorskip("PyQt5.QtCore")
    from acfv.steps.local_video_manager.impl import LocalVideoManager

    class _MainWindow:
        def __init__(self):
            self.progress_values = []

        def update_progress_percent(self, percent):
            self.progress_values.append(percent)

    manager = LocalVideoManager.__new__(LocalVideoManager)
    manager.main_window = _MainWindow()

    manager.apply_job_view_progress({"overall_progress": {"percent": 42.7}})

    assert manager.main_window.progress_values == [42]


def test_local_replay_output_base_uses_replay_download_folder(tmp_path):
    pytest.importorskip("PyQt5.QtCore")
    from acfv.steps.local_video_manager.impl import LocalVideoManager

    manager = LocalVideoManager.__new__(LocalVideoManager)
    manager.config_manager = object()
    replay_dir = tmp_path / "直播回放"

    output_base = manager._resolve_local_replay_output_base(replay_dir)

    assert output_base == replay_dir.resolve()
    assert output_base.exists()


def test_allocate_video_run_dir_auto_resumes_latest_incomplete_run(tmp_path):
    pytest.importorskip("PyQt5.QtCore")
    from acfv.steps.local_video_manager.impl import LocalVideoManager

    manager = LocalVideoManager.__new__(LocalVideoManager)
    video_dir = tmp_path / "video-a"
    run_001 = video_dir / "runs" / "run_001"
    runtime_dir = run_001 / "work" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (run_001 / "work" / "chunks" / "chunk_0000").mkdir(parents=True, exist_ok=True)
    (run_001 / "work" / "chunks" / "chunk_0000" / "transcript.json").write_text("{}", encoding="utf-8")
    (runtime_dir / "transcribe_runtime.json").write_text(
        json.dumps(
            {
                "status": "running",
                "total_chunks": 10,
                "completed_chunks": 3,
            }
        ),
        encoding="utf-8",
    )

    run_dir, reused = manager._allocate_video_run_dir(video_dir, resume_mode=None)

    assert reused is True
    assert Path(run_dir) == run_001


def test_allocate_video_run_dir_restart_creates_new_run(tmp_path):
    pytest.importorskip("PyQt5.QtCore")
    from acfv.steps.local_video_manager.impl import LocalVideoManager

    manager = LocalVideoManager.__new__(LocalVideoManager)
    video_dir = tmp_path / "video-b"
    run_001 = video_dir / "runs" / "run_001"
    (run_001 / "work" / "runtime").mkdir(parents=True, exist_ok=True)
    (run_001 / "work" / "runtime" / "transcribe_runtime.json").write_text(
        json.dumps({"status": "running", "total_chunks": 10, "completed_chunks": 3}),
        encoding="utf-8",
    )

    run_dir, reused = manager._allocate_video_run_dir(video_dir, resume_mode=False)

    assert reused is False
    assert Path(run_dir) == video_dir / "runs" / "run_002"


def test_allocate_video_run_dir_ignores_completed_run(tmp_path):
    pytest.importorskip("PyQt5.QtCore")
    from acfv.steps.local_video_manager.impl import LocalVideoManager

    manager = LocalVideoManager.__new__(LocalVideoManager)
    video_dir = tmp_path / "video-c"
    run_001 = video_dir / "runs" / "run_001"
    runtime_dir = run_001 / "work" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "render_runtime.json").write_text(
        json.dumps({"status": "succeeded", "total_clips": 4, "completed_clips": 4}),
        encoding="utf-8",
    )

    run_dir, reused = manager._allocate_video_run_dir(video_dir, resume_mode=None)

    assert reused is False
    assert Path(run_dir) == video_dir / "runs" / "run_002"
