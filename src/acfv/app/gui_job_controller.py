from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from acfv.backend import service as backend_service


def _parse_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _runtime_summary(payload: Optional[Dict[str, Any]], *, total_key: str, completed_key: str, failed_key: str, running_key: str) -> Dict[str, Any]:
    payload = payload or {}
    return {
        "present": bool(payload),
        "status": str(payload.get("status") or "missing"),
        "total": int(payload.get(total_key, 0) or 0),
        "completed": int(payload.get(completed_key, 0) or 0),
        "failed": int(payload.get(failed_key, 0) or 0),
        "running": int(payload.get(running_key, 0) or 0),
        "updated_at": payload.get("updated_at"),
        "is_active": bool(payload) and str(payload.get("status") or "") == "running",
    }


class GuiJobController:
    """Thin GUI-side adapter over backend service + runtime summaries."""

    def __init__(self, service_module=backend_service) -> None:
        self._service = service_module

    def create_job(self, **kwargs) -> Dict[str, Any]:
        return self._service.create_job(**kwargs)

    def get_job_view(self, job_id: str) -> Dict[str, Any]:
        job = self._service.get_job_status(job_id)
        runtime = {}
        getter = getattr(self._service, "get_runtime_state", None)
        if callable(getter):
            runtime = getter(job_id) or {}
        transcribe = _runtime_summary(
            runtime.get("transcribe_runtime"),
            total_key="total_chunks",
            completed_key="completed_chunks",
            failed_key="failed_chunks",
            running_key="running_chunks",
        )
        render = _runtime_summary(
            runtime.get("render_runtime"),
            total_key="total_clips",
            completed_key="completed_clips",
            failed_key="failed_clips",
            running_key="running_clips",
        )
        current_stage = str(job.get("current_stage") or "queued")
        current_runtime = transcribe if current_stage == "transcribe_chunks" else render if current_stage == "render_clips_batch" else None
        active_runtime = bool(current_runtime and current_runtime.get("is_active"))
        return {
            "job": job,
            "runtime": {
                "transcribe": transcribe,
                "render": render,
            },
            "current_runtime": current_runtime,
            "active_runtime": active_runtime,
            "result_dir": job.get("output_dir") or job.get("run_dir"),
            "error_display": self._build_error_display(job),
        }

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        return self._service.cancel_job(job_id)

    def get_logs(self, job_id: str) -> list[str]:
        return list(self._service.get_logs(job_id))

    def open_result_dir(self, path: str) -> None:
        if not path or not os.path.exists(path):
            raise FileNotFoundError(path or "result directory missing")
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return
        subprocess.Popen(["xdg-open", path])

    def _build_error_display(self, job: Dict[str, Any]) -> str:
        stage = str(job.get("current_stage") or "unknown")
        status = str(job.get("status") or "unknown")
        error = str(job.get("error_summary") or "").strip()
        if not error and status not in {"failed", "cancelled"}:
            return ""
        lines = [
            f"状态: {status}",
            f"阶段: {stage}",
        ]
        if error:
            lines.append(f"摘要: {error}")
        run_dir = job.get("run_dir")
        if run_dir:
            lines.append(f"结果目录: {run_dir}")
        return "\n".join(lines)


__all__ = ["GuiJobController"]
