from __future__ import annotations

from typing import Any, Dict, List

from acfv.modular.types import ModuleContext, ModuleSpec

VIDEO_TYPE = "VideoSource:local.v1"
SEGMENTS_TYPE = "Segments:unified.v1"
OUT_TYPE = "Clips:index.v1"


def run(ctx: ModuleContext) -> Dict[str, Any]:
    video = ctx.inputs[VIDEO_TYPE].payload or {}
    segments = ctx.inputs[SEGMENTS_TYPE].payload or []

    clip_prefix = str(ctx.params.get("clip_prefix", "clip_"))
    out_dir = str(ctx.params.get("out_dir", "clips"))

    clips: List[Dict[str, Any]] = []
    for idx, seg in enumerate(segments, start=1):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        clip_name = f"{clip_prefix}{idx:03d}.mp4"
        clips.append(
            {
                "id": idx,
                "start": start,
                "end": end,
                "path": f"{out_dir}/{clip_name}",
                "source_video": video.get("path"),
            }
        )

    return {OUT_TYPE: clips}


spec = ModuleSpec(
    name="render_clips",
    version="0.1",
    inputs=[VIDEO_TYPE, SEGMENTS_TYPE],
    outputs=[OUT_TYPE],
    run=run,
    description="Sample module that builds clip index without rendering.",
    impl_path="src/acfv/modular/plugins/render_clips_sample/module.py",
    default_params={"clip_prefix": "clip_", "out_dir": "clips"},
)

__all__ = ["spec"]
