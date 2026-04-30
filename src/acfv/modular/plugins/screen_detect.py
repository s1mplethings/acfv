from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from acfv import config as app_config
from acfv.modular.contracts import ART_SCREEN_FRAMES, ART_SCREEN_WINDOWS, ART_VIDEO
from acfv.modular.types import ModuleContext, ModuleSpec
from acfv.steps.screen_detect.impl import run_screen_detect


def run(ctx: ModuleContext) -> Dict[str, Any]:
    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path:
        empty = {"schema_version": "1.0.0", "status": "missing_video", "frames": [], "windows": []}
        return {
            ART_SCREEN_FRAMES: {"schema_version": "1.0.0", "frames": []},
            ART_SCREEN_WINDOWS: empty,
        }

    work_dir = Path(ctx.store.run_dir) / "work"
    payload = run_screen_detect(
        video_path=video_path,
        work_dir=work_dir,
        config_manager=getattr(app_config, "config_manager", None),
        enabled=ctx.params.get("enabled"),
        interval_sec=ctx.params.get("interval_sec"),
        max_frames_per_window=ctx.params.get("max_frames_per_window"),
        enable_ocr=ctx.params.get("enable_ocr"),
        scene_provider=ctx.params.get("scene_provider"),
        ocr_provider=ctx.params.get("ocr_provider"),
        dedupe_hash_distance=ctx.params.get("dedupe_hash_distance"),
        progress_callback=ctx.progress,
    )
    return {
        ART_SCREEN_FRAMES: {
            "schema_version": payload.get("schema_version", "1.0.0"),
            "status": payload.get("status", "ok"),
            "frames": payload.get("frames", []),
        },
        ART_SCREEN_WINDOWS: payload,
    }


spec = ModuleSpec(
    name="screen_detect",
    version="1",
    inputs=[ART_VIDEO],
    outputs=[ART_SCREEN_FRAMES, ART_SCREEN_WINDOWS],
    run=run,
    description="Mechanical screen region detection and sparse keyframe extraction without LLM.",
    impl_path="src/acfv/steps/screen_detect/impl.py",
    default_params={
        "enabled": False,
        "interval_sec": 30.0,
        "max_frames_per_window": 12,
        "enable_ocr": True,
        "scene_provider": "pyscenedetect",
        "ocr_provider": "rapidvideocr",
        "dedupe_hash_distance": 6,
    },
)

__all__ = ["spec"]
