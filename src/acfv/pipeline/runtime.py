from __future__ import annotations

import json
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_STATE_CACHE: dict[str, Dict[str, Any]] = {}
_LAST_FLUSH: dict[str, float] = {}
_SUMMARY_FLUSH_INTERVAL_SEC = 1.0


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
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


def _events_path(runtime_path: Path) -> Path:
    return runtime_path.parent / "events.jsonl"


def _cache_key(path: Path) -> str:
    return str(path.resolve())


def _append_event(runtime_path: Path, event: Dict[str, Any]) -> None:
    event_path = _events_path(runtime_path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0.0", "ts": _utcnow(), **event}
    with _path_lock(event_path):
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _cache_payload(path: Path, payload: Dict[str, Any]) -> None:
    _STATE_CACHE[_cache_key(path)] = payload


def _load_payload(path: Path) -> Dict[str, Any]:
    key = _cache_key(path)
    cached = _STATE_CACHE.get(key)
    if cached is not None:
        return cached
    payload = json.loads(path.read_text(encoding="utf-8"))
    _STATE_CACHE[key] = payload
    return payload


def _flush_summary(path: Path, payload: Dict[str, Any], *, force: bool = False) -> None:
    key = _cache_key(path)
    now = time.monotonic()
    last = _LAST_FLUSH.get(key, 0.0)
    if not force and now - last < _SUMMARY_FLUSH_INTERVAL_SEC:
        return
    _write_json(path, payload)
    _LAST_FLUSH[key] = now


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
        _cache_payload(runtime_path, payload)
        _append_event(
            runtime_path,
            {
                "event": "runtime_initialized",
                "stage": "transcribe_chunks",
                "job_id": job_id,
                "total": len(chunks),
                "pool": pool,
                "max_workers": int(max_workers),
            },
        )
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
        _cache_payload(runtime_path, payload)
        _append_event(
            runtime_path,
            {
                "event": "runtime_initialized",
                "stage": "render_clips_batch",
                "job_id": job_id,
                "total": len(clips),
                "pool": pool,
                "max_workers": int(max_workers),
            },
        )
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
        payload = _load_payload(path)
        items = payload.get(items_key, [])
        found_item: Dict[str, Any] | None = None
        for item in items:
            if item.get(item_id_key) != item_id:
                continue
            found_item = item
            expected_worker_id = worker_id or item.get("worker_id")
            expected_error_summary = error_summary if status in {"running", "succeeded", "failed", "cancelled"} else item.get("error_summary")
            noop = (
                item.get("status") == status
                and item.get("worker_id") == expected_worker_id
                and item.get("error_summary") == expected_error_summary
                and (result_path is None or item.get("result_path") == result_path)
                and (segment_count is None or item.get("segment_count") == int(segment_count))
                and (output_video is None or item.get("output_video") == output_video)
                and (subtitle_path is None or item.get("subtitle_path") == subtitle_path)
                and (thumbnail_path is None or item.get("thumbnail_path") == thumbnail_path)
            )
            if noop:
                return payload
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
        if found_item is None:
            found_item = {item_id_key: item_id, "status": "queued", "attempt": 1}
            if items_key == "clips":
                found_item.update(
                    {
                        "rank": None,
                        "start_ms": None,
                        "end_ms": None,
                        "worker_id": None,
                        "error_summary": None,
                        "started_at": None,
                        "finished_at": None,
                        "output_video": None,
                        "subtitle_path": None,
                        "thumbnail_path": None,
                    }
                )
            else:
                found_item.update(
                    {
                        "index": None,
                        "start_sec": None,
                        "end_sec": None,
                        "worker_id": None,
                        "error_summary": None,
                        "started_at": None,
                        "finished_at": None,
                        "result_path": None,
                        "segment_count": None,
                    }
                )
            items.append(found_item)
            payload[items_key] = items
            return update_runtime_item(
                path,
                items_key=items_key,
                item_id_key=item_id_key,
                item_id=item_id,
                status=status,
                worker_id=worker_id,
                error_summary=error_summary,
                result_path=result_path,
                segment_count=segment_count,
                output_video=output_video,
                subtitle_path=subtitle_path,
                thumbnail_path=thumbnail_path,
            )
        _refresh_summary(payload)
        _append_event(
            path,
            {
                "event": "item_state_changed",
                "stage": payload.get("stage"),
                "job_id": payload.get("job_id"),
                "item_key": item_id_key,
                "item_id": item_id,
                "status": status,
                "worker_id": worker_id,
                "error_summary": error_summary,
                "result_path": result_path,
                "output_video": output_video,
                "found": found_item is not None,
            },
        )
        _flush_summary(path, payload)
        return payload


def finalize_runtime(runtime_path: Path | str, *, status: str) -> Dict[str, Any]:
    path = Path(runtime_path)
    with _path_lock(path):
        payload = _load_payload(path)
        payload["status"] = status
        payload["updated_at"] = _utcnow()
        _refresh_summary(payload)
        _append_event(
            path,
            {
                "event": "runtime_finalized",
                "stage": payload.get("stage"),
                "job_id": payload.get("job_id"),
                "status": status,
            },
        )
        _flush_summary(path, payload, force=True)
        return payload


def read_runtime(runtime_path: Path | str) -> Dict[str, Any]:
    path = Path(runtime_path)
    with _path_lock(path):
        return dict(_load_payload(path))


def append_runtime_event(run_dir: Path | str, event: Dict[str, Any]) -> Path:
    event_path = Path(run_dir) / "work" / "runtime" / "events.jsonl"
    with _path_lock(event_path):
        event_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "1.0.0", "ts": _utcnow(), **dict(event)}
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return event_path


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
    "append_runtime_event",
    "finalize_runtime",
    "init_render_runtime",
    "init_transcribe_runtime",
    "read_runtime",
    "update_runtime_item",
]
