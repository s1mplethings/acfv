from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from acfv import config as app_config
from acfv.modular.contracts import ART_AUDIO_HOST, ART_CLIPS, ART_SEGMENTS_LLM, ART_SEGMENTS_SEMANTIC, ART_TRANSCRIPT, ART_VIDEO
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.pipeline.runtime import finalize_runtime, init_render_runtime, read_runtime, update_runtime_item
from acfv.selection.merge_segments import merge_segments
from acfv.steps.render_clips.impl import NAMING_POLICY as CLIP_NAMING_POLICY, cut_video_ffmpeg
from acfv.steps.subtitle_generator.impl import generate_semantic_subtitles_for_clips

SCHEMA_VERSION = "1.0.0"
UNITS = "ms"
SORT_POLICY = "score_desc_start_ms_asc_end_ms_asc"

logger = logging.getLogger(__name__)


def _get_min_clip_segment_seconds() -> float:
    cm = getattr(app_config, "config_manager", None)
    try:
        if cm is None:
            return 6.0
        value = cm.get("MIN_CLIP_SEGMENT_SECONDS", None)
        if value is None:
            value = cm.get("MIN_INTEREST_SEGMENT_DURATION", None)
        if value is None:
            return 6.0
        return float(value)
    except (TypeError, ValueError):
        return 6.0


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _resolve_subtitle_settings(ctx: ModuleContext) -> tuple[bool, str]:
    enabled = ctx.params.get("subtitle_enabled")
    fmt = ctx.params.get("subtitle_format")
    if enabled is None:
        cm = getattr(app_config, "config_manager", None)
        enable_enhance = bool(cm.get("ENABLE_ENHANCE", False)) if cm else False
        enable_asr = bool(cm.get("ENHANCE_ASR", True)) if cm else False
        enabled = enable_enhance and enable_asr
    if not fmt:
        fmt = "srt"
    return bool(enabled), str(fmt)


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
        item = {
            "start": max(0.0, start),
            "end": max(0.0, end),
            "score": score,
            "rank": rank,
            "reason_tags": reason_tags,
        }
        if seg.get("summary"):
            item["text"] = str(seg.get("summary"))
        elif seg.get("text"):
            item["text"] = str(seg.get("text"))
        if seg.get("highlight_type") is not None:
            item["highlight_type"] = str(seg.get("highlight_type"))
        if seg.get("why_highlight") is not None:
            item["why_highlight"] = str(seg.get("why_highlight"))
        if seg.get("confidence") is not None:
            item["confidence"] = float(seg.get("confidence"))
        if seg.get("score_base") is not None:
            item["score_base"] = float(seg.get("score_base"))
        if seg.get("score_scale") is not None:
            item["score_scale"] = float(seg.get("score_scale"))
        if seg.get("overlap_count") is not None:
            try:
                item["overlap_count"] = int(seg.get("overlap_count"))
            except Exception:
                item["overlap_count"] = seg.get("overlap_count")
        normalized.append(item)

    normalized.sort(key=lambda s: (s["start"], s["end"]))
    return normalized


def _segments_to_contract(
    segments_sec: List[Dict[str, Any]],
    policy_override: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    min_duration_sec = _get_min_clip_segment_seconds()
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

    policy = {
        "min_duration_ms": int(min_duration_sec * 1000),
        "max_duration_ms": int(120000),  # aligned with merge max default 120s
        "merge_gap_ms": int(1000 * 1.0),
        "allow_overlap": False,
        "clamp_to_duration": True,
        "max_segments": len(contract_segments),
    }
    if policy_override:
        for key in (
            "target_duration_ms",
            "min_duration_ms",
            "max_duration_ms",
            "similarity_threshold",
            "max_gap_ms",
        ):
            if key in policy_override:
                policy[key] = policy_override[key]

    return {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "sort": SORT_POLICY,
        "policy": policy,
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
    planned: bool = False,
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
        if planned:
            output_obj["video"] = expected_name
        elif clip_path:
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
            "status": "planned" if planned else ("ok" if clip_path else "failed"),
        }
        if label_val:
            clip_entry["label"] = label_val
        if seg.get("reason_tags"):
            clip_entry["meta"] = {"reason_tags": seg.get("reason_tags")}
        manifest_clips.append(clip_entry)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "stage": "build_clip_manifest",
        "units": UNITS,
        "run_id": run_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_media": source_media,
        "selected_segments_path": str(run_dir / "work" / "selected_segments.json"),
        "naming_policy": naming_policy,
        "clip_count": len(manifest_clips),
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

    llm_env = ctx.inputs.get(ART_SEGMENTS_LLM)
    segments_payload = llm_env.payload if llm_env is not None else []
    if not segments_payload:
        fallback_env = ctx.store.get_latest_by_type(ART_SEGMENTS_SEMANTIC)
        if fallback_env is not None:
            segments_payload = fallback_env.payload or []
    segments_raw = _normalize_segments(segments_payload)
    policy_in = segments_payload.get("policy") if isinstance(segments_payload, dict) else None
    logger.info("[render_clips] incoming segments=%d", len(segments_raw))
    for idx, seg in enumerate(segments_raw, 1):
        logger.info(
            "[render_clips] seg#%03d %.2fs-%.2fs score=%.4f tags=%s",
            idx,
            seg.get("start", 0.0),
            seg.get("end", 0.0),
            float(seg.get("score", 0.0)),
            ",".join(seg.get("reason_tags", [])) if seg.get("reason_tags") else "-",
        )

    semantic_mode = bool(isinstance(policy_in, dict) and policy_in.get("target_duration_ms") is not None)
    merge_result = {
        "merge_gap_sec": ctx.params.get("merge_gap_sec", 1.0),
        "max_merged_duration": ctx.params.get("max_merged_duration", 120.0),
    }
    if semantic_mode:
        segments = sorted(segments_raw, key=lambda s: (s.get("start", 0.0), s.get("end", 0.0)))
        logger.info("[render_clips] semantic segments=%d (skip merge)", len(segments))
    else:
        merge_result = merge_segments(
            {
                "segments": segments_raw,
                "merge_gap_sec": ctx.params.get("merge_gap_sec", 1.0),
                "max_merged_duration": ctx.params.get("max_merged_duration", 120.0),
            }
        )
        merged_segments = merge_result.get("merged_segments", [])
        segments = sorted(merged_segments, key=lambda s: (-s.get("score", 0.0), s.get("start", 0.0), s.get("end", 0.0)))
        logger.info(
            "[render_clips] merged segments=%d gap=%.2f max_dur=%.2f",
            len(segments),
            merge_result.get("merge_gap_sec"),
            merge_result.get("max_merged_duration"),
        )
        for idx, seg in enumerate(segments, 1):
            logger.info(
                "[render_clips] merged#%03d %.2fs-%.2fs score=%.4f tags=%s",
                idx,
                seg.get("start", 0.0),
                seg.get("end", 0.0),
                float(seg.get("score", 0.0)),
                ",".join(seg.get("reason_tags", [])) if seg.get("reason_tags") else "-",
            )

    output_dir = ctx.params.get("output_dir")
    if not output_dir:
        output_dir = str(Path(ctx.store.run_dir))

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    work_dir = Path(ctx.store.run_dir) / "work"
    analysis_path = work_dir / "segments.json"
    selected_segments_path = work_dir / "selected_segments.json"
    clip_manifest_plan_path = work_dir / "clip_manifest.json"
    export_summary_path = work_dir / "export_results.json"

    audio_source = None
    audio_env = ctx.inputs.get(ART_AUDIO_HOST)
    if audio_env and isinstance(audio_env.payload, dict):
        audio_source = audio_env.payload.get("path")

    def _progress(current: int, total: int, message: str = "") -> None:
        if ctx.progress:
            ctx.progress("render_clips_batch", current, total, message or "progress")

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
    plan_segments = sorted(plan_segments, key=lambda s: (-float(s.get("score", 0.0)), float(s.get("start", 0.0)), float(s.get("end", 0.0))))

    segments_contract = _segments_to_contract(plan_segments, policy_override=policy_in)
    if ctx.progress:
        ctx.progress("select_segments", 0, 1, "start")
    _write_json(selected_segments_path, segments_contract)
    if ctx.progress:
        ctx.progress("select_segments", 1, 1, "done")
    _write_json(analysis_path, segments_contract)
    logger.info("[render_clips] write contract segments -> %s", analysis_path)

    planned_manifest = _build_manifest(
        Path(ctx.store.run_dir),
        output_dir_path,
        plan_segments,
        [],
        [],
        [],
        source_media=str(video_path),
        naming_policy=CLIP_NAMING_POLICY,
        planned=True,
    )
    if ctx.progress:
        ctx.progress("build_clip_manifest", 0, 1, "start")
    _write_json(clip_manifest_plan_path, planned_manifest)
    if ctx.progress:
        ctx.progress("build_clip_manifest", 1, 1, "done")
    runtime_path = init_render_runtime(
        run_dir=ctx.store.run_dir,
        job_id=ctx.run_id,
        manifest_path=clip_manifest_plan_path,
        pool="render_pool",
        max_workers=max(1, int(ctx.params.get("render_pool_max_workers", 2) or 2)),
    )
    render_workers = max(1, int(ctx.params.get("render_pool_max_workers", 2) or 2))
    if ctx.progress:
        ctx.progress("render_clips_batch", 0, max(1, len(segments)), "start")

    def _emit_render_progress(message: str) -> None:
        if not ctx.progress:
            return
        runtime_payload = read_runtime(runtime_path)
        done = int(runtime_payload.get("completed_clips", 0) or 0) + int(runtime_payload.get("failed_clips", 0) or 0)
        ctx.progress("render_clips_batch", done, len(planned_manifest.get("clips", [])), message)

    segment_by_clip_id = {
        str(clip["clip_id"]): plan_segments[idx]
        for idx, clip in enumerate(planned_manifest.get("clips", []))
    }

    def _render_single_clip(clip_item: Dict[str, Any]) -> str:
        clip_id = str(clip_item["clip_id"])
        segment = segment_by_clip_id[clip_id]
        relative_output = str(clip_item.get("output", {}).get("video") or "")
        output_path = output_dir_path / relative_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_output_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
        for stale in (output_path, tmp_output_path):
            if stale.exists():
                stale.unlink()
        update_runtime_item(
            runtime_path,
            items_key="clips",
            item_id_key="clip_id",
            item_id=clip_id,
            status="running",
            worker_id="render_pool",
        )
        _emit_render_progress(f"{clip_id} started")
        cut_video_ffmpeg(str(video_path), str(tmp_output_path), float(segment["start"]), float(segment["end"] - segment["start"]))
        if tmp_output_path.exists():
            os.replace(tmp_output_path, output_path)
        if not output_path.exists():
            raise RuntimeError(f"{clip_id} output missing")
        update_runtime_item(
            runtime_path,
            items_key="clips",
            item_id_key="clip_id",
            item_id=clip_id,
            status="succeeded",
            worker_id="render_pool",
            output_video=relative_output,
        )
        _emit_render_progress(f"{clip_id} done")
        return str(output_path)

    clip_results: dict[str, Path] = {}
    clip_failures: list[str] = []
    cancelled = False
    with ThreadPoolExecutor(max_workers=render_workers, thread_name_prefix="render_pool") as executor:
        future_to_clip = {
            executor.submit(_render_single_clip, clip_item): clip_item
            for clip_item in planned_manifest.get("clips", [])
        }
        for future in as_completed(future_to_clip):
            clip_item = future_to_clip[future]
            clip_id = str(clip_item["clip_id"])
            try:
                clip_results[clip_id] = Path(future.result())
            except Exception as exc:
                terminal_status = "cancelled" if "cancel" in str(exc).lower() else "failed"
                update_runtime_item(
                    runtime_path,
                    items_key="clips",
                    item_id_key="clip_id",
                    item_id=clip_id,
                    status=terminal_status,
                    error_summary=str(exc),
                )
                _emit_render_progress(f"{clip_id} {terminal_status}")
                if terminal_status == "cancelled":
                    cancelled = True
                    for pending_future in future_to_clip:
                        if pending_future is not future:
                            pending_future.cancel()
                    break
                else:
                    clip_failures.append(f"{clip_id}: {exc}")

    if cancelled:
        for clip_item in planned_manifest.get("clips", []):
            current_state = read_runtime(runtime_path).get("clips", [])
            current = next((item for item in current_state if item.get("clip_id") == clip_item["clip_id"]), None)
            if current and current.get("status") not in {"succeeded", "failed", "cancelled"}:
                update_runtime_item(
                    runtime_path,
                    items_key="clips",
                    item_id_key="clip_id",
                    item_id=str(clip_item["clip_id"]),
                    status="cancelled",
                    error_summary="Job cancelled",
                )
        finalize_runtime(runtime_path, status="cancelled")
        raise RuntimeError("render cancelled")

    if clip_failures:
        finalize_runtime(runtime_path, status="failed")
        raise RuntimeError("; ".join(clip_failures))

    clip_paths = [
        clip_results[str(clip["clip_id"])]
        for clip in planned_manifest.get("clips", [])
        if str(clip["clip_id"]) in clip_results
    ]

    subtitle_enabled, subtitle_format = _resolve_subtitle_settings(ctx)
    if subtitle_enabled:
        transcript_path = Path(ctx.store.run_dir) / "work" / "transcription.json"
        if transcript_path.exists() and clip_paths:
            written = generate_semantic_subtitles_for_clips(
                output_clips_dir=str(output_dir_path),
                transcription_file=str(transcript_path),
                cfg_manager=getattr(app_config, "config_manager", None),
                clip_paths=[str(p) for p in clip_paths],
                fmt=subtitle_format,
            )
            logger.info("[render_clips] subtitles generated=%d format=%s", written, subtitle_format)
        else:
            logger.warning(
                "[render_clips] subtitles skipped (transcription=%s clips=%d)",
                transcript_path if transcript_path.exists() else None,
                len(clip_paths),
            )

    if ctx.progress:
        ctx.progress("render_clips_batch", len(clip_paths), max(1, len(segments)), "done")

    subtitles: List[str] = []
    for path in output_dir_path.glob("*.srt"):
        subtitles.append(str(path))

    thumbnails: List[str] = []
    for path in output_dir_path.glob("*.jpg"):
        thumbnails.append(str(path))

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
    for clip in manifest.get("clips", []):
        update_runtime_item(
            runtime_path,
            items_key="clips",
            item_id_key="clip_id",
            item_id=str(clip["clip_id"]),
            status="succeeded" if clip.get("status") == "ok" else "failed",
            worker_id="render_pool" if clip.get("status") == "ok" else None,
            output_video=str(clip.get("output", {}).get("video") or ""),
            subtitle_path=clip.get("output", {}).get("subtitle"),
            thumbnail_path=clip.get("output", {}).get("thumbnail"),
            error_summary=None if clip.get("status") == "ok" else "clip output missing",
        )
    manifest_path = work_dir / "clips_manifest.json"
    if ctx.progress:
        ctx.progress("export_results", 0, 1, "start")
    _write_json(manifest_path, manifest)
    # keep a copy next to outputs for convenience
    _write_json(output_dir_path / "clips_manifest.json", manifest)
    export_summary = {
        "schema_version": SCHEMA_VERSION,
        "stage": "export_results",
        "run_id": Path(ctx.store.run_dir).name,
        "clip_count": len(clip_paths),
        "planned_clip_count": len(manifest.get("clips", [])),
        "selected_segment_count": len(segments_contract.get("segments", [])),
        "subtitle_count": len(subtitles),
        "thumbnail_count": len(thumbnails),
        "clips_manifest_path": str(manifest_path),
        "artifact_refs": {
            "stage_plan": str(work_dir / "stage_plan.json"),
            "audio_chunk_manifest": str(work_dir / "audio_chunk_manifest.json"),
            "transcript_merged": str(work_dir / "transcript_merged.json"),
            "selected_segments": str(selected_segments_path),
            "clip_manifest": str(clip_manifest_plan_path),
        },
    }
    _write_json(export_summary_path, export_summary)
    if ctx.progress:
        ctx.progress("export_results", 1, 1, "done")
    finalize_runtime(runtime_path, status="succeeded")
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
    inputs=[ART_VIDEO, ART_SEGMENTS_LLM, ART_AUDIO_HOST, ART_TRANSCRIPT],
    outputs=[ART_CLIPS],
    run=run,
    description="Render highlight clips from video and segments.",
    impl_path="src/acfv/processing/clip_video.py",
    default_params={
        "output_dir": None,
        "merge_gap_sec": 1.0,
        "max_merged_duration": 120.0,
        "subtitle_enabled": None,
        "subtitle_format": "srt",
    },
)

__all__ = ["spec"]
