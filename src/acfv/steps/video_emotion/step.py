from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_VIDEO, ART_VIDEO_EMOTION
from acfv.modular.types import ModuleContext


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def run(ctx: ModuleContext) -> Dict[str, Any]:
    enabled = bool(ctx.params.get("enabled", True))
    if not enabled:
        if ctx.progress:
            ctx.progress("video_emotion", 1, 1, "disabled")
        return {ART_VIDEO_EMOTION: []}

    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path:
        raise FileNotFoundError("video path missing")

    work_dir = Path(ctx.store.run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "video_emotion.json"

    class EmotionArgs:
        def __init__(self, segment_length: float, model_path: str, device: Any) -> None:
            self.segment_length = segment_length
            self.model_path = model_path
            self.device = device

    segment_length = float(ctx.params.get("segment_length", 4.0))
    model_path = str(ctx.params.get("model_path", ""))
    device = ctx.params.get("device", 0)

    if ctx.progress:
        ctx.progress("video_emotion", 0, 1, "start")

    try:
        from acfv.processing.video_emotion_infer import run as infer_emotion
    except Exception:
        if ctx.progress:
            ctx.progress("video_emotion", 1, 1, "unavailable")
        return {ART_VIDEO_EMOTION: []}

    infer_emotion(video_path, str(out_path), EmotionArgs(segment_length, model_path, device))
    payload = _read_json(out_path)

    if ctx.progress:
        ctx.progress("video_emotion", 1, 1, "done")

    return {ART_VIDEO_EMOTION: payload}


__all__ = ["run"]
