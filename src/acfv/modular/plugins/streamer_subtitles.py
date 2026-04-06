from __future__ import annotations

from typing import Any, Dict

from acfv.modular.contracts import ART_SPEAKER_RESULT, ART_SUBTITLES_STREAMER, ART_TRANSCRIPT
from acfv.modular.types import ModuleContext, ModuleSpec


def run(ctx: ModuleContext) -> Dict[str, Any]:
    enabled = bool(ctx.params.get("enabled", False))
    if not enabled:
        return {ART_SUBTITLES_STREAMER: {"status": "disabled"}}

    speaker_payload = ctx.inputs.get(ART_SPEAKER_RESULT)
    if speaker_payload and isinstance(speaker_payload.payload, dict):
        status = speaker_payload.payload.get("status")
        if status in {"disabled", "unavailable"}:
            return {ART_SUBTITLES_STREAMER: {"status": status}}

    from acfv.steps.subtitle_generator.streamer_subtitles import run_generate_streamer_subtitles

    result = run_generate_streamer_subtitles(
        run_dir=ctx.store.run_dir,
        config={
            "primary_speaker": ctx.params.get("primary_speaker"),
        },
    )
    return {ART_SUBTITLES_STREAMER: result}


spec = ModuleSpec(
    name="streamer_subtitles",
    version="1",
    inputs=[ART_TRANSCRIPT, ART_SPEAKER_RESULT],
    outputs=[ART_SUBTITLES_STREAMER],
    run=run,
    description="Generate streamer-only subtitles aligned to diarization and transcript.",
    impl_path="src/acfv/steps/subtitle_generator/streamer_subtitles.py",
    default_params={"enabled": False, "primary_speaker": None},
)

__all__ = ["spec"]
