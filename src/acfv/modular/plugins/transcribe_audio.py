from __future__ import annotations

import json
import math
import os
import threading
import re
from pathlib import Path
from typing import Any, Dict
from concurrent.futures import ThreadPoolExecutor

from acfv.modular.contracts import ART_AUDIO, ART_TRANSCRIPT
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.pipeline.runtime import append_runtime_event, finalize_runtime, init_render_runtime, init_transcribe_runtime, read_runtime, update_runtime_item
from acfv.steps.render_clips.impl import NAMING_POLICY as CLIP_NAMING_POLICY, cut_video_ffmpeg
from acfv.steps.transcribe_audio.impl import run_transcribe_subprocess_guarded
import logging


def _chunk_output_path(chunks_dir: Path, chunk_id: str) -> Path:
    chunk_dir = chunks_dir / chunk_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    return chunk_dir / "transcript.json"


def _chunk_segments(segments: list[dict[str, Any]], start_sec: float, end_sec: float, *, is_last: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for seg in segments:
        seg_start = float(seg.get("start", 0.0))
        if seg_start < start_sec:
            continue
        if is_last:
            if seg_start > end_sec:
                continue
        elif seg_start >= end_sec:
            continue
        selected.append(dict(seg))
    return selected


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _format_hhmmss(start_sec: float) -> str:
    total = max(0, int(float(start_sec or 0.0)))
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}h{mm:02d}m{ss:02d}s"


def _normalize_window(start_sec: float, end_sec: float, *, min_duration_sec: float) -> tuple[float, float, int, int]:
    start = max(0.0, float(start_sec or 0.0))
    end = max(start, float(end_sec or 0.0))
    if end - start < min_duration_sec:
        end = start + float(min_duration_sec)
    start_ms = int(round(start * 1000))
    end_ms = int(round(end * 1000))
    start = start_ms / 1000.0
    end = end_ms / 1000.0
    return start, end, start_ms, end_ms


def _window_identity(start_ms: int, end_ms: int) -> str:
    return f"{int(start_ms)}:{int(end_ms)}"


def _chunk_runtime_result_path(chunks_dir: Path, chunk_id: str) -> Path:
    return chunks_dir / chunk_id / "transcript.json"


def _read_segment_count(result_path: Path) -> int | None:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return None
    return len(segments)


def _parse_stalled_chunk_index(message: str) -> int | None:
    match = re.search(r"chunk\s+(\d+)", str(message or ""), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


class _StreamingFastPath:
    def __init__(
        self,
        *,
        ctx: ModuleContext,
        work_dir: Path,
        video_path: str | None,
        output_dir: str | None,
        render_workers: int,
        window_chunks: int,
        min_duration_sec: float,
    ) -> None:
        self.ctx = ctx
        self.work_dir = work_dir
        self.video_path = video_path
        self.output_dir = Path(output_dir) if output_dir else Path(ctx.store.run_dir)
        self.render_workers = max(1, int(render_workers or 1))
        self.window_chunks = max(1, int(window_chunks or 1))
        self.min_duration_sec = max(0.1, float(min_duration_sec or 6.0))
        self.pending_segments: list[dict[str, Any]] = []
        self.completed_since_window = 0
        self.rank = 0
        self.futures = []
        self.executor: ThreadPoolExecutor | None = None
        self.runtime_path: Path | None = None
        self.enabled = bool(video_path)
        self._lock = threading.RLock()
        self._seen_chunk_results: set[tuple[str, str]] = set()
        self._window_items: dict[str, dict[str, Any]] = {}
        self._window_states: dict[str, str] = {}

    def start(self) -> None:
        if not self.enabled:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        seed_manifest = self.work_dir / "streaming" / "render_seed_manifest.json"
        _write_json(
            seed_manifest,
            {
                "schema_version": "1.0.0",
                "stage": "streaming_render_seed",
                "clip_count": 0,
                "clips": [],
            },
        )
        self.runtime_path = init_render_runtime(
            run_dir=self.ctx.store.run_dir,
            job_id=self.ctx.run_id,
            manifest_path=seed_manifest,
            pool="render_pool",
            max_workers=self.render_workers,
        )
        self.executor = ThreadPoolExecutor(max_workers=self.render_workers, thread_name_prefix="render_pool")
        append_runtime_event(
            self.ctx.store.run_dir,
            {
                "event": "streaming_fast_path_started",
                "stage": "render_clips_batch",
                "render_workers": self.render_workers,
            },
        )

    def on_chunk_result(self, chunk_id: str, result_path: str | None) -> None:
        if not result_path:
            return
        chunk_key = (str(chunk_id), str(result_path))
        with self._lock:
            if chunk_key in self._seen_chunk_results:
                append_runtime_event(
                    self.ctx.store.run_dir,
                    {
                        "event": "streaming_chunk_result_deduplicated",
                        "stage": "merge_transcript",
                        "chunk_id": chunk_id,
                        "result_path": str(result_path),
                    },
                )
                return
            self._seen_chunk_results.add(chunk_key)
        try:
            payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
        except Exception as exc:
            append_runtime_event(
                self.ctx.store.run_dir,
                {"event": "streaming_chunk_read_failed", "stage": "merge_transcript", "chunk_id": chunk_id, "error": str(exc)},
            )
            return
        segments = [seg for seg in payload.get("segments", []) if isinstance(seg, dict)]
        self.pending_segments.extend(segments)
        self.completed_since_window += 1
        append_runtime_event(
            self.ctx.store.run_dir,
            {
                "event": "incremental_merge_done",
                "stage": "merge_transcript",
                "chunk_id": chunk_id,
                "window_segment_count": len(self.pending_segments),
            },
        )
        if self.completed_since_window >= self.window_chunks:
            self.flush_window(reason="chunk_window")

    def flush_window(self, *, reason: str) -> None:
        if not self.enabled or not self.pending_segments or not self.executor or not self.runtime_path:
            self.pending_segments.clear()
            self.completed_since_window = 0
            return
        valid_segments = []
        for seg in self.pending_segments:
            try:
                start = float(seg.get("start", 0.0))
                end = float(seg.get("end", 0.0))
            except Exception:
                continue
            if end > start:
                valid_segments.append({"start": start, "end": end, "text": str(seg.get("text") or "")})
        self.pending_segments = []
        self.completed_since_window = 0
        if not valid_segments:
            return
        start_sec = min(seg["start"] for seg in valid_segments)
        end_sec = max(seg["end"] for seg in valid_segments)
        start_sec, end_sec, start_ms, end_ms = _normalize_window(
            start_sec,
            end_sec,
            min_duration_sec=self.min_duration_sec,
        )
        window_key = _window_identity(start_ms, end_ms)
        with self._lock:
            existing_item = self._window_items.get(window_key)
        if existing_item is not None:
            append_runtime_event(
                self.ctx.store.run_dir,
                {
                    "event": "clip_work_item_deduplicated",
                    "stage": "build_clip_manifest",
                    "window_id": window_key,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "existing_clip_id": existing_item.get("clip_id"),
                    "existing_status": self._window_states.get(window_key),
                    "reason": reason,
                },
            )
            return
        self.rank += 1
        clip_id = f"clip_{self.rank:03d}"
        expected_name = CLIP_NAMING_POLICY.format(
            rank=self.rank,
            HHhMMmSSs=_format_hhmmss(start_sec),
            start_ms=start_ms,
            end_ms=end_ms,
        )
        item = {
            "clip_id": clip_id,
            "rank": self.rank,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "window_id": window_key,
            "output_video": expected_name,
            "reason": reason,
        }
        with self._lock:
            self._window_items[window_key] = dict(item)
        append_runtime_event(
            self.ctx.store.run_dir,
            {"event": "clip_work_item_queued", "stage": "build_clip_manifest", **item},
        )
        self._enqueue_render_item(item)

    def _enqueue_render_item(self, item: dict[str, Any]) -> None:
        assert self.executor is not None
        window_key = str(item["window_id"])
        with self._lock:
            current_state = self._window_states.get(window_key)
            if current_state in {"queued", "running", "succeeded", "failed"}:
                existing_item = self._window_items.get(window_key, {})
                append_runtime_event(
                    self.ctx.store.run_dir,
                    {
                        "event": "render_enqueue_skipped_duplicate",
                        "stage": "render_clips_batch",
                        "window_id": window_key,
                        "start_ms": item.get("start_ms"),
                        "end_ms": item.get("end_ms"),
                        "clip_id": item.get("clip_id"),
                        "existing_clip_id": existing_item.get("clip_id"),
                        "existing_status": current_state,
                    },
                )
                return
            self._window_states[window_key] = "queued"
        self.futures.append(self.executor.submit(self._render_item, item))

    def _render_item(self, item: dict[str, Any]) -> None:
        assert self.runtime_path is not None
        clip_id = str(item["clip_id"])
        window_key = str(item["window_id"])
        output_path = self.output_dir / str(item["output_video"])
        tmp_output_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
        try:
            with self._lock:
                self._window_states[window_key] = "running"
            update_runtime_item(
                self.runtime_path,
                items_key="clips",
                item_id_key="clip_id",
                item_id=clip_id,
                status="running",
                worker_id="render_pool",
            )
            if output_path.exists() and output_path.stat().st_size > 0:
                pass
            else:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if tmp_output_path.exists():
                    tmp_output_path.unlink()
                cut_video_ffmpeg(
                    str(self.video_path),
                    str(tmp_output_path),
                    float(item["start_sec"]),
                    float(item["end_sec"] - item["start_sec"]),
                )
                if tmp_output_path.exists():
                    os.replace(tmp_output_path, output_path)
            if not output_path.exists():
                raise RuntimeError(f"{clip_id} output missing")
            update_runtime_item(
                self.runtime_path,
                items_key="clips",
                item_id_key="clip_id",
                item_id=clip_id,
                status="succeeded",
                worker_id="render_pool",
                output_video=str(item["output_video"]),
            )
            with self._lock:
                self._window_states[window_key] = "succeeded"
        except Exception as exc:
            update_runtime_item(
                self.runtime_path,
                items_key="clips",
                item_id_key="clip_id",
                item_id=clip_id,
                status="failed",
                worker_id="render_pool",
                error_summary=str(exc),
            )
            with self._lock:
                self._window_states[window_key] = "failed"

    def close(self) -> None:
        self.flush_window(reason="final_window")
        for future in self.futures:
            try:
                future.result()
            except Exception:
                pass
        if self.executor:
            self.executor.shutdown(wait=True)


def run(ctx: ModuleContext) -> Dict[str, Any]:
    audio_payload = ctx.inputs[ART_AUDIO].payload or {}
    if isinstance(audio_payload, dict):
        audio_path = audio_payload.get("path") or audio_payload.get("audio_path")
    else:
        audio_path = str(audio_payload)
    if not audio_path:
        logging.error("[transcribe_audio plugin] audio path missing; payload=%s", audio_payload)
        raise FileNotFoundError("audio path missing")

    work_dir = Path(ctx.store.run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "transcription.json"
    chunk_manifest_path = work_dir / "audio_chunk_manifest.json"
    merged_transcript_path = work_dir / "transcript_merged.json"

    segment_length = int(ctx.params.get("segment_length", 300))
    whisper_engine = str(ctx.params.get("whisper_engine", "auto"))
    hf_whisper_model = str(ctx.params.get("hf_whisper_model", "openai/whisper-medium"))
    requested_workers = max(1, int(ctx.params.get("gpu_asr_pool_max_workers", 1) or 1))
    pool_workers = 1 if requested_workers > 1 else requested_workers
    streaming_enabled = bool(ctx.params.get("streaming_fast_path", True))
    render_workers = max(1, int(ctx.params.get("render_pool_max_workers", 2) or 2))
    stream_window_chunks = max(1, int(ctx.params.get("streaming_window_chunks", 1) or 1))
    min_clip_segment_seconds = float(ctx.params.get("min_clip_segment_seconds", 6.0) or 6.0)
    video_path_for_streaming = ctx.params.get("video_path")
    output_dir_for_streaming = ctx.params.get("output_dir")
    if whisper_engine == "hf-whisper":
        whisper_model = hf_whisper_model
    else:
        whisper_model = str(ctx.params.get("whisper_model", "medium"))
    language = ctx.params.get("language")
    device_hint = str(ctx.params.get("device") or "auto").strip().lower()
    if device_hint == "auto":
        device_hint = "cuda" if pool_workers >= 1 else "cpu"

    audio_duration = 0.0
    if isinstance(audio_payload, dict):
        try:
            audio_duration = float(audio_payload.get("duration_sec") or 0.0)
        except Exception:
            audio_duration = 0.0

    chunk_count = max(1, int(math.ceil(audio_duration / float(segment_length)))) if audio_duration > 0 else 1
    chunk_manifest = {
        "schema_version": "1.0.0",
        "stage": "build_audio_chunk_manifest",
        "audio_path": str(audio_path),
        "segment_length_sec": segment_length,
        "chunk_count": chunk_count,
        "chunks": [],
    }
    for idx in range(chunk_count):
        start_sec = round(idx * float(segment_length), 3)
        end_sec = round(min(audio_duration or start_sec + float(segment_length), start_sec + float(segment_length)), 3)
        chunk_manifest["chunks"].append(
            {
                "chunk_id": f"chunk_{idx:04d}",
                "index": idx,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "status": "planned",
            }
        )

    if ctx.progress:
        ctx.progress("build_audio_chunk_manifest", 0, 1, "start")
    chunk_manifest_path.write_text(json.dumps(chunk_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if ctx.progress:
        ctx.progress("build_audio_chunk_manifest", 1, 1, "done")

    runtime_path = init_transcribe_runtime(
        run_dir=ctx.store.run_dir,
        job_id=ctx.run_id,
        manifest_path=chunk_manifest_path,
        pool="gpu_asr_pool",
        max_workers=pool_workers,
    )
    total_chunks = len(chunk_manifest["chunks"])
    if ctx.progress:
        ctx.progress("transcribe_chunks", 0, total_chunks, f"queued {total_chunks} chunks")

    chunks_dir = work_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_by_index = {int(chunk["index"]): chunk for chunk in chunk_manifest["chunks"]}
    streaming = _StreamingFastPath(
        ctx=ctx,
        work_dir=work_dir,
        video_path=str(video_path_for_streaming) if streaming_enabled and video_path_for_streaming else None,
        output_dir=str(output_dir_for_streaming) if output_dir_for_streaming else None,
        render_workers=render_workers,
        window_chunks=stream_window_chunks,
        min_duration_sec=min_clip_segment_seconds,
    )
    streaming.start()

    def _emit_progress(message: str) -> None:
        if not ctx.progress:
            return
        runtime_payload = read_runtime(runtime_path)
        done = int(runtime_payload.get("completed_chunks", 0) or 0) + int(runtime_payload.get("failed_chunks", 0) or 0)
        ctx.progress("transcribe_chunks", done, total_chunks, message)

    def _mark_cancelled(message: str) -> None:
        current_runtime = read_runtime(runtime_path)
        for item in current_runtime.get("chunks", []):
            if item.get("status") in {"queued", "running"}:
                update_runtime_item(
                    runtime_path,
                    items_key="chunks",
                    item_id_key="chunk_id",
                    item_id=str(item["chunk_id"]),
                    status="cancelled",
                    error_summary=message,
                )
        finalize_runtime(runtime_path, status="cancelled")

    def _reconcile_completed_chunks() -> None:
        current_runtime = read_runtime(runtime_path)
        for item in current_runtime.get("chunks", []):
            chunk_id = str(item.get("chunk_id") or "")
            if not chunk_id:
                continue
            result_path = _chunk_runtime_result_path(chunks_dir, chunk_id)
            if not result_path.exists():
                continue
            update_runtime_item(
                runtime_path,
                items_key="chunks",
                item_id_key="chunk_id",
                item_id=chunk_id,
                status="succeeded",
                worker_id=item.get("worker_id") or "gpu_asr_pool:0",
                result_path=str(result_path),
                segment_count=_read_segment_count(result_path),
            )

    def _mark_failed(message: str) -> None:
        _reconcile_completed_chunks()
        current_runtime = read_runtime(runtime_path)
        stalled_chunk_index = _parse_stalled_chunk_index(message)
        for item in current_runtime.get("chunks", []):
            if item.get("status") != "running":
                continue
            item_index = item.get("index")
            if stalled_chunk_index is not None and item_index == stalled_chunk_index:
                update_runtime_item(
                    runtime_path,
                    items_key="chunks",
                    item_id_key="chunk_id",
                    item_id=str(item["chunk_id"]),
                    status="failed",
                    worker_id=item.get("worker_id") or "gpu_asr_pool:0",
                    error_summary=message,
                )
                continue
            update_runtime_item(
                runtime_path,
                items_key="chunks",
                item_id_key="chunk_id",
                item_id=str(item["chunk_id"]),
                status="queued",
            )
        finalize_runtime(runtime_path, status="failed")

    def _checkpoint_callback(checkpoint: Dict[str, Any]) -> None:
        stage = str(checkpoint.get("stage", "")).strip()
        error_text = str(checkpoint.get("error") or "")
        if stage == "transcribe_error" and "recycle requested" in error_text.lower():
            return
        if stage == "recycle_requested":
            _emit_progress("restarting transcribe worker")
            return
        if stage in {"prepare_audio_done", "model_loaded"}:
            _emit_progress("audio ready" if stage == "prepare_audio_done" else "model loaded")
            return

        chunk_index = 0 if stage.startswith("single_transcribe_") else int(checkpoint.get("chunk_index", 0) or 0)
        chunk = chunk_by_index.get(chunk_index)
        if not chunk:
            return
        chunk_id = str(chunk["chunk_id"])

        if stage in {"chunk_transcribe_start", "single_transcribe_start"}:
            update_runtime_item(
                runtime_path,
                items_key="chunks",
                item_id_key="chunk_id",
                item_id=chunk_id,
                status="running",
                worker_id="gpu_asr_pool:0",
            )
            _emit_progress(f"{chunk_id} started")
            return

        if stage in {"chunk_transcribe_ok", "single_transcribe_ok"}:
            result_path = checkpoint.get("result_path")
            update_runtime_item(
                runtime_path,
                items_key="chunks",
                item_id_key="chunk_id",
                item_id=chunk_id,
                status="succeeded",
                worker_id="gpu_asr_pool:0",
                result_path=str(result_path) if result_path else None,
                segment_count=int(checkpoint.get("segments", 0) or 0),
            )
            streaming.on_chunk_result(chunk_id, str(result_path) if result_path else None)
            _emit_progress(f"{chunk_id} done")
            return

        if stage in {"chunk_transcribe_error", "single_transcribe_error", "transcribe_error"}:
            terminal_status = "cancelled" if "cancel" in str(checkpoint.get("error", "")).lower() else "failed"
            update_runtime_item(
                runtime_path,
                items_key="chunks",
                item_id_key="chunk_id",
                item_id=chunk_id,
                status=terminal_status,
                worker_id="gpu_asr_pool:0" if terminal_status != "cancelled" else None,
                error_summary=str(checkpoint.get("error") or "transcribe error"),
            )
            _emit_progress(f"{chunk_id} {terminal_status}")

    payload = {
        "source_path": str(audio_path),
        "model_size": whisper_model,
        "language": language,
        "device": device_hint,
        "engine": whisper_engine,
        "split_duration": segment_length,
        "output_format": "json",
        "work_dir": str(chunks_dir / "_stage"),
        "transcript_path": str(out_path),
        "chunk_result_dir": str(chunks_dir),
    }

    try:
        transcript = run_transcribe_subprocess_guarded(
            payload,
            Path(payload["work_dir"]),
            checkpoint_callback=_checkpoint_callback,
        )
    except Exception as exc:
        if "cancel" in str(exc).lower():
            _mark_cancelled("Job cancelled")
            raise RuntimeError("transcribe cancelled") from exc
        _mark_failed(str(exc))
        raise
    finally:
        streaming.close()

    all_segments = sorted(
        transcript.get("segments", []),
        key=lambda seg: (float(seg.get("start", 0.0)), float(seg.get("end", 0.0))),
    )
    for idx, chunk in enumerate(chunk_manifest["chunks"]):
        chunk_id = str(chunk["chunk_id"])
        start_sec = float(chunk["start_sec"])
        end_sec = float(chunk["end_sec"])
        chunk_segments = _chunk_segments(
            all_segments,
            start_sec,
            end_sec,
            is_last=idx == len(chunk_manifest["chunks"]) - 1,
        )
        chunk_result_path = _chunk_output_path(chunks_dir, chunk_id)
        if not chunk_result_path.exists():
            chunk_payload = {
                "schema_version": "1.0.0",
                "chunk_id": chunk_id,
                "index": int(chunk["index"]),
                "start_sec": start_sec,
                "end_sec": end_sec,
                "language": transcript.get("language") or language or "auto",
                "engine": transcript.get("engine") or whisper_engine,
                "segments": chunk_segments,
            }
            chunk_result_path.write_text(json.dumps(chunk_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        update_runtime_item(
            runtime_path,
            items_key="chunks",
            item_id_key="chunk_id",
            item_id=chunk_id,
            status="succeeded",
            worker_id="gpu_asr_pool:0",
            result_path=str(chunk_result_path),
            segment_count=len(chunk_segments),
        )

    merged_payload = {
        "schema_version": transcript.get("schema_version", "1.0.0"),
        "stage": "merge_transcript",
        "transcript_path": str(out_path),
        "audio_chunk_manifest_path": str(chunk_manifest_path),
        "chunk_count": len(chunk_manifest["chunks"]),
        "language": transcript.get("language") or language or "auto",
        "segments": all_segments,
    }
    if ctx.progress:
        ctx.progress("merge_transcript", 0, 1, "start")
    merged_transcript_path.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if ctx.progress:
        ctx.progress("merge_transcript", 1, 1, "done")
    finalize_runtime(runtime_path, status="succeeded")

    return {ART_TRANSCRIPT: merged_payload}


spec = ModuleSpec(
    name="transcribe_audio",
    version="1",
    inputs=[ART_AUDIO],
    outputs=[ART_TRANSCRIPT],
    run=run,
    description="Transcribe audio into timestamped text segments (Whisper).",
    impl_path="src/acfv/processing/transcribe_audio.py",
    default_params={
        "segment_length": 120,
        "whisper_model": "medium",
        "whisper_engine": "auto",
        "hf_whisper_model": "openai/whisper-medium",
    },
)

__all__ = ["spec"]
