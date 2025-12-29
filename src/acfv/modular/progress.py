from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .artifact import new_artifact_id, producer_record
from .contracts import ART_PROGRESS
from .types import ArtifactEnvelope
from .utils import hash_obj


class ProgressEmitter:
    def __init__(self, store, run_id: str, producer_name: str = "pipeline") -> None:
        self.store = store
        self.run_id = run_id
        self.producer_name = producer_name

    def emit(
        self,
        stage: str,
        current: int,
        total: int,
        message: str = "",
        status: str = "running",
        extra: Optional[Dict[str, Any]] = None,
    ) -> ArtifactEnvelope:
        payload: Dict[str, Any] = {
            "run_id": self.run_id,
            "stage": stage,
            "current": int(current),
            "total": int(total),
            "message": message or "",
            "status": status,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        if total:
            payload["percent"] = max(0.0, min(100.0, (current / total) * 100.0))
        if extra:
            payload.update(extra)

        fingerprint = hash_obj(payload)
        producer = producer_record(self.producer_name, "1", hash_obj({"stage": stage}))
        env = ArtifactEnvelope(
            artifact_id=new_artifact_id(),
            type=ART_PROGRESS,
            payload=payload,
            producer=producer,
            fingerprint=fingerprint,
        )
        self.store.write_artifact(env)
        return env


__all__ = ["ProgressEmitter"]
