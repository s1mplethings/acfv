from __future__ import annotations

from acfv.modular.types import ModuleSpec

from .step import OUT_TYPE, SEGMENTS_TYPE, VIDEO_TYPE, run


spec = ModuleSpec(
    name="render_clips_sample",
    version="0.1",
    inputs=[VIDEO_TYPE, SEGMENTS_TYPE],
    outputs=[OUT_TYPE],
    run=run,
    description="Sample module that builds clip index without rendering.",
    impl_path="src/acfv/steps/render_clips_sample/step.py",
    default_params={"clip_prefix": "clip_", "out_dir": "clips"},
)

__all__ = ["spec"]
