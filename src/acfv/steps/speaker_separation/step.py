from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import (
    ART_AUDIO_GAME,
    ART_AUDIO_HOST,
    ART_AUDIO_LABELS,
    ART_AUDIO_VIDEO_SPEECH,
    ART_SPEAKER_RESULT,
    ART_VIDEO,
)
from acfv.modular.types import ModuleContext


def run(ctx: ModuleContext) -> Dict[str, Any]:
    enabled = bool(ctx.params.get("enabled", False))
    if not enabled:
        return {
            ART_AUDIO_HOST: {"path": None},
            ART_AUDIO_VIDEO_SPEECH: {"path": None},
            ART_AUDIO_GAME: {"path": None},
            ART_AUDIO_LABELS: [],
            ART_SPEAKER_RESULT: {"status": "disabled"},
        }

    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path:
        raise FileNotFoundError("video path missing")

    try:
        from .impl import SpeakerSeparationIntegration
    except Exception:
        return {
            ART_AUDIO_HOST: {"path": None},
            ART_AUDIO_VIDEO_SPEECH: {"path": None},
            ART_AUDIO_GAME: {"path": None},
            ART_AUDIO_LABELS: [],
            ART_SPEAKER_RESULT: {"status": "unavailable"},
        }

    integration = SpeakerSeparationIntegration(None)
    output_dir = ctx.params.get("output_dir")
    if not output_dir:
        output_dir = str(Path(ctx.store.run_dir) / "work" / "speaker_separation")

    if ctx.progress:
        ctx.progress("speaker_separation", 0, 1, "start")
        integration.set_progress_callback(
            lambda stage, current, total, message: ctx.progress(
                "speaker_separation", current, total, message or stage
            )
        )

    result = integration.process_video_with_speaker_separation(video_path, output_dir=output_dir)
    host_audio = None
    video_speech_audio = None
    game_audio = None
    labels = []
    labels_file = None
    if isinstance(result, dict):
        host_audio = result.get("host_audio_file")
        video_speech_audio = result.get("video_speech_audio_file")
        game_audio = result.get("game_audio_file")
        labels = result.get("labels") or []
        labels_file = result.get("labels_file")

    if ctx.progress:
        ctx.progress("speaker_separation", 1, 1, "done")

    labels_payload: Any = labels or []
    if labels_file or labels:
        labels_payload = {"path": labels_file, "segments": labels}

    return {
        ART_AUDIO_HOST: {"path": host_audio},
        ART_AUDIO_VIDEO_SPEECH: {"path": video_speech_audio},
        ART_AUDIO_GAME: {"path": game_audio},
        ART_AUDIO_LABELS: labels_payload,
        ART_SPEAKER_RESULT: result or {"status": "failed"},
    }


__all__ = ["run"]
