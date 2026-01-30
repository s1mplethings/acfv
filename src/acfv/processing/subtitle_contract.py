from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_VERSION = "1.0.0"
ALLOWED_FORMATS = {"srt", "ass"}


@dataclass
class SubtitleOptions:
    segments: List[Dict[str, Any]]
    fmt: str
    out_dir: Path
    source_name: str
    time_offset: float = 0.0
    framerate: float | None = None


def _validate_segments(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError("segments must be a list")
    result: List[Dict[str, Any]] = []
    for idx, seg in enumerate(items):
        if not isinstance(seg, dict):
            continue
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except Exception:
            continue
        if end <= start:
            raise ValueError(f"segment {idx} has non-positive duration")
        text = (seg.get("text") or "").strip()
        result.append({"start": start, "end": end, "text": text})
    return sorted(result, key=lambda s: (s["start"], s["end"]))


def _validate_payload(payload: Dict[str, Any]) -> SubtitleOptions:
    segments = _validate_segments(payload.get("segments") or [])
    fmt = str(payload.get("format", "srt")).lower()
    if fmt not in ALLOWED_FORMATS:
        raise ValueError("format must be srt or ass")
    source = payload.get("source_name") or "subtitle"
    out_dir_val = payload.get("out_dir") or "."
    out_dir = Path(str(out_dir_val))
    out_dir.mkdir(parents=True, exist_ok=True)
    time_offset = float(payload.get("time_offset_sec", 0.0) or 0.0)
    framerate = payload.get("framerate")
    if framerate is not None:
        framerate = float(framerate)
    return SubtitleOptions(
        segments=segments,
        fmt=fmt,
        out_dir=out_dir,
        source_name=str(source),
        time_offset=time_offset,
        framerate=framerate,
    )


def _format_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = int(round(seconds * 100))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _write_srt(segments: List[Dict[str, Any]], path: Path, offset: float) -> None:
    lines: List[str] = []
    for idx, seg in enumerate(segments, 1):
        start = _format_srt_time(seg["start"] + offset)
        end = _format_srt_time(seg["end"] + offset)
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(seg["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_ass(segments: List[Dict[str, Any]], path: Path, offset: float) -> None:
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "Collisions: Normal",
        "Timer: 100.0000",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body: List[str] = []
    for seg in segments:
        start = _format_ass_time(seg["start"] + offset)
        end = _format_ass_time(seg["end"] + offset)
        text = (seg["text"] or "").replace("\n", "\\N")
        body.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    path.write_text("\n".join(header + body), encoding="utf-8")


def generate_subtitle(payload: Dict[str, Any]) -> Dict[str, Any]:
    opts = _validate_payload(payload)
    if not opts.segments:
        raise ValueError("segments cannot be empty")

    # adjust ordering and clamp negative times after offset
    adjusted = []
    for seg in opts.segments:
        start = max(0.0, seg["start"])
        end = max(start, seg["end"])
        adjusted.append({"start": round(start, 3), "end": round(end, 3), "text": seg["text"]})
    adjusted.sort(key=lambda s: (s["start"], s["end"]))

    filename = f"{opts.source_name}.{opts.fmt}"
    path = opts.out_dir / filename
    if opts.fmt == "srt":
        _write_srt(adjusted, path, opts.time_offset)
    else:
        _write_ass(adjusted, path, opts.time_offset)

    return {
        "schema_version": SCHEMA_VERSION,
        "subtitle_path": str(path),
        "format": opts.fmt,
        "segments": len(adjusted),
    }


__all__ = ["generate_subtitle", "SubtitleOptions", "SCHEMA_VERSION"]
