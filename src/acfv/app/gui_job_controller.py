from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from acfv.backend import service as backend_service
from acfv.pipeline.stages import stage_names


_CANONICAL_STAGES = stage_names()
_STAGE_INDEX = {name: index for index, name in enumerate(_CANONICAL_STAGES)}
_STAGE_COUNT = max(1, len(_CANONICAL_STAGES))


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


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_percent(value: Any) -> float:
    return max(0.0, min(100.0, _coerce_float(value, 0.0)))


class GuiJobController:
    """Thin GUI-side adapter over backend service + runtime summaries."""

    def __init__(self, service_module=backend_service) -> None:
        self._service = service_module
        self._progress_memory: Dict[str, Dict[str, Any]] = {}

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
        overall_progress = self._build_overall_progress(job)
        return {
            "job": job,
            "overall_progress": overall_progress,
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

    def _build_overall_progress(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(job.get("job_id") or "")
        progress = job.get("progress", {}) or {}
        status = str(job.get("status") or "unknown")
        stage = str(job.get("current_stage") or "queued")
        updated_at_raw = job.get("updated_at")
        updated_at = _parse_utc(updated_at_raw)
        progress_seq = _coerce_int(job.get("progress_seq"), 0)
        previous = self._progress_memory.get(job_id)

        if previous and self._is_stale_snapshot(updated_at, progress_seq, previous):
            stale = dict(previous)
            stale.update(
                {
                    "accepted": False,
                    "stale": True,
                    "incoming_updated_at": updated_at_raw,
                    "incoming_progress_seq": progress_seq,
                }
            )
            return stale

        raw_stage_percent = progress.get("percent")
        if not isinstance(raw_stage_percent, (int, float)):
            total = _coerce_float(progress.get("total"), 0.0)
            current = _coerce_float(progress.get("current"), 0.0)
            raw_stage_percent = (current / total) * 100.0 if total > 0 else 0.0
        raw_stage_percent = _clamp_percent(raw_stage_percent)
        candidate = self._candidate_overall_percent(stage, status, raw_stage_percent)
        previous_percent = _coerce_float(previous.get("percent"), 0.0) if previous else 0.0
        percent = max(previous_percent, candidate)
        if status == "succeeded" or stage == "completed":
            percent = 100.0
        percent = _clamp_percent(percent)
        stage_index = _STAGE_INDEX.get(stage)
        snapshot = {
            "job_id": job_id,
            "percent": round(percent, 1),
            "stage": stage,
            "stage_index": stage_index,
            "stage_count": _STAGE_COUNT,
            "stage_percent": round(raw_stage_percent, 1),
            "updated_at": updated_at_raw,
            "progress_seq": progress_seq,
            "accepted": True,
            "stale": False,
            "source": "backend_job_state",
        }
        if job_id:
            self._progress_memory[job_id] = snapshot
        return snapshot

    def _candidate_overall_percent(self, stage: str, status: str, stage_percent: float) -> float:
        if status == "succeeded" or stage == "completed":
            return 100.0
        stage_index = _STAGE_INDEX.get(stage)
        if stage_index is None:
            return 0.0
        stage_width = 100.0 / float(_STAGE_COUNT)
        return (float(stage_index) * stage_width) + ((_clamp_percent(stage_percent) / 100.0) * stage_width)

    def _is_stale_snapshot(
        self,
        updated_at: Optional[datetime],
        progress_seq: int,
        previous: Dict[str, Any],
    ) -> bool:
        previous_updated_at = _parse_utc(previous.get("updated_at"))
        if updated_at and previous_updated_at:
            if updated_at < previous_updated_at:
                return True
            if updated_at > previous_updated_at:
                return False
        previous_seq = _coerce_int(previous.get("progress_seq"), 0)
        return progress_seq > 0 and previous_seq > 0 and progress_seq < previous_seq

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
