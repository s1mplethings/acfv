from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from acfv.modular.contracts import ART_CHAT_LOG, ART_SEGMENTS, ART_TRANSCRIPT, ART_VIDEO_EMOTION
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.processing.analyze_data import analyze_data


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def run(ctx: ModuleContext) -> Dict[str, Any]:
    chat_payload = ctx.inputs[ART_CHAT_LOG].payload or []
    transcript_payload = ctx.inputs[ART_TRANSCRIPT].payload or []

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

    return {ART_SEGMENTS: segments}


spec = ModuleSpec(
    name="analyze_segments",
    version="1",
    inputs=[ART_CHAT_LOG, ART_TRANSCRIPT, ART_VIDEO_EMOTION],
    outputs=[ART_SEGMENTS],
    run=run,
    description="Fuse chat, transcript, and emotion into highlight segments.",
    impl_path="src/acfv/processing/analyze_data.py",
    default_params={"max_clips": None, "video_emotion_weight": 0.3, "enable_video_emotion": False},
)

__all__ = ["spec"]
