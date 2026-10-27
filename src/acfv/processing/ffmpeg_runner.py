from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable


def check_ffmpeg() -> bool:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def subtitles_filter_arg(path: str | Path) -> str:
    escaped = Path(path).resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
    return f"subtitles='{escaped}'"


def run_ffmpeg(cmd: Iterable[str], timeout: int = 1800) -> None:
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg is not available")
    result = subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")
