from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_AUDIO, ART_TRANSCRIPT
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.pipeline.runtime import finalize_runtime, init_transcribe_runtime, read_runtime, update_runtime_item
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
    if whisper_engine == "hf-whisper":
        whisper_model = hf_whisper_model
    else:
        whisper_model = str(ctx.params.get("whisper_model", "medium"))
    language = ctx.params.get("language")

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

    def _mark_failed(message: str) -> None:
        current_runtime = read_runtime(runtime_path)
        running_items = [item for item in current_runtime.get("chunks", []) if item.get("status") == "running"]
        if running_items:
            for item in running_items:
                update_runtime_item(
                    runtime_path,
                    items_key="chunks",
                    item_id_key="chunk_id",
                    item_id=str(item["chunk_id"]),
                    status="failed",
                    worker_id=item.get("worker_id") or "gpu_asr_pool:0",
                    error_summary=message,
                )
        finalize_runtime(runtime_path, status="failed")

    def _checkpoint_callback(checkpoint: Dict[str, Any]) -> None:
        stage = str(checkpoint.get("stage", "")).strip()
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
            update_runtime_item(
                runtime_path,
                items_key="chunks",
                item_id_key="chunk_id",
                item_id=chunk_id,
                status="succeeded",
                worker_id="gpu_asr_pool:0",
                segment_count=int(checkpoint.get("segments", 0) or 0),
            )
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
        "device": "cuda" if pool_workers >= 1 else "cpu",
        "engine": whisper_engine,
        "split_duration": segment_length,
        "output_format": "json",
        "work_dir": str(chunks_dir / "_stage"),
        "transcript_path": str(out_path),
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
        "segment_length": 300,
        "whisper_model": "large-v3-turbo",
        "whisper_engine": "auto",
        "hf_whisper_model": "openai/whisper-medium",
    },
)

__all__ = ["spec"]
