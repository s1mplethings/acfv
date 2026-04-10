from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .stages import stage_names

CONTRACT_ARTIFACT_FILES: Dict[str, str] = {
    "stage_plan": "stage_plan.json",
    "audio_chunk_manifest": "audio_chunk_manifest.json",
    "transcript_merged": "transcript_merged.json",
    "selected_segments": "selected_segments.json",
    "clip_manifest": "clip_manifest.json",
    "export_results": "export_results.json",
}


def resolve_contract_paths(run_dir: Path | str) -> Dict[str, Path]:
    work_dir = Path(run_dir).resolve() / "work"
    return {name: work_dir / filename for name, filename in CONTRACT_ARTIFACT_FILES.items()}


def load_contract_artifacts(run_dir: Path | str) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for name, path in resolve_contract_paths(run_dir).items():
        payloads[name] = json.loads(path.read_text(encoding="utf-8"))
    return payloads


def validate_contract_artifacts(run_dir: Path | str) -> list[str]:
    run_dir_path = Path(run_dir).resolve()
    paths = resolve_contract_paths(run_dir_path)
    errors: list[str] = []

    for name, path in paths.items():
        if not path.exists():
            errors.append(f"missing {name}: {path}")
    if errors:
        return errors

    artifacts = load_contract_artifacts(run_dir_path)
    expected_stage_names = stage_names()

    stage_plan = artifacts["stage_plan"]
    if stage_plan.get("pipeline") != "clip":
        errors.append("stage_plan.pipeline must be 'clip'")
    actual_stage_names = [stage.get("name") for stage in stage_plan.get("stages", []) if isinstance(stage, dict)]
    if actual_stage_names != expected_stage_names:
        errors.append(f"stage_plan.stages mismatch: {actual_stage_names!r}")

    audio_chunk_manifest = artifacts["audio_chunk_manifest"]
    chunks = audio_chunk_manifest.get("chunks")
    if audio_chunk_manifest.get("stage") != "build_audio_chunk_manifest":
        errors.append("audio_chunk_manifest.stage must be 'build_audio_chunk_manifest'")
    if not isinstance(chunks, list) or not chunks:
        errors.append("audio_chunk_manifest.chunks must be a non-empty list")
        chunks = []
    if audio_chunk_manifest.get("chunk_count") != len(chunks):
        errors.append("audio_chunk_manifest.chunk_count must equal len(chunks)")
    previous_end = None
    for idx, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            errors.append(f"audio_chunk_manifest.chunks[{idx}] must be an object")
            continue
        for field in ("chunk_id", "index", "start_sec", "end_sec", "status"):
            if field not in chunk:
                errors.append(f"audio_chunk_manifest.chunks[{idx}] missing {field}")
        for field in ("attempt", "worker_id", "started_at", "finished_at", "error_summary"):
            if field in chunk:
                errors.append(f"audio_chunk_manifest.chunks[{idx}] must not include runtime field {field}")
        if chunk.get("index") != idx:
            errors.append(f"audio_chunk_manifest.chunks[{idx}].index must equal {idx}")
        try:
            start_sec = float(chunk.get("start_sec", 0.0))
            end_sec = float(chunk.get("end_sec", 0.0))
            if end_sec < start_sec:
                errors.append(f"audio_chunk_manifest.chunks[{idx}] end_sec < start_sec")
            if previous_end is not None and start_sec < previous_end:
                errors.append(f"audio_chunk_manifest.chunks[{idx}] start_sec is not monotonic")
            previous_end = end_sec
        except Exception:
            errors.append(f"audio_chunk_manifest.chunks[{idx}] invalid start_sec/end_sec")

    transcript_merged = artifacts["transcript_merged"]
    if transcript_merged.get("stage") != "merge_transcript":
        errors.append("transcript_merged.stage must be 'merge_transcript'")
    if transcript_merged.get("chunk_count") != len(chunks):
        errors.append("transcript_merged.chunk_count must equal audio_chunk_manifest.chunk_count")
    transcript_manifest_path = _resolve_declared_path(
        run_dir_path,
        transcript_merged.get("audio_chunk_manifest_path") or transcript_merged.get("audio_chunk_manifest"),
    )
    if transcript_manifest_path != paths["audio_chunk_manifest"]:
        errors.append("transcript_merged.audio_chunk_manifest_path must point to audio_chunk_manifest.json")
    if not isinstance(transcript_merged.get("segments"), list):
        errors.append("transcript_merged.segments must be a list")

    selected_segments = artifacts["selected_segments"]
    if selected_segments.get("units") != "ms":
        errors.append("selected_segments.units must be 'ms'")
    selected_list = selected_segments.get("segments")
    if not isinstance(selected_list, list):
        errors.append("selected_segments.segments must be a list")
        selected_list = []

    clip_manifest = artifacts["clip_manifest"]
    if clip_manifest.get("stage") != "build_clip_manifest":
        errors.append("clip_manifest.stage must be 'build_clip_manifest'")
    if clip_manifest.get("clip_count") != len(clip_manifest.get("clips", [])):
        errors.append("clip_manifest.clip_count must equal len(clips)")
    clip_selected_path = _resolve_declared_path(run_dir_path, clip_manifest.get("selected_segments_path"))
    if clip_selected_path != paths["selected_segments"]:
        errors.append("clip_manifest.selected_segments_path must point to selected_segments.json")
    clips = clip_manifest.get("clips")
    if not isinstance(clips, list):
        errors.append("clip_manifest.clips must be a list")
        clips = []
    for idx, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            errors.append(f"clip_manifest.clips[{idx - 1}] must be an object")
            continue
        if clip.get("rank") != idx:
            errors.append(f"clip_manifest.clips[{idx - 1}].rank must equal {idx}")
        for field in ("clip_id", "start_ms", "end_ms", "duration_ms", "status", "output"):
            if field not in clip:
                errors.append(f"clip_manifest.clips[{idx - 1}] missing {field}")
        for field in ("attempt", "worker_id", "started_at", "finished_at", "error_summary"):
            if field in clip:
                errors.append(f"clip_manifest.clips[{idx - 1}] must not include runtime field {field}")
        output = clip.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("video"), str):
            errors.append(f"clip_manifest.clips[{idx - 1}].output.video must be a string")
    if len(selected_list) != len(clips):
        errors.append("selected_segments.segments and clip_manifest.clips must have the same length in Phase 2")
    for idx, (segment, clip) in enumerate(zip(selected_list, clips)):
        if segment.get("start_ms") != clip.get("start_ms") or segment.get("end_ms") != clip.get("end_ms"):
            errors.append(f"selected_segments[{idx}] must align with clip_manifest.clips[{idx}]")

    export_results = artifacts["export_results"]
    if export_results.get("stage") != "export_results":
        errors.append("export_results.stage must be 'export_results'")
    if export_results.get("selected_segment_count") != len(selected_list):
        errors.append("export_results.selected_segment_count must equal len(selected_segments.segments)")
    if export_results.get("planned_clip_count") != len(clips):
        errors.append("export_results.planned_clip_count must equal len(clip_manifest.clips)")
    if not isinstance(export_results.get("clip_count"), int):
        errors.append("export_results.clip_count must be an int")
    artifact_refs = export_results.get("artifact_refs")
    if not isinstance(artifact_refs, dict):
        errors.append("export_results.artifact_refs must be an object")
        artifact_refs = {}
    expected_refs = {
        "stage_plan": paths["stage_plan"],
        "audio_chunk_manifest": paths["audio_chunk_manifest"],
        "transcript_merged": paths["transcript_merged"],
        "selected_segments": paths["selected_segments"],
        "clip_manifest": paths["clip_manifest"],
    }
    for ref_name, expected_path in expected_refs.items():
        resolved = _resolve_declared_path(run_dir_path, artifact_refs.get(ref_name))
        if resolved != expected_path:
            errors.append(f"export_results.artifact_refs.{ref_name} must point to {expected_path.name}")
    clips_manifest_path = _resolve_declared_path(run_dir_path, export_results.get("clips_manifest_path"))
    if clips_manifest_path != run_dir_path / "work" / "clips_manifest.json":
        errors.append("export_results.clips_manifest_path must point to work/clips_manifest.json")

    return errors


def _resolve_declared_path(run_dir: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    cwd_relative = path.resolve()
    if cwd_relative.exists():
        return cwd_relative
    return (run_dir / path).resolve()


__all__ = [
    "CONTRACT_ARTIFACT_FILES",
    "load_contract_artifacts",
    "resolve_contract_paths",
    "validate_contract_artifacts",
]
