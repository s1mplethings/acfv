from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_CANCELLING = "cancelling"
STATUS_CANCELLED = "cancelled"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

TERMINAL_STATUSES = {
    STATUS_CANCELLED,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class JobProgress:
    current: int = 0
    total: int = 0
    message: str = ""
    percent: Optional[float] = None

    def update(self, current: int, total: int, message: str = "") -> None:
        self.current = int(current)
        self.total = int(total)
        self.message = message or ""
        if total > 0:
            self.percent = max(0.0, min(100.0, (float(current) / float(total)) * 100.0))
        else:
            self.percent = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current": self.current,
            "total": self.total,
            "message": self.message,
            "percent": self.percent,
        }


@dataclass
class JobState:
    job_id: str
    status: str = STATUS_PENDING
    current_stage: str = "queued"
    progress: JobProgress = field(default_factory=JobProgress)
    error_summary: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    run_dir: Optional[str] = None
    output_dir: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    progress_seq: int = 0

    def touch(self) -> None:
        self.progress_seq += 1
        self.updated_at = _utcnow()

    def append_log(self, message: str) -> None:
        if message:
            self.logs.append(message)
            self.touch()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "current_stage": self.current_stage,
            "progress": self.progress.snapshot(),
            "error_summary": self.error_summary,
            "artifacts": list(self.artifacts),
            "result": dict(self.result),
            "logs": list(self.logs),
            "metadata": dict(self.metadata),
            "run_dir": self.run_dir,
            "output_dir": self.output_dir,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress_seq": self.progress_seq,
        }
