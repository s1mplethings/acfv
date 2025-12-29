from __future__ import annotations

from acfv.modular.contracts import ART_VIDEO, ART_VIDEO_EMOTION
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="video_emotion",
    version="1",
    inputs=[ART_VIDEO],
    outputs=[ART_VIDEO_EMOTION],
    run=run,
    description="Optional video emotion inference for segment scoring.",
    impl_path="src/acfv/steps/video_emotion/step.py",
    default_params={"enabled": True, "segment_length": 4.0, "model_path": "", "device": 0},
)

__all__ = ["spec"]
