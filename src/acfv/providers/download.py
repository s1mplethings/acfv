from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from acfv.utils.twitch_downloader_setup import ensure_cli_on_path

from .config import provider_name

_TWITCH_VOD_RE = re.compile(r"/videos/(\d+)")


def parse_twitch_vod_id(src: str) -> str:
    text = (src or "").strip()
    match = _TWITCH_VOD_RE.search(text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    raise ValueError(f"unsupported twitch VOD URL or id: {src}")


def download_twitch_vod(vod_id: str, workdir_path: Path) -> Path:
    output_path = workdir_path / f"{vod_id}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    cli_path = ensure_cli_on_path(auto_install=True)
    if not cli_path:
        raise RuntimeError("TwitchDownloaderCLI is not available")

    cmd = [cli_path, "videodownload", "--id", vod_id, "-o", str(output_path)]
    last_error = None
    for _ in range(3):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=7200,
        )
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        last_error = (result.stderr or result.stdout or f"exit={result.returncode}").strip()
    raise RuntimeError(f"failed to download twitch VOD {vod_id}: {last_error}")


def download_with_streamlink(url: str, workdir_path: Path, quality: str = "best") -> Path:
    output_path = workdir_path / "streamlink_capture.mp4"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path
    cmd = [
        "streamlink",
        "--retry-open",
        "3",
        "--force",
        url,
        quality or "best",
        "-o",
        str(output_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=7200,
    )
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        detail = (result.stderr or result.stdout or f"exit={result.returncode}").strip()
        raise RuntimeError(f"streamlink download failed: {detail}")
    return output_path


def resolve_video_source(src: str, workdir: str, config_manager: Any = None) -> str:
    workdir_path = Path(workdir)
    workdir_path.mkdir(parents=True, exist_ok=True)

    text = (src or "").strip()
    if text.startswith(("http://", "https://")):
        lower = text.lower()
        provider = provider_name(config_manager, "download", default="twitch-downloader")
        if "twitch.tv" in lower and "/videos/" in lower:
            vod_id = parse_twitch_vod_id(text)
            if provider in {"streamlink", "stream-link"}:
                return str(download_with_streamlink(text, workdir_path))
            try:
                return str(download_twitch_vod(vod_id, workdir_path))
            except Exception:
                return str(download_with_streamlink(text, workdir_path))
        if provider in {"streamlink", "stream-link"}:
            return str(download_with_streamlink(text, workdir_path))
        raise ValueError(f"only twitch VOD URL is supported for provider '{provider}', got: {src}")

    local_path = Path(text).expanduser()
    if not local_path.exists():
        raise FileNotFoundError(f"input video not found: {local_path}")
    return str(local_path)


__all__ = [
    "download_twitch_vod",
    "download_with_streamlink",
    "parse_twitch_vod_id",
    "resolve_video_source",
]
