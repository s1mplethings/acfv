from __future__ import annotations

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from acfv.modular.contracts import ART_AUDIO_HOST, ART_CLIPS, ART_SEGMENTS, ART_VIDEO
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.processing.clip_video import clip_video
from acfv.selection.merge_segments import merge_segments
from acfv.steps.render_clips.impl import NAMING_POLICY as CLIP_NAMING_POLICY

SCHEMA_VERSION = "1.0.0"
UNITS = "ms"
SORT_POLICY = "score_desc_start_ms_asc_end_ms_asc"

logger = logging.getLogger(__name__)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    tmp.replace(path)


def _normalize_segments(payload: Any) -> List[Dict[str, Any]]:
    """Accept contract segments (ms) or legacy seconds list; return seconds list with optional reason_tags."""
    segments_raw = []
    if isinstance(payload, dict):
        segments_raw = payload.get("segments", [])
    else:
        segments_raw = payload or []

    normalized: List[Dict[str, Any]] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            continue
        if "start_ms" in seg or "end_ms" in seg:
            try:
                start = float(seg.get("start_ms", 0)) / 1000.0
                end = float(seg.get("end_ms", 0)) / 1000.0
            except Exception:
                continue
            score = float(seg.get("score", 0.0) or 0.0)
            rank = seg.get("rank")
        else:
            try:
                start = float(seg.get("start", 0.0))
                end = float(seg.get("end", 0.0))
            except Exception:
                continue
            score = float(seg.get("score", 0.0) or 0.0)
            rank = seg.get("rank")
        if end <= start:
            continue
        reason_tags = seg.get("reason_tags") if isinstance(seg.get("reason_tags"), list) else []
        normalized.append(
            {"start": max(0.0, start), "end": max(0.0, end), "score": score, "rank": rank, "reason_tags": reason_tags}
        )

    normalized.sort(key=lambda s: (s["start"], s["end"]))
    return normalized


def _segments_to_contract(segments_sec: List[Dict[str, Any]]) -> Dict[str, Any]:
    contract_segments: List[Dict[str, Any]] = []
    for rank, seg in enumerate(sorted(segments_sec, key=lambda s: (-s["score"], s["start"], s["end"])), start=1):
        start_ms = int(round(seg["start"] * 1000))
        end_ms = int(round(seg["end"] * 1000))
        if end_ms <= start_ms:
            continue
        item = {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "score": float(seg.get("score", 0.0)),
            "rank": rank,
        }
        if seg.get("reason_tags"):
            item["reason_tags"] = seg["reason_tags"]
        contract_segments.append(item)

    return {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "sort": SORT_POLICY,
        "policy": {
            "min_duration_ms": 6000,
            "max_duration_ms": int(120000),  # aligned with merge max default 120s
            "merge_gap_ms": int(1000 * 1.0),
            "allow_overlap": False,
            "clamp_to_duration": True,
            "max_segments": len(contract_segments),
        },
        "segments": contract_segments,
    }


def _build_manifest(
    run_dir: Path,
    output_dir: Path,
    plan_segments: List[Dict[str, Any]],
    clip_files: List[Path],
    subtitles: List[str],
    thumbnails: List[str],
    source_media: str,
    naming_policy: str,
) -> Dict[str, Any]:
    subtitles_map = {Path(p).stem: Path(p) for p in subtitles}
    thumbs_map = {Path(p).stem: Path(p) for p in thumbnails}
    manifest_clips: List[Dict[str, Any]] = []
    clip_file_map = {p.stem: p for p in clip_files}
    for idx, seg in enumerate(plan_segments, start=1):
        start_ms = int(round(float(seg.get("start", 0.0)) * 1000))
        end_ms = int(round(float(seg.get("end", 0.0)) * 1000))
        duration_ms = max(0, end_ms - start_ms)
        clip_id = f"clip_{idx:03d}"
        expected_name = CLIP_NAMING_POLICY.format(
            rank=idx,
            HHhMMmSSs=_format_hhmmss(seg.get("start", 0.0)),
            start_ms=start_ms,
            end_ms=end_ms,
        )
        stem = Path(expected_name).stem
        clip_path = clip_file_map.get(stem)
        output_obj: Dict[str, Any] = {}
        if clip_path:
            output_obj["video"] = str(clip_path.relative_to(output_dir) if clip_path.is_absolute() else clip_path)
        else:
            # 即便失败也写入预期路径，便于排障
            output_obj["video"] = expected_name
        if stem in subtitles_map:
            output_obj["subtitle"] = str(
                subtitles_map[stem].relative_to(output_dir) if subtitles_map[stem].is_absolute() else subtitles_map[stem]
            )
        if stem in thumbs_map:
            output_obj["thumbnail"] = str(
                thumbs_map[stem].relative_to(output_dir) if thumbs_map[stem].is_absolute() else thumbs_map[stem]
            )
        label_val = seg.get("reason_tags", [None])[0] if seg.get("reason_tags") else None
        clip_entry: Dict[str, Any] = {
            "clip_id": clip_id,
            "rank": idx,
            "score": float(seg.get("score", 0.0)),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": duration_ms,
            "output": output_obj,
            "status": "ok" if clip_path else "failed",
        }
        if label_val:
            clip_entry["label"] = label_val
        if seg.get("reason_tags"):
            clip_entry["meta"] = {"reason_tags": seg.get("reason_tags")}
        manifest_clips.append(clip_entry)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "run_id": run_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_media": source_media,
        "naming_policy": naming_policy,
        "clips": manifest_clips,
    }
    return manifest


def _format_hhmmss(start_sec: float) -> str:
    try:
        total = float(start_sec)
    except Exception:
        total = 0.0
    hh = int(total // 3600)
    mm = int((total % 3600) // 60)
    ss = int(total % 60)
    return f"{hh:02d}h{mm:02d}m{ss:02d}s"


def run(ctx: ModuleContext) -> Dict[str, Any]:
    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path or not os.path.exists(video_path):
        raise FileNotFoundError("video not found")
    logger.info("[render_clips] start | run_dir=%s video=%s", ctx.store.run_dir, video_path)

    segments_payload = ctx.inputs[ART_SEGMENTS].payload or []
    segments_raw = _normalize_segments(segments_payload)
    logger.info("[render_clips] incoming segments=%d", len(segments_raw))

    merge_result = merge_segments(
        {
            "segments": segments_raw,
            "merge_gap_sec": ctx.params.get("merge_gap_sec", 1.0),
            "max_merged_duration": ctx.params.get("max_merged_duration", 120.0),
        }
    )
    merged_segments = merge_result.get("merged_segments", [])
    segments = sorted(merged_segments, key=lambda s: (-s.get("score", 0.0), s.get("start", 0.0), s.get("end", 0.0)))
    logger.info("[render_clips] merged segments=%d gap=%.2f max_dur=%.2f", len(segments), merge_result.get("merge_gap_sec"), merge_result.get("max_merged_duration"))

    output_dir = ctx.params.get("output_dir")
    if not output_dir:
        output_dir = str(Path(ctx.store.run_dir) / "output_clips")

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    work_dir = Path(ctx.store.run_dir) / "work"
    analysis_path = work_dir / "segments.json"
    segments_contract = _segments_to_contract(segments)
    _write_json(analysis_path, segments_contract)
    logger.info("[render_clips] write contract segments -> %s", analysis_path)

    audio_source = None
    audio_env = ctx.inputs.get(ART_AUDIO_HOST)
    if audio_env and isinstance(audio_env.payload, dict):
        audio_source = audio_env.payload.get("path")

    def _progress(current: int, total: int, message: str = "") -> None:
        if ctx.progress:
            ctx.progress("clip", current, total, message or "progress")

    if ctx.progress:
        ctx.progress("clip", 0, max(1, len(segments)), "start")

    clip_files = clip_video(
        video_path=video_path,
        analysis_file=str(analysis_path),
        output_dir=str(output_dir_path),
        progress_callback=_progress,
        audio_source=audio_source,
    )
    clip_paths = [Path(p) for p in clip_files]

    if ctx.progress:
        ctx.progress("clip", len(clip_paths), max(1, len(segments)), "done")

    subtitles: List[str] = []
    for path in output_dir_path.glob("*.srt"):
        subtitles.append(str(path))

    thumbnails: List[str] = []
    for path in output_dir_path.glob("*.jpg"):
        thumbnails.append(str(path))

    plan_segments = segments
    plan_path = output_dir_path / "clip_plan.json"
    if plan_path.exists():
        try:
            with plan_path.open("r", encoding="utf-8") as f:
                plan_payload = json.load(f)
            plan_segments = plan_payload.get("segments", plan_segments)
        except Exception:
            logger.warning("[render_clips] failed to read clip_plan.json, fallback to merged segments")
    if not isinstance(plan_segments, list):
        plan_segments = segments

    manifest = _build_manifest(
        Path(ctx.store.run_dir),
        output_dir_path,
        plan_segments,
        clip_paths,
        subtitles,
        thumbnails,
        source_media=str(video_path),
        naming_policy=CLIP_NAMING_POLICY,
    )
    manifest_path = work_dir / "clips_manifest.json"
    _write_json(manifest_path, manifest)
    # keep a copy next to outputs for convenience
    _write_json(output_dir_path / "clips_manifest.json", manifest)
    logger.info("[render_clips] clips=%d subtitles=%d thumbnails=%d manifest=%s", len(clip_paths), len(subtitles), len(thumbnails), manifest_path)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "clips": [str(p) for p in clip_paths],
        "subtitles": subtitles,
        "thumbnails": thumbnails,
        "log_path": None,
        "merge_gap_sec": merge_result.get("merge_gap_sec"),
        "max_merged_duration": merge_result.get("max_merged_duration"),
        "segments": segments_contract,
        "manifest_path": str(manifest_path),
    }
    return {ART_CLIPS: payload}


spec = ModuleSpec(
    name="render_clips",
    version="1",
    inputs=[ART_VIDEO, ART_SEGMENTS, ART_AUDIO_HOST],
    outputs=[ART_CLIPS],
    run=run,
    description="Render highlight clips from video and segments.",
    impl_path="src/acfv/processing/clip_video.py",
    default_params={"output_dir": None, "merge_gap_sec": 1.0, "max_merged_duration": 120.0},
)

__all__ = ["spec"]
