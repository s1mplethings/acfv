from __future__ import annotations

from acfv.modular.contracts import ART_AUDIO, ART_TRANSCRIPT
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="transcribe_audio",
    version="2",  # bump to invalidate cached empty transcripts
    inputs=[ART_AUDIO],
    outputs=[ART_TRANSCRIPT],
    run=run,
    description="Transcribe audio into timestamped text segments (Whisper).",
    impl_path="src/acfv/steps/transcribe_audio/impl.py",
    default_params={"segment_length": 300, "whisper_model": "medium"},
)

__all__ = ["spec"]
