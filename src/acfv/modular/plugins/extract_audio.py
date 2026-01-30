from __future__ import annotations

import json
import os
import subprocess
import logging
from pathlib import Path
from typing import Any, Dict

from acfv.modular.contracts import ART_AUDIO, ART_VIDEO
from acfv.modular.types import ModuleContext, ModuleSpec

SCHEMA_VERSION = "1.0.0"
logger = logging.getLogger(__name__)


def _ensure_extended_path(path: str | os.PathLike) -> str:
    text = str(path)
    if os.name == "nt":
        normed = os.path.normpath(text)
        if not normed.startswith("\\\\?\\") and len(normed) >= 240:
            return "\\\\?\\" + normed
        return normed
    return text


def _check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _probe_media(path: str) -> Dict[str, Any]:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=30,
    )
    info: Dict[str, Any] = {"duration": 0.0, "sample_rate": None, "channels": None}
    if result.returncode != 0 or not result.stdout:
        return info
    try:
        payload = json.loads(result.stdout)
        info["duration"] = float(payload.get("format", {}).get("duration") or 0.0)
        for stream in payload.get("streams", []):
            if stream.get("codec_type") == "audio":
                if stream.get("sample_rate"):
                    info["sample_rate"] = int(stream["sample_rate"])
                if stream.get("channels"):
                    info["channels"] = int(stream["channels"])
                break
    except Exception:
        return info
    return info


def run(ctx: ModuleContext) -> Dict[str, Any]:
    video_payload = ctx.inputs[ART_VIDEO].payload or {}
    video_path = video_payload.get("path") if isinstance(video_payload, dict) else str(video_payload)
    if not video_path or not os.path.exists(video_path):
        raise FileNotFoundError("video not found")
    if not _check_ffmpeg():
        raise RuntimeError("ffmpeg not available")

    sample_rate = int(ctx.params.get("sample_rate", 16000) or 16000)
    channels = int(ctx.params.get("channels", 1) or 1)
    out_dir = ctx.params.get("out_dir")
    if not out_dir:
        out_dir = Path(ctx.store.run_dir) / "work" / "audio"
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    stem = Path(video_path).stem
    audio_path = out_dir_path / f"{stem}_{sample_rate}hz.wav"

    logger.info(
        "[extract_audio] start | video=%s sample_rate=%s channels=%s out=%s",
        video_path,
        sample_rate,
        channels,
        audio_path,
    )
    if ctx.progress:
        ctx.progress("audio_extract", 0, 2, "start")

    media_info = _probe_media(_ensure_extended_path(video_path))
    duration = float(media_info.get("duration") or 0.0)
    timeout = min(int(duration * 2) + 300, 7200) if duration else 3600
    logger.info(
        "[extract_audio] probe duration=%.2fs sample_rate=%s channels=%s timeout=%ss",
        duration,
        media_info.get("sample_rate"),
        media_info.get("channels"),
        timeout,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        _ensure_extended_path(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-threads",
        "0",
        _ensure_extended_path(audio_path),
    ]
    if ctx.progress:
        ctx.progress("audio_extract", 1, 2, "ffmpeg")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )
    if result.returncode != 0 or not audio_path.exists():
        raise RuntimeError(f"audio extract failed: {result.stderr or result.returncode}")

    if ctx.progress:
        ctx.progress("audio_extract", 2, 2, "done")
    logger.info("[extract_audio] done | audio=%s size=%s bytes", audio_path, audio_path.stat().st_size if audio_path.exists() else 0)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "audio_path": str(audio_path),
        "path": str(audio_path),  # compatibility
        "sample_rate": sample_rate,
        "channels": channels,
        "duration_sec": round(duration, 3) if duration else 0.0,
    }
    return {ART_AUDIO: payload}


spec = ModuleSpec(
    name="extract_audio",
    version="1",
    inputs=[ART_VIDEO],
    outputs=[ART_AUDIO],
    run=run,
    description="Extract mono audio via ffmpeg according to contract.",
    impl_path="src/acfv/modular/plugins/extract_audio.py",
    default_params={"sample_rate": 16000, "channels": 1, "out_dir": None},
)

__all__ = ["spec"]
