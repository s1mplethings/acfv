from __future__ import annotations

from acfv.modular.contracts import ART_CHAT_LOG, ART_SEGMENTS, ART_TRANSCRIPT, ART_VIDEO_EMOTION
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="analyze_segments",
    version="1",
    inputs=[ART_CHAT_LOG, ART_TRANSCRIPT, ART_VIDEO_EMOTION],
    outputs=[ART_SEGMENTS],
    run=run,
    description="Fuse chat, transcript, and emotion into highlight segments.",
    impl_path="src/acfv/steps/analyze_segments/step.py",
    default_params={"max_clips": None, "video_emotion_weight": 0.3, "enable_video_emotion": False},
)

__all__ = ["spec"]
