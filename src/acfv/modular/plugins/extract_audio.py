from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_AUDIO, ART_VIDEO
from acfv.modular.types import ModuleContext, ModuleSpec


def _probe_duration(video_path: str) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30)
        if result.returncode == 0 and result.stdout:
            payload = json.loads(result.stdout)
            return float(payload.get("format", {}).get("duration") or 0.0)
    except Exception:
        return 0.0
    return 0.0


def run(ctx: ModuleContext) -> Dict[str, Any]:
    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path or not os.path.exists(video_path):
        raise FileNotFoundError("video not found")

    work_dir = Path(ctx.store.run_dir) / "work" / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "extracted_audio.wav"

    if ctx.progress:
        ctx.progress("audio_extract", 0, 1, "start")

    if not audio_path.exists():
        duration = _probe_duration(video_path)
        timeout = 3600
        if duration:
            timeout = min(int(duration * 2) + 300, 7200)

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-threads",
            "0",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)
        if result.returncode != 0 and not audio_path.exists():
            raise RuntimeError("audio extract failed")

    size_bytes = audio_path.stat().st_size if audio_path.exists() else 0
    if ctx.progress:
        ctx.progress("audio_extract", 1, 1, "done")

    return {ART_AUDIO: {"path": str(audio_path), "size_bytes": size_bytes}}


spec = ModuleSpec(
    name="extract_audio",
    version="1",
    inputs=[ART_VIDEO],
    outputs=[ART_AUDIO],
    run=run,
    description="Extract mono 16kHz audio from video via ffmpeg.",
    impl_path="src/acfv/modular/plugins/extract_audio.py",
)

__all__ = ["spec"]
