from __future__ import annotations

import json
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    last_error: Exception | None = None
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.02)
    raise last_error if last_error is not None else RuntimeError(f"failed to replace runtime file: {path}")


def init_transcribe_runtime(
    *,
    run_dir: Path | str,
    job_id: str,
    manifest_path: Path | str,
    pool: str = "gpu_asr_pool",
    max_workers: int = 1,
) -> Path:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    runtime_path = Path(run_dir) / "work" / "runtime" / "transcribe_runtime.json"
    chunks = []
    for chunk in manifest.get("chunks", []):
        chunks.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "index": chunk.get("index"),
                "start_sec": chunk.get("start_sec"),
                "end_sec": chunk.get("end_sec"),
                "status": "queued",
                "attempt": 1,
                "worker_id": None,
                "error_summary": None,
                "started_at": None,
                "finished_at": None,
                "result_path": None,
                "segment_count": None,
            }
        )
    payload = {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "stage": "transcribe_chunks",
        "status": "running",
        "total_chunks": len(chunks),
        "completed_chunks": 0,
        "failed_chunks": 0,
        "running_chunks": 0,
        "pool": pool,
        "max_workers": int(max_workers),
        "updated_at": _utcnow(),
        "chunks": chunks,
    }
    with _path_lock(runtime_path):
        _write_json(runtime_path, payload)
    return runtime_path


def init_render_runtime(
    *,
    run_dir: Path | str,
    job_id: str,
    manifest_path: Path | str,
    pool: str = "render_pool",
    max_workers: int = 1,
) -> Path:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    runtime_path = Path(run_dir) / "work" / "runtime" / "render_runtime.json"
    clips = []
    for clip in manifest.get("clips", []):
        clips.append(
            {
                "clip_id": clip.get("clip_id"),
                "rank": clip.get("rank"),
                "start_ms": clip.get("start_ms"),
                "end_ms": clip.get("end_ms"),
                "status": "queued",
                "attempt": 1,
                "worker_id": None,
                "error_summary": None,
                "started_at": None,
                "finished_at": None,
                "output_video": None,
                "subtitle_path": None,
                "thumbnail_path": None,
            }
        )
    payload = {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "stage": "render_clips_batch",
        "status": "running",
        "total_clips": len(clips),
        "completed_clips": 0,
        "failed_clips": 0,
        "running_clips": 0,
        "pool": pool,
        "max_workers": int(max_workers),
        "updated_at": _utcnow(),
        "clips": clips,
    }
    with _path_lock(runtime_path):
        _write_json(runtime_path, payload)
    return runtime_path


def update_runtime_item(
    runtime_path: Path | str,
    *,
    items_key: str,
    item_id_key: str,
    item_id: str,
    status: str,
    worker_id: str | None = None,
    error_summary: str | None = None,
    result_path: str | None = None,
    segment_count: int | None = None,
    output_video: str | None = None,
    subtitle_path: str | None = None,
    thumbnail_path: str | None = None,
) -> Dict[str, Any]:
    path = Path(runtime_path)
    with _path_lock(path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get(items_key, [])
        for item in items:
            if item.get(item_id_key) != item_id:
                continue
            if status == "running":
                item["started_at"] = item.get("started_at") or _utcnow()
                item["worker_id"] = worker_id or item.get("worker_id")
                item["error_summary"] = None
            elif status in {"succeeded", "failed", "cancelled"}:
                if item.get("status") == "queued":
                    item["started_at"] = item.get("started_at") or _utcnow()
                item["finished_at"] = _utcnow()
                if worker_id:
                    item["worker_id"] = worker_id
                item["error_summary"] = error_summary
            item["status"] = status
            if result_path is not None and "result_path" in item:
                item["result_path"] = result_path
            if segment_count is not None and "segment_count" in item:
                item["segment_count"] = int(segment_count)
            if output_video is not None and "output_video" in item:
                item["output_video"] = output_video
            if subtitle_path is not None and "subtitle_path" in item:
                item["subtitle_path"] = subtitle_path
            if thumbnail_path is not None and "thumbnail_path" in item:
                item["thumbnail_path"] = thumbnail_path
            break
        _refresh_summary(payload)
        _write_json(path, payload)
        return payload


def finalize_runtime(runtime_path: Path | str, *, status: str) -> Dict[str, Any]:
    path = Path(runtime_path)
    with _path_lock(path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = status
        payload["updated_at"] = _utcnow()
        _refresh_summary(payload)
        _write_json(path, payload)
        return payload


def read_runtime(runtime_path: Path | str) -> Dict[str, Any]:
    path = Path(runtime_path)
    with _path_lock(path):
        return json.loads(path.read_text(encoding="utf-8"))


def _refresh_summary(payload: Dict[str, Any]) -> None:
    items_key = "chunks" if "chunks" in payload else "clips"
    items = payload.get(items_key, [])
    completed = sum(1 for item in items if item.get("status") == "succeeded")
    failed = sum(1 for item in items if item.get("status") == "failed")
    running = sum(1 for item in items if item.get("status") == "running")
    payload["updated_at"] = _utcnow()
    if items_key == "chunks":
        payload["total_chunks"] = len(items)
        payload["completed_chunks"] = completed
        payload["failed_chunks"] = failed
        payload["running_chunks"] = running
    else:
        payload["total_clips"] = len(items)
        payload["completed_clips"] = completed
        payload["failed_clips"] = failed
        payload["running_clips"] = running


__all__ = [
    "finalize_runtime",
    "init_render_runtime",
    "init_transcribe_runtime",
    "read_runtime",
    "update_runtime_item",
]
