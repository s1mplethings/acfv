from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_AUDIO, ART_TRANSCRIPT
from acfv.modular.types import ModuleContext
from .impl import process_audio_segments


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def run(ctx: ModuleContext) -> Dict[str, Any]:
    audio_payload = ctx.inputs[ART_AUDIO].payload or {}
    audio_path = audio_payload.get("path") if isinstance(audio_payload, dict) else str(audio_payload)
    if not audio_path:
        raise FileNotFoundError("audio path missing")

    work_dir = Path(ctx.store.run_dir) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "transcription.json"

    segment_length = int(ctx.params.get("segment_length", 300))
    whisper_model = str(ctx.params.get("whisper_model", "medium"))

    if ctx.progress:
        ctx.progress("transcribe", 0, 1, "start")

    process_audio_segments(
        audio_path=audio_path,
        output_file=str(out_path),
        segment_length=segment_length,
        whisper_model_name=whisper_model,
    )

    transcript = _read_json(out_path)
    if ctx.progress:
        ctx.progress("transcribe", 1, 1, "done")

    return {ART_TRANSCRIPT: transcript}


__all__ = ["run"]
