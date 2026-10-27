#!/usr/bin/env python3
"""Audit and sequentially build a real Creator Library through ACFV's pipeline.

The script deliberately owns orchestration only. Media processing is delegated
to LibraryService -> backend.service -> run_clip_pipeline, preserving the same
pipeline, artifacts, cache fingerprints, and chunk checkpoints used by the app.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acfv.backend import service as backend_service
from acfv.config._config_impl import ConfigManager
from acfv.library import IndexStatus, LibraryService, ProcessingStatus
from acfv.moments import MomentFinalizer
from acfv.moments.models import MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var" / "final_validation_20261007" / "dogfood_import.db"
DEFAULT_BUILD_ROOT = ROOT / "var" / "real_library_build_20261007"
DEFAULT_PROGRESS = ROOT / "var" / "library_build_progress.json"
DEFAULT_MATRIX = ROOT / "evidence" / "validation" / "real-library-reuse-matrix.md"
TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled"}


def resolve_python_executable(explicit: str | Path | None = None) -> Path:
    """Resolve a Python executable without relying on machine-specific paths."""
    source = "explicit Python executable"
    if explicit is not None:
        candidate = explicit
    elif "ACFV_PYTHON" in os.environ:
        source = "ACFV_PYTHON"
        candidate = os.environ["ACFV_PYTHON"]
    else:
        source = "sys.executable"
        candidate = sys.executable

    value = str(candidate).strip()
    if not value:
        raise RuntimeError(f"{source} is empty; provide a valid Python interpreter")
    resolved = Path(os.path.expandvars(value)).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{source} is not a file: {resolved}")
    return resolved


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def first_file(root: Path | None, *relative: str) -> Path | None:
    if root is None:
        return None
    for name in relative:
        candidate = root / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def chunk_inventory(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"count": 0, "valid": 0, "paths": []}
    paths = sorted(root.glob("work/chunks/chunk_*/transcript.json"))
    valid = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload.get("segments"), list):
                valid += 1
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    return {"count": len(paths), "valid": valid, "paths": [str(path) for path in paths]}


def transcript_inventory(root: Path | None) -> dict[str, Any]:
    path = first_file(root, "work/transcript_merged.json", "work/transcription.json")
    result: dict[str, Any] = {"exists": path is not None, "path": str(path) if path else None, "valid": False, "entries": 0}
    if path is None:
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments = payload.get("segments") if isinstance(payload, dict) else None
        result["valid"] = isinstance(segments, list)
        result["entries"] = len(segments) if isinstance(segments, list) else 0
    except (OSError, json.JSONDecodeError):
        pass
    return result


def validate_transcript(path: Path, duration_ms: int | None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        return {"valid": False, "entries": 0, "errors": ["segments is not a list"], "suspect": True}
    duration_sec = max(0.0, float(duration_ms or 0) / 1000.0)
    errors: list[str] = []
    intervals: list[tuple[float, float]] = []
    zero_length = 0
    overlap_count = 0
    previous_start = -1.0
    previous_end = -1.0
    for index, segment in enumerate(segments):
        try:
            start = float(segment.get("start"))
            end = float(segment.get("end"))
        except (AttributeError, TypeError, ValueError):
            errors.append(f"segment {index} has invalid timestamps")
            continue
        if start < 0 or end < start or (duration_sec and end > duration_sec):
            errors.append(f"segment {index} out of bounds: {start}-{end}")
        if start < previous_start:
            errors.append(f"segment {index} is not monotonic")
        if end <= start:
            zero_length += 1
        else:
            intervals.append((max(0.0, start), min(duration_sec or end, end)))
        if previous_end >= 0 and start < previous_end:
            overlap_count += 1
        previous_start = start
        previous_end = max(previous_end, end)
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    spoken_seconds = sum(end - start for start, end in merged)
    last_end = max((end for _, end in intervals), default=0.0)
    zero_mass = bool(segments) and zero_length / len(segments) > 0.05
    suspect = zero_mass or (duration_sec >= 3600 and (last_end < 120 or last_end < duration_sec * 0.05))
    return {
        "valid": not errors,
        "entries": len(segments),
        "errors": errors[:50],
        "zero_length": zero_length,
        "overlap_count": overlap_count,
        "spoken_seconds": round(spoken_seconds, 3),
        "spoken_coverage": round(spoken_seconds / duration_sec, 6) if duration_sec else None,
        "last_timestamp_sec": round(last_end, 3),
        "language": payload.get("language"),
        "suspect": suspect,
    }


def validate_moments(moments: list[Any], duration_ms: int | None) -> dict[str, Any]:
    duration = int(duration_ms or 0)
    invalid = []
    short = 0
    duplicate_keys: set[tuple[int, int, str]] = set()
    duplicates = 0
    for moment in moments:
        if moment.start_ms < 0 or moment.end_ms <= moment.start_ms or (duration and moment.end_ms > duration) or not moment.summary.strip():
            invalid.append(moment.id)
        if moment.end_ms - moment.start_ms < 5000:
            short += 1
        key = (round(moment.start_ms / 1000), round(moment.end_ms / 1000), moment.summary.strip().casefold())
        if key in duplicate_keys:
            duplicates += 1
        duplicate_keys.add(key)
    suspect = bool(moments) and (short / len(moments) > 0.5 or duplicates / len(moments) > 0.1)
    return {
        "valid": not invalid,
        "count": len(moments),
        "invalid_ids": invalid[:50],
        "short_under_5s": short,
        "duplicates": duplicates,
        "suspect": suspect,
    }


def gpu_memory_mib() -> int | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip().isdigit()]
        return sum(values) if values else 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def run_root_for(build_root: Path, recording_id: str) -> Path:
    return build_root / "runs" / recording_id


def audit_library(service: LibraryService, build_root: Path, index_root: Path) -> dict[str, Any]:
    index_error = None
    try:
        indexed_rows = PersistentMomentIndex(service.repository, index_root=index_root).rows()
    except RuntimeError as exc:
        # A stale model/version manifest is itself an audit finding.  Treat the
        # index as unavailable so downstream rebuilding is selected.
        indexed_rows = []
        index_error = str(exc)
    indexed_by_recording: dict[str, int] = {}
    for row in indexed_rows:
        indexed_by_recording[row.recording_id] = indexed_by_recording.get(row.recording_id, 0) + 1
    creators = {creator.id: creator.display_name for creator in service.list_creators()}
    rows = []
    for recording in sorted(service.list_recordings(), key=lambda item: (item.duration_ms or 0, item.id)):
        media = Path(recording.local_path) if recording.local_path else None
        stable_root = run_root_for(build_root, recording.id)
        recorded_root = Path(recording.artifact_root) if recording.artifact_root else None
        # An explicit build root is authoritative.  The database may still point
        # at an empty directory left behind after a recoverable run relocation.
        artifact_root = stable_root if stable_root.is_dir() else recorded_root or stable_root
        transcript = transcript_inventory(artifact_root)
        transcript_validation = (
            validate_transcript(Path(transcript["path"]), recording.duration_ms)
            if transcript["valid"] and transcript["path"]
            else None
        )
        transcript_usable = bool(transcript_validation and transcript_validation["valid"])
        transcript["validation"] = transcript_validation
        chunks = chunk_inventory(artifact_root)
        moments = service.repository.list_moments(recording_id=recording.id, status=MomentStatus.FINAL)
        moment_validation = validate_moments(moments, recording.duration_ms)
        index_count = indexed_by_recording.get(recording.id, 0)
        media_ok = bool(media and media.is_file() and media.stat().st_size > 0)
        audio = first_file(artifact_root, "work/audio/audio.wav", "work/audio.wav")
        chat = first_file(artifact_root, "work/chat.json", "work/chat_with_emotes.json")
        analysis = first_file(artifact_root, "work/high_interest_segments.json", "work/segments.json")
        scene = first_file(artifact_root, "work/scene_analysis.json", "work/screen_context.json")
        ocr = first_file(artifact_root, "work/ocr.json", "work/screen_context.json")
        visual = first_file(artifact_root, "work/visual_analysis.json", "work/screen_context.json")
        if not media_ok:
            action = "BLOCKED"
        elif transcript_usable and moments and moment_validation["valid"] and len(moments) == index_count:
            action = "REUSE"
        elif transcript_usable:
            action = "REBUILD_DOWNSTREAM"
        elif chunks["valid"]:
            action = "RESUME"
        else:
            action = "TRANSCRIBE"
        rows.append(
            {
                "recording_id": recording.id,
                "creator": creators.get(recording.creator_id, recording.creator_id),
                "title": recording.title,
                "local_path": recording.local_path,
                "duration_ms": recording.duration_ms,
                "duration_hours": round((recording.duration_ms or 0) / 3_600_000, 6),
                "size_bytes": recording.file_size or (media.stat().st_size if media_ok and media else 0),
                "recording_status": recording.recording_status.value,
                "processing_status": recording.processing_status.value,
                "index_status": recording.index_status.value,
                "existing_transcript": transcript,
                "existing_audio": {"exists": audio is not None, "path": str(audio) if audio else None},
                "existing_chunks": chunks,
                "existing_chat": {"exists": chat is not None, "path": str(chat) if chat else None},
                "existing_scene_analysis": {"exists": scene is not None, "path": str(scene) if scene else None},
                "existing_ocr": {"exists": ocr is not None, "path": str(ocr) if ocr else None},
                "existing_visual_analysis": {"exists": visual is not None, "path": str(visual) if visual else None},
                "existing_moments": len(moments),
                "existing_moment_validation": moment_validation,
                "existing_index": index_count,
                "artifact_root": str(artifact_root),
                "source_health": "HEALTHY" if media_ok else "MISSING_OR_EMPTY",
                "action": action,
            }
        )
    return {
        "index_error": index_error,
        "generated_at": utc_now(),
        "database": str(service.repository.db_path),
        "index_root": str(index_root),
        "recordings": rows,
        "totals": {
            "recordings": len(rows),
            "duration_hours": sum(row["duration_ms"] or 0 for row in rows) / 3_600_000,
            "raw_bytes": sum(row["size_bytes"] for row in rows),
            "missing_media": sum(row["source_health"] != "HEALTHY" for row in rows),
            "actions": {action: sum(row["action"] == action for row in rows) for action in ("REUSE", "RESUME", "REBUILD_DOWNSTREAM", "TRANSCRIBE", "REPROCESS", "BLOCKED")},
        },
    }


def write_reuse_matrix(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# REAL LIBRARY REUSE MATRIX",
        "",
        f"Generated: `{audit['generated_at']}`",
        "",
        "| Recording | Media | Audio | Transcript | Chat | Analysis | Moment | Index | Action |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in audit["recordings"]:
        analysis = any((row["existing_scene_analysis"]["exists"], row["existing_ocr"]["exists"], row["existing_visual_analysis"]["exists"]))
        lines.append(
            "| {recording_id} | {media} | {audio} | {transcript} | {chat} | {analysis} | {moments} | {index} | {action} |".format(
                recording_id=row["recording_id"],
                media="OK" if row["source_health"] == "HEALTHY" else "MISSING",
                audio="YES" if row["existing_audio"]["exists"] else "NO",
                transcript="YES" if (row["existing_transcript"].get("validation") or {}).get("valid") else "NO",
                chat="YES" if row["existing_chat"]["exists"] else "NO",
                analysis="YES" if analysis else "NO",
                moments=row["existing_moments"],
                index=row["existing_index"],
                action=row["action"],
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_config() -> ConfigManager:
    config = ConfigManager()
    providers = json.loads(json.dumps(config.get("providers") or {}))
    providers.setdefault("asr", {})
    providers["asr"]["default"] = "faster-whisper"
    providers["asr"]["common"] = {"segment_length": 120, "language": "auto", "device": "cuda"}
    providers["asr"]["faster-whisper"] = {"model": "medium"}
    config.update(
        {
            "providers": providers,
            "WHISPER_ENGINE": "faster-whisper",
            "WHISPER_MODEL": "medium",
            "TRANSCRIPTION_LANGUAGE": "auto",
            "SEGMENT_LENGTH": 120,
            "gpu_asr_pool.max_workers": 1,
            "render_pool.max_workers": 1,
            "MAX_CLIP_COUNT": 1,
            "streaming_window.enabled": False,
            "ENABLE_VIDEO_EMOTION": False,
            "ENABLE_AUDIO_FEATURES": False,
            "RAG_ENABLE": False,
            "RAG_WRITE_ANALYSIS_RATINGS": False,
            "ENABLE_SCREEN_DETECT": False,
            "ENABLE_SCREEN_UNDERSTANDING": False,
            "ENABLE_SPEAKER_SEPARATION": False,
            "ENABLE_STREAMER_SUBTITLES": False,
            "ENABLE_SUBTITLE_TRANSLATE": False,
            "ENABLE_LLM_HIGHLIGHT": False,
            "ENABLE_LLM_LOCAL_DISTILL": False,
            "REQUIRE_LLM_API": False,
            "FORCE_RETRANSCRIPTION": False,
        }
    )
    return config


def base_progress(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "started_at": utc_now(),
        "updated_at": utc_now(),
        "recordings_total": audit["totals"]["recordings"],
        "recordings_ready": 0,
        "hours_total": audit["totals"]["duration_hours"],
        "hours_processed": 0.0,
        "current_recording": None,
        "current_stage": "audit_complete",
        "gpu_memory_mib": gpu_memory_mib(),
        "failed": [],
        "recordings": {row["recording_id"]: {"action": row["action"], "status": "PENDING"} for row in audit["recordings"]},
    }


def update_progress(path: Path, progress: dict[str, Any], **changes: Any) -> None:
    progress.update(changes)
    progress["updated_at"] = utc_now()
    write_json_atomic(path, progress)


def wait_for_recording(service: LibraryService, recording_id: str, job_id: str, progress_path: Path, progress: dict[str, Any]) -> dict[str, Any]:
    while True:
        snapshot = backend_service.get_job_status(job_id)
        runtime = backend_service.get_runtime_state(job_id)
        transcribe = runtime.get("transcribe_runtime") or {}
        item = progress["recordings"][recording_id]
        item.update(
            {
                "job_status": snapshot.get("status"),
                "stage": snapshot.get("current_stage"),
                "stage_progress": snapshot.get("progress"),
                "transcribe_runtime": transcribe,
            }
        )
        update_progress(
            progress_path,
            progress,
            current_recording=recording_id,
            current_stage=snapshot.get("current_stage"),
            gpu_memory_mib=gpu_memory_mib(),
        )
        if snapshot.get("status") in TERMINAL_JOB_STATES:
            break
        time.sleep(10)
    if snapshot.get("status") != "succeeded":
        return snapshot
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        recording = service.get_recording(recording_id)
        if recording.processing_status == ProcessingStatus.FAILED:
            return {**snapshot, "status": "failed", "error_summary": recording.error_message}
        if recording.processing_status == ProcessingStatus.READY and recording.index_status == IndexStatus.READY:
            return snapshot
        time.sleep(1)
    return {**snapshot, "status": "failed", "error_summary": "Timed out waiting for Moment finalization and indexing"}


def build_library(
    service: LibraryService,
    audit: dict[str, Any],
    build_root: Path,
    index_root: Path,
    progress_path: Path,
    *,
    max_recordings: int | None = None,
    recording_id: str | None = None,
) -> dict[str, Any]:
    progress = base_progress(audit)
    write_json_atomic(progress_path, progress)
    config = build_config()
    ready_hours = 0.0
    selected = [row for row in audit["recordings"] if recording_id is None or row["recording_id"] == recording_id]
    if recording_id is not None and not selected:
        raise KeyError(f"Unknown recording: {recording_id}")
    if max_recordings is not None:
        selected = selected[:max_recordings]
    for row in selected:
        recording_id = row["recording_id"]
        run_dir = run_root_for(build_root, recording_id)
        started = time.monotonic()
        progress["recordings"][recording_id].update({"status": "RUNNING", "started_at": utc_now(), "run_dir": str(run_dir)})
        update_progress(progress_path, progress, current_recording=recording_id, current_stage="prepare")
        if row["action"] == "BLOCKED":
            snapshot = {"status": "failed", "error_summary": "Source media is missing or empty"}
        elif row["action"] == "REUSE":
            service.update_recording_status(
                recording_id,
                processing_status=ProcessingStatus.READY,
                index_status=IndexStatus.READY,
                error_message=None,
            )
            snapshot = {"status": "succeeded", "reuse": True}
        elif row["action"] == "REBUILD_DOWNSTREAM":
            try:
                artifact_root = Path(row["artifact_root"])
                moments = MomentFinalizer(service.repository).finalize_artifacts(recording_id, artifact_root)
                service.update_recording_status(recording_id, index_status=IndexStatus.INDEXING)
                HybridRetrievalService(
                    service.repository,
                    PersistentMomentIndex(service.repository, index_root=index_root),
                ).rebuild()
                if not moments:
                    raise RuntimeError("Transcript produced no FINAL Moments")
                service.update_recording_status(
                    recording_id,
                    processing_status=ProcessingStatus.READY,
                    index_status=IndexStatus.READY,
                    error_message=None,
                )
                snapshot = {"status": "succeeded", "downstream_only": True}
            except Exception as exc:
                service.update_recording_status(
                    recording_id,
                    processing_status=ProcessingStatus.FAILED,
                    index_status=IndexStatus.FAILED,
                    error_message=str(exc),
                )
                snapshot = {"status": "failed", "error_summary": str(exc)}
        else:
            processed = service.process_recording(
                recording_id,
                config_manager=config,
                run_dir=run_dir,
                output_clips_dir=run_dir / "clips",
            )
            snapshot = wait_for_recording(service, recording_id, processed.last_job_id, progress_path, progress)
        elapsed = time.monotonic() - started
        item = progress["recordings"][recording_id]
        item.update({"finished_at": utc_now(), "elapsed_seconds": elapsed})
        if snapshot.get("status") == "succeeded":
            recording = service.get_recording(recording_id)
            artifact_root = run_dir if run_dir.is_dir() else Path(recording.artifact_root or run_dir)
            transcript = transcript_inventory(artifact_root)
            moments = service.repository.list_moments(recording_id=recording_id, status=MomentStatus.FINAL)
            index_count = sum(row_.recording_id == recording_id for row_ in PersistentMomentIndex(service.repository, index_root=index_root).rows())
            transcript_validation = (
                validate_transcript(Path(transcript["path"]), recording.duration_ms)
                if transcript["valid"] and transcript["path"]
                else {"valid": False, "errors": ["missing transcript"], "suspect": True}
            )
            moment_validation = validate_moments(moments, recording.duration_ms)
            item.update({"transcript_validation": transcript_validation, "moment_validation": moment_validation})
            if (
                not transcript_validation["valid"]
                or not moment_validation["valid"]
                or not moments
                or index_count != len(moments)
            ):
                snapshot = {"status": "failed", "error_summary": "Post-build integrity check failed"}
            else:
                item.update({"status": "READY", "transcript_entries": transcript["entries"], "moment_count": len(moments), "index_count": index_count})
                ready_hours += row["duration_hours"]
                progress["recordings_ready"] += 1
                progress["hours_processed"] = ready_hours
        if snapshot.get("status") != "succeeded":
            error = str(snapshot.get("error_summary") or snapshot.get("status"))
            item.update({"status": "FAILED", "error": error})
            progress["failed"].append({"recording_id": recording_id, "error": error})
        update_progress(progress_path, progress, current_recording=None, current_stage="recording_complete")
    progress["finished_at"] = utc_now()
    stage = "complete" if len(selected) == len(audit["recordings"]) else "partial_complete"
    update_progress(progress_path, progress, current_recording=None, current_stage=stage)
    return progress


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--index-root", type=Path)
    parser.add_argument("--reuse-matrix", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-recordings", type=int)
    parser.add_argument("--recording-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db.resolve()
    build_root = args.build_root.resolve()
    index_root = (getattr(args, "index_root", None) or (ROOT / "var" / "moment_index")).resolve()
    build_root.mkdir(parents=True, exist_ok=True)
    if not db_path.is_file():
        raise FileNotFoundError(f"Library database not found: {db_path}")
    backup = build_root / "backups" / f"{db_path.stem}-pre-build.db"
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, backup)
    service = LibraryService(db_path, index_root=index_root)
    audit = audit_library(service, build_root, index_root)
    write_json_atomic(build_root / "real-library-audit.json", audit)
    matrix_path = getattr(args, "reuse_matrix", None) or DEFAULT_MATRIX
    write_reuse_matrix(matrix_path.resolve(), audit)
    print(json.dumps(audit["totals"], ensure_ascii=False, indent=2))
    if args.audit_only:
        return 0
    os.environ.setdefault("ACFV_TRANSCRIBE_PYTHON", str(resolve_python_executable()))
    os.environ.setdefault("ACFV_TRANSCRIBE_STALL_RESTARTS", "20")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    result = build_library(
        service,
        audit,
        build_root,
        index_root,
        args.progress.resolve(),
        max_recordings=args.max_recordings,
        recording_id=args.recording_id,
    )
    print(json.dumps({"recordings_ready": result["recordings_ready"], "failed": result["failed"]}, ensure_ascii=False, indent=2))
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
