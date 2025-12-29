from __future__ import annotations

from acfv.modular.contracts import (
    ART_AUDIO_GAME,
    ART_AUDIO_HOST,
    ART_AUDIO_LABELS,
    ART_AUDIO_VIDEO_SPEECH,
    ART_SPEAKER_RESULT,
    ART_VIDEO,
)
from acfv.modular.types import ModuleSpec

from .step import run


spec = ModuleSpec(
    name="speaker_separation",
    version="1",
    inputs=[ART_VIDEO],
    outputs=[ART_AUDIO_HOST, ART_AUDIO_VIDEO_SPEECH, ART_AUDIO_GAME, ART_AUDIO_LABELS, ART_SPEAKER_RESULT],
    run=run,
    description="Optional speaker separation to isolate host audio.",
    impl_path="src/acfv/steps/speaker_separation/step.py",
    default_params={"enabled": False, "output_dir": None},
)

__all__ = ["spec"]
