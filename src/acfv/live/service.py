from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from acfv.library.models import IndexStatus, RecordingStatus, utc_now
from acfv.library.repository import LibraryRepository
from acfv.moments import MomentFinalizer, MomentService, MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex
from acfv.runtime.storage import storage_root


class SegmentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class SegmentRecord:
    id: str
    path: str
    start_ms: int
    end_ms: int
    status: str
    transcript_path: str | None = None
    error: str | None = None


class LiveProcessingService:
    """Canonical coordinator for closed-segment ASR, Moments, and live indexing."""

    def __init__(
        self,
        recording_id: str,
        repository: LibraryRepository,
        *,
        root: Path | None = None,
        transcriber: Callable[[Path, Path], dict[str, Any]] | None = None,
        moment_index: PersistentMomentIndex | None = None,
    ) -> None:
        recording = repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        self.recording_id = recording_id
        self.repository = repository
        self.root = Path(root or storage_root() / "recordings" / recording_id)
        self.segment_root = self.root / "segments"
        self.work_root = self.root / "work"
        self.transcript_root = self.work_root / "segments"
        for path in (self.segment_root, self.transcript_root):
            path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "segment_manifest.json"
        self.events_path = self.root / "events.jsonl"
        self.merged_path = self.work_root / "transcript_merged.json"
        self.chat_path = self.work_root / "chat.json"
        self.transcriber = transcriber or self._default_transcriber
        self.index = moment_index or PersistentMomentIndex(repository)
        self.retrieval = HybridRetrievalService(repository, self.index)
        self.moments = MomentService(repository)

    def warmup(self) -> bool:
        """Best-effort import/runtime discovery before the first segment closes."""
        try:
            os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
            from acfv.steps.transcribe_audio import impl

            impl._resolve_transcribe_python()
            return True
        except Exception:
            return False

    def close_segment(
        self,
        segment_id: str,
        path: Path | str,
        start_ms: int,
        end_ms: int,
    ) -> list[Any]:
        segment_path = Path(path).expanduser().resolve()
        if not segment_path.is_file():
            raise FileNotFoundError(segment_path)
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("segment must have a positive recording-relative range")
        manifest = self._manifest()
        existing = self._find(manifest, segment_id)
        if existing and existing["status"] == SegmentStatus.DONE.value:
            return self.repository.list_moments(recording_id=self.recording_id, status=MomentStatus.PROVISIONAL)
        if existing is None:
            previous = manifest["segments"][-1] if manifest["segments"] else None
            if previous and int(previous["end_ms"]) != start_ms:
                raise ValueError("closed segments must be continuous and ordered")
            existing = asdict(SegmentRecord(segment_id, str(segment_path), start_ms, end_ms, SegmentStatus.CLOSED.value))
            manifest["segments"].append(existing)
            self._save_manifest(manifest)
            self._event(
                "segment_closed",
                {
                    "segment_id": existing["id"],
                    "path": existing["path"],
                    "start_ms": existing["start_ms"],
                    "end_ms": existing["end_ms"],
                },
            )
        return self._process(existing)

    def append_chat(self, timestamp_ms: int, username: str, message: str, **metadata: Any) -> None:
        if timestamp_ms < 0:
            raise ValueError("chat timestamp must be recording-relative")
        payload = self._read_json(self.chat_path, {"records": []})
        payload["records"].append(
            {"timestamp": timestamp_ms / 1000.0, "username": username, "message": message, **metadata}
        )
        payload["records"].sort(key=lambda item: float(item["timestamp"]))
        self._write_json(self.chat_path, payload)

    def retry_failed(self) -> int:
        retried = 0
        for item in list(self._manifest()["segments"]):
            if item["status"] == SegmentStatus.FAILED.value:
                self._process(item)
                retried += 1
        return retried

    def finalize(self, *, final_source: Path | str | None = None) -> list[Any]:
        pending = [item for item in self._manifest()["segments"] if item["status"] != SegmentStatus.DONE.value]
        if pending:
            raise RuntimeError(f"cannot finalize with unfinished segments: {[item['id'] for item in pending]}")
        for moment in self.repository.list_moments(recording_id=self.recording_id, status=MomentStatus.PROVISIONAL):
            moment.status = MomentStatus.FINALIZING
            self.repository.save(moment)
        transcript = self._read_json(self.merged_path, {"segments": []})
        chat = self._read_json(self.chat_path, {"records": []})
        final = MomentFinalizer(self.repository).finalize(
            self.recording_id,
            transcript,
            chat,
            transcript_artifact=str(self.merged_path),
            chat_artifact=str(self.chat_path) if self.chat_path.is_file() else None,
        )
        recording = self.repository.get_recording(self.recording_id)
        if recording is None:
            raise KeyError(self.recording_id)
        recording.recording_status = RecordingStatus.COMPLETE
        recording.ended_at = recording.ended_at or utc_now()
        recording.artifact_root = str(self.root)
        if final_source:
            source = Path(final_source).expanduser().resolve()
            if source.is_file():
                recording.local_path = str(source)
                recording.canonical_path = str(source)
                recording.file_size = source.stat().st_size
        recording.index_status = IndexStatus.INDEXING
        self.repository.save(recording)
        self.retrieval.rebuild()
        self._event("live_finalized", {"final_moment_count": len(final)})
        return final

    def _process(self, item: dict[str, Any]) -> list[Any]:
        self._update(item["id"], status=SegmentStatus.PROCESSING.value, error=None)
        transcript_path = self.transcript_root / item["id"] / "transcript.json"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            relative = self.transcriber(Path(item["path"]), transcript_path)
            absolute = self._absolute_transcript(
                relative,
                int(item["start_ms"]),
                int(item["end_ms"]),
            )
            self._write_json(transcript_path, absolute)
            self._update(item["id"], status=SegmentStatus.DONE.value, transcript_path=str(transcript_path), error=None)
            merged = self._merge_transcripts()
            chat = self._read_json(self.chat_path, {"records": []})
            moments = self.moments.ingest_incremental(
                self.recording_id,
                merged,
                chat,
                transcript_artifact=str(self.merged_path),
                chat_artifact=str(self.chat_path) if self.chat_path.is_file() else None,
            )
            self.retrieval.rebuild()
            self._event("segment_processed", {"segment_id": item["id"], "moment_ids": [moment.id for moment in moments]})
            return moments
        except Exception as exc:
            self._update(item["id"], status=SegmentStatus.FAILED.value, error=str(exc))
            self._event("segment_failed", {"segment_id": item["id"], "error": str(exc)})
            raise

    def _merge_transcripts(self) -> dict[str, Any]:
        segments = []
        for item in self._manifest()["segments"]:
            path = item.get("transcript_path")
            if item["status"] == SegmentStatus.DONE.value and path and Path(path).is_file():
                segments.extend(self._read_json(Path(path), {"segments": []})["segments"])
        segments.sort(key=lambda entry: (float(entry["start"]), float(entry["end"])))
        payload = {"schema_version": "1.0", "partial": True, "segments": segments}
        self._write_json(self.merged_path, payload)
        return payload

    @staticmethod
    def _absolute_transcript(
        payload: dict[str, Any],
        offset_ms: int,
        segment_end_ms: int | None = None,
    ) -> dict[str, Any]:
        result = dict(payload)
        lower = offset_ms / 1000.0
        upper = segment_end_ms / 1000.0 if segment_end_ms is not None else None
        bounded = []
        for segment in payload.get("segments", []):
            start = max(lower, float(segment["start"]) + lower)
            end = float(segment["end"]) + lower
            if upper is not None:
                end = min(upper, end)
            if end <= start:
                continue
            bounded.append({**segment, "start": start, "end": end})
        result["segments"] = bounded
        result["recording_offset_ms"] = offset_ms
        return result

    @staticmethod
    def _default_transcriber(path: Path, transcript_path: Path) -> dict[str, Any]:
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        from acfv.steps.transcribe_audio.impl import transcribe_audio

        payload = {
            "source_path": str(path),
            "work_dir": str(transcript_path.parent),
            "transcript_path": str(transcript_path),
            "output_format": "json",
        }
        return transcribe_audio(payload)

    def _manifest(self) -> dict[str, Any]:
        return self._read_json(self.manifest_path, {"schema_version": "1.0", "recording_id": self.recording_id, "segments": []})

    @staticmethod
    def _find(manifest: dict[str, Any], segment_id: str) -> dict[str, Any] | None:
        return next((item for item in manifest["segments"] if item["id"] == segment_id), None)

    def _update(self, segment_id: str, **changes: Any) -> None:
        manifest = self._manifest()
        item = self._find(manifest, segment_id)
        if item is None:
            raise KeyError(segment_id)
        item.update(changes)
        self._save_manifest(manifest)

    def _save_manifest(self, payload: dict[str, Any]) -> None:
        self._write_json(self.manifest_path, payload)

    def _event(self, event_type: str, details: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"type": event_type, "recording_id": self.recording_id, "timestamp": utc_now().isoformat(), **details}
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
