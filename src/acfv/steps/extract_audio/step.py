from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_AUDIO, ART_VIDEO
from acfv.modular.types import ModuleContext


def _ensure_extended_path(path: str) -> str:
    """Add Windows long-path prefix when paths are too long."""
    if os.name == "nt":
        norm = os.path.normpath(path)
        if not norm.startswith("\\\\?\\") and len(norm) >= 240:
            return "\\\\?\\" + norm
        return norm
    return path


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
    audio_cmd = _ensure_extended_path(str(audio_path))
    video_cmd = _ensure_extended_path(str(video_path))

    if ctx.progress:
        ctx.progress("audio_extract", 0, 1, "start")

    if not audio_path.exists():
        duration = _probe_duration(video_cmd)
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
            video_cmd,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-threads",
            "0",
            audio_cmd,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)
        if result.returncode != 0 and not Path(audio_cmd).exists():
            raise RuntimeError(f"audio extract failed (ffmpeg rc={result.returncode})")

    size_bytes = Path(audio_cmd).stat().st_size if Path(audio_cmd).exists() else 0
    if size_bytes < 2048:
        raise RuntimeError(f"audio extract produced tiny file ({size_bytes} bytes) at {audio_path}")
    if ctx.progress:
        ctx.progress("audio_extract", 1, 1, "done")

    return {ART_AUDIO: {"path": str(audio_path), "size_bytes": size_bytes}}


__all__ = ["run"]
