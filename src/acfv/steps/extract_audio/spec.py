from __future__ import annotations

from acfv.modular.contracts import ART_AUDIO, ART_VIDEO
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="extract_audio",
    version="2",  # bump to invalidate cached bad audio artifacts
    inputs=[ART_VIDEO],
    outputs=[ART_AUDIO],
    run=run,
    description="Extract mono 16kHz audio from video via ffmpeg.",
    impl_path="src/acfv/steps/extract_audio/step.py",
)

__all__ = ["spec"]
