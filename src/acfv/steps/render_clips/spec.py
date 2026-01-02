from __future__ import annotations

from acfv.modular.contracts import ART_AUDIO_HOST, ART_CLIPS, ART_SEGMENTS, ART_VIDEO
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="render_clips",
    version="1",
    inputs=[ART_VIDEO, ART_SEGMENTS, ART_AUDIO_HOST],
    outputs=[ART_CLIPS],
    run=run,
    description="Render highlight clips from video and segments.",
    impl_path="src/acfv/steps/render_clips/impl.py",
    default_params={"output_dir": None},
)

__all__ = ["spec"]
