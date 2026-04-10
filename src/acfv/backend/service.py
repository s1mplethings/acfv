from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .job_manager import JobManager

_manager = JobManager()


def create_job(
    *,
    video_path: str,
    chat_path: Optional[str] = None,
    config_manager: Any = None,
    run_dir: Optional[Path | str] = None,
    output_clips_dir: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    return _manager.create_job(
        video_path=video_path,
        chat_path=chat_path,
        config_manager=config_manager,
        run_dir=run_dir,
        output_clips_dir=output_clips_dir,
        metadata=metadata,
        progress_callback=progress_callback,
    )


def get_job_status(job_id: str) -> Dict[str, Any]:
    return _manager.get_job_status(job_id)


def wait_for_job(job_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
    return _manager.wait_for_job(job_id, timeout=timeout)


def cancel_job(job_id: str) -> Dict[str, Any]:
    return _manager.cancel_job(job_id)


def list_artifacts(job_id: str):
    return _manager.list_artifacts(job_id)


def get_logs(job_id: str):
    return _manager.get_logs(job_id)


def get_runtime_state(job_id: str) -> Dict[str, Any]:
    return _manager.get_runtime_state(job_id)
