from __future__ import annotations

from pathlib import Path

from .ffmpeg_runner import run_ffmpeg, subtitles_filter_arg


def burn_in(video_path: str | Path, styled_ass: str | Path, out_mp4: str | Path) -> Path:
    out_path = Path(out_mp4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(video_path), "-vf", subtitles_filter_arg(styled_ass),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", str(out_path),
    ], timeout=3600)
    return out_path
