from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from acfv.modular.contracts import ART_CHAT_LOG, ART_SEGMENTS, ART_TRANSCRIPT, ART_VIDEO_EMOTION
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.processing.analyze_data import analyze_data

SCHEMA_VERSION = "1.0.0"
UNITS = "ms"
SORT_POLICY = "score_desc_start_ms_asc_end_ms_asc"
MIN_DURATION_SEC_DEFAULT = 6.0
MUSIC_TAGS = {"music", "song", "instrumental", "bgm"}

logger = logging.getLogger(__name__)


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
        return []


def _normalize_segments(raw: Any, min_duration_sec: float) -> list[dict]:
    """Normalize raw segments to a list of dicts with float seconds and score; drop too-short/music-only windows."""
    segments: list[dict] = []
    if not isinstance(raw, list):
        return segments
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg.get("start") or seg.get("start_sec") or 0.0)
            end = float(seg.get("end") or seg.get("end_sec") or 0.0)
        except Exception:
            continue
        if end <= start:
            continue
        score_val = seg.get("score", seg.get("interest_score", seg.get("rating", 0.0)))
        try:
            score = float(score_val or 0.0)
        except Exception:
            score = 0.0
        text_val = (seg.get("text") or seg.get("utterance") or "").strip()
        reason_tags_raw = seg.get("reason_tags") if isinstance(seg.get("reason_tags"), list) else []
        reason_tags = [str(tag) for tag in reason_tags_raw]
        if (end - start) < min_duration_sec:
            logger.info("drop segment (too short): start=%.3f end=%.3f dur=%.3f", start, end, end - start)
            continue
        if not text_val or any(tag.lower() in MUSIC_TAGS for tag in reason_tags):
            logger.info("drop segment (music/no speech): start=%.3f end=%.3f tags=%s", start, end, reason_tags)
            continue
        segments.append(
            {
                "start": max(0.0, start),
                "end": max(0.0, end),
                "score": score,
                "reason_tags": [str(tag) for tag in reason_tags],
            }
        )
    segments.sort(key=lambda s: (-s["score"], s["start"], s["end"]))
    return segments


def _to_contract_segments(segments_sec: list[dict]) -> dict:
    """Convert seconds-based segments to contract schema (ms, ranked)."""
    contract_segments: list[dict] = []
    for rank, seg in enumerate(segments_sec, start=1):
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
            "min_duration_ms": int(MIN_DURATION_SEC_DEFAULT * 1000),
            "max_duration_ms": 60000,
            "merge_gap_ms": 800,
            "allow_overlap": False,
            "clamp_to_duration": True,
            "max_segments": len(contract_segments),
        },
        "segments": contract_segments,
    }


def run(ctx: ModuleContext) -> Dict[str, Any]:
    logger.info(
        "[analyze_segments] start | run_dir=%s min_duration_sec=%.1f",
        ctx.store.run_dir,
        float(ctx.params.get("min_duration_sec", MIN_DURATION_SEC_DEFAULT) or MIN_DURATION_SEC_DEFAULT),
    )
    chat_payload_raw = ctx.inputs[ART_CHAT_LOG].payload or []
    if isinstance(chat_payload_raw, dict):
        chat_payload = chat_payload_raw.get("records", []) or chat_payload_raw.get("messages", [])
    else:
        chat_payload = chat_payload_raw
    transcript_payload = ctx.inputs[ART_TRANSCRIPT].payload or []
    if isinstance(transcript_payload, dict):
        transcript_payload = transcript_payload.get("segments", [])

    work_dir = Path(ctx.store.run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    chat_path = work_dir / "chat.json"
    transcript_path = work_dir / "transcription.json"
    out_path = work_dir / "segments.json"

    _write_json(chat_path, chat_payload)
    _write_json(transcript_path, transcript_payload)

    video_emotion_path = None
    video_emotion_payload = ctx.inputs[ART_VIDEO_EMOTION].payload if ART_VIDEO_EMOTION in ctx.inputs else None
    if video_emotion_payload:
        video_emotion_path = work_dir / "video_emotion.json"
        _write_json(video_emotion_path, video_emotion_payload)

    max_clips = ctx.params.get("max_clips")
    video_emotion_weight = float(ctx.params.get("video_emotion_weight", 0.3))
    enable_video_emotion = bool(ctx.params.get("enable_video_emotion", False))

    def _progress(stage: str, current: int, total: int, message: str = "") -> None:
        if ctx.progress:
            detail = message or stage
            ctx.progress("analysis", current, total, detail)

    if ctx.progress:
        ctx.progress("analysis", 0, 1, "start")

    result = analyze_data(
        str(chat_path),
        str(transcript_path),
        str(out_path),
        video_emotion_file=str(video_emotion_path) if video_emotion_path else None,
        video_emotion_weight=video_emotion_weight,
        top_n=max_clips,
        enable_video_emotion=enable_video_emotion,
        progress_callback=_progress,
    )

    segments = result or _read_json(out_path)
    if ctx.progress:
        ctx.progress("analysis", 1, 1, "done")

    if isinstance(segments, dict):
        segments = segments.get("segments", [])
    if not isinstance(segments, list):
        segments = []

    min_duration_sec = float(ctx.params.get("min_duration_sec", MIN_DURATION_SEC_DEFAULT) or MIN_DURATION_SEC_DEFAULT)
    segments_sec = _normalize_segments(segments, min_duration_sec=min_duration_sec)
    logger.info("[analyze_segments] segments after filter: %d", len(segments_sec))
    contract_segments = _to_contract_segments(segments_sec)
    _write_json(out_path, contract_segments)
    logger.info("[analyze_segments] write contract segments -> %s", out_path)

    return {ART_SEGMENTS: contract_segments}


spec = ModuleSpec(
    name="analyze_segments",
    version="1",
    inputs=[ART_CHAT_LOG, ART_TRANSCRIPT, ART_VIDEO_EMOTION],
    outputs=[ART_SEGMENTS],
    run=run,
    description="Fuse chat, transcript, and emotion into highlight segments.",
    impl_path="src/acfv/processing/analyze_data.py",
    default_params={
        "max_clips": None,
        "video_emotion_weight": 0.3,
        "enable_video_emotion": False,
        "min_duration_sec": MIN_DURATION_SEC_DEFAULT,
    },
)

__all__ = ["spec"]
