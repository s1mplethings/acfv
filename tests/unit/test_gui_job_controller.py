from __future__ import annotations

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
