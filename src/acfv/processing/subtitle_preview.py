from __future__ import annotations

from pathlib import Path

import pysubs2

from .ffmpeg_runner import run_ffmpeg, subtitles_filter_arg


def make_preview_ass(in_ass: str | Path, preview_start: float, preview_duration: float, out_ass: str | Path) -> Path:
    subtitles = pysubs2.load(str(in_ass))
    subtitles.shift(ms=int(round(-preview_start * 1000)))
    maximum = int(round(preview_duration * 1000))
    trimmed = pysubs2.SSAFile()
    trimmed.styles = subtitles.styles
    for event in subtitles.events:
        if event.end <= 0 or event.start >= maximum:
            continue
        event.start, event.end = max(0, event.start), min(maximum, event.end)
        if event.end > event.start:
            trimmed.events.append(event)
    output = Path(out_ass)
    output.parent.mkdir(parents=True, exist_ok=True)
    trimmed.save(str(output))
    return output


def render_preview(video_path: str | Path, preview_start: float, preview_duration: float, preview_ass: str | Path, out_mp4: str | Path) -> Path:
    output = Path(out_mp4)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(preview_start), "-t", str(preview_duration), "-i", str(video_path),
        "-vf", subtitles_filter_arg(preview_ass), "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-c:a", "aac", "-b:a", "160k", str(output),
    ], timeout=600)
    return output
