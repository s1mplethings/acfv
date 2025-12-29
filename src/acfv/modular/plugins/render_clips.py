from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from acfv.modular.contracts import ART_AUDIO_HOST, ART_CLIPS, ART_SEGMENTS, ART_VIDEO
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.processing.clip_video import clip_video


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)


def run(ctx: ModuleContext) -> Dict[str, Any]:
    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path or not os.path.exists(video_path):
        raise FileNotFoundError("video not found")

    segments = ctx.inputs[ART_SEGMENTS].payload or []

    output_dir = ctx.params.get("output_dir")
    if not output_dir:
        output_dir = str(Path(ctx.store.run_dir) / "output_clips")

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    work_dir = Path(ctx.store.run_dir) / "work"
    analysis_path = work_dir / "segments.json"
    _write_json(analysis_path, segments)

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

    if ctx.progress:
        ctx.progress("clip", len(clip_files), max(1, len(segments)), "done")

    return {ART_CLIPS: [str(p) for p in clip_files]}


spec = ModuleSpec(
    name="render_clips",
    version="1",
    inputs=[ART_VIDEO, ART_SEGMENTS, ART_AUDIO_HOST],
    outputs=[ART_CLIPS],
    run=run,
    description="Render highlight clips from video and segments.",
    impl_path="src/acfv/processing/clip_video.py",
    default_params={"output_dir": None},
)

__all__ = ["spec"]
