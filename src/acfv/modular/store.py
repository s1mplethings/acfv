from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .types import ArtifactEnvelope, ArtifactType
from .utils import stable_json


class ArtifactStore:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.artifacts_dir = self.run_dir / "artifacts"
        self.index_path = self.run_dir / "index.json"
        self.producer_index_path = self.run_dir / "producer_index.json"
        self._index: Dict[str, List[str]] = {}
        self._producer_index: Dict[str, List[str]] = {}
        self._ensure_dirs()
        self._load_indexes()

    def _ensure_dirs(self) -> None:
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _load_indexes(self) -> None:
        self._index = self._load_json(self.index_path, default={})
        self._producer_index = self._load_json(self.producer_index_path, default={})

    def _save_indexes(self) -> None:
        self._save_json(self.index_path, self._index)
        self._save_json(self.producer_index_path, self._producer_index)

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(stable_json(data))

    def write_artifact(self, envelope: ArtifactEnvelope) -> ArtifactEnvelope:
        artifact_id = envelope.artifact_id
        if not artifact_id:
            raise ValueError("artifact_id is required")

        artifact_dir = self.artifacts_dir / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        payload_ref = envelope.payload_ref
        payload = envelope.payload
        if payload is not None and payload_ref is None:
            payload_ref = "payload.json"
            payload_path = artifact_dir / payload_ref
            with payload_path.open("w", encoding="utf-8") as f:
                f.write(stable_json(payload))
            envelope.payload_ref = payload_ref

        self._save_json(artifact_dir / "envelope.json", self._envelope_to_dict(envelope))
        type_list = self._index.setdefault(envelope.type, [])
        if artifact_id in type_list:
            type_list = [item for item in type_list if item != artifact_id]
            self._index[envelope.type] = type_list
        type_list.append(artifact_id)

        producer_name = envelope.producer.get("name") if envelope.producer else None
        if producer_name and envelope.fingerprint:
            key = f"{producer_name}|{envelope.fingerprint}"
            id_list = self._producer_index.setdefault(key, [])
            if artifact_id in id_list:
                id_list = [item for item in id_list if item != artifact_id]
                self._producer_index[key] = id_list
            id_list.append(artifact_id)

        self._save_indexes()
        return envelope

    def read_artifact(self, artifact_id: str) -> Optional[ArtifactEnvelope]:
        artifact_dir = self.artifacts_dir / artifact_id
        envelope_path = artifact_dir / "envelope.json"
        if not envelope_path.exists():
            return None

        data = self._load_json(envelope_path, default=None)
        if not data:
            return None
        envelope = self._envelope_from_dict(data)

        if envelope.payload_ref:
            payload_path = artifact_dir / envelope.payload_ref
            if payload_path.exists():
                envelope.payload = self._load_json(payload_path, default=None)
        return envelope

    def list_artifacts(self, artifact_type: Optional[ArtifactType] = None) -> List[str]:
        if artifact_type is None:
            ids: List[str] = []
            for items in self._index.values():
                ids.extend(items)
            return ids
        return list(self._index.get(artifact_type, []))

    def get_latest_by_type(self, artifact_type: ArtifactType) -> Optional[ArtifactEnvelope]:
        ids = self._index.get(artifact_type, [])
        if not ids:
            return None
        return self.read_artifact(ids[-1])

    def find_by_producer_fingerprint(
        self, module_name: str, fingerprint: str
    ) -> List[ArtifactEnvelope]:
        key = f"{module_name}|{fingerprint}"
        ids = self._producer_index.get(key, [])
        results: List[ArtifactEnvelope] = []
        for artifact_id in ids:
            env = self.read_artifact(artifact_id)
            if env is not None:
                results.append(env)
        return results

    def _envelope_to_dict(self, envelope: ArtifactEnvelope) -> Dict[str, Any]:
        payload = None
        if envelope.payload_ref is None:
            payload = envelope.payload
        return {
            "artifact_id": envelope.artifact_id,
            "type": envelope.type,
            "schema_version": envelope.schema_version,
            "timebase": envelope.timebase,
            "time_range": envelope.time_range,
            "producer": envelope.producer,
            "payload": payload,
            "payload_ref": envelope.payload_ref,
            "fingerprint": envelope.fingerprint,
            "depends_on": envelope.depends_on,
        }

    def _envelope_from_dict(self, data: Dict[str, Any]) -> ArtifactEnvelope:
        return ArtifactEnvelope(
            artifact_id=data.get("artifact_id", ""),
            type=data.get("type", ""),
            schema_version=data.get("schema_version", "1"),
            timebase=data.get("timebase", "seconds"),
            time_range=data.get("time_range"),
            producer=data.get("producer", {}),
            payload=data.get("payload"),
            payload_ref=data.get("payload_ref"),
            fingerprint=data.get("fingerprint"),
            depends_on=data.get("depends_on", []) or [],
        )


__all__ = ["ArtifactStore"]
