from __future__ import annotations

import re
import subprocess
from pathlib import Path

from acfv.utils.twitch_downloader_setup import ensure_cli_on_path

_TWITCH_VOD_RE = re.compile(r"/videos/(\d+)")


def _parse_twitch_vod_id(src: str) -> str:
    text = (src or "").strip()
    match = _TWITCH_VOD_RE.search(text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    raise ValueError(f"unsupported twitch VOD URL or id: {src}")


def _download_twitch_vod(vod_id: str, workdir_path: Path) -> Path:
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


def fetch_vod(src: str, workdir: str) -> str:
    workdir_path = Path(workdir)
    workdir_path.mkdir(parents=True, exist_ok=True)

    text = (src or "").strip()
    if text.startswith(("http://", "https://")):
        if "twitch.tv" not in text.lower():
            raise ValueError(f"only twitch VOD URL is supported, got: {src}")
        vod_id = _parse_twitch_vod_id(text)
        return str(_download_twitch_vod(vod_id, workdir_path))

    local_path = Path(text).expanduser()
    if not local_path.exists():
        raise FileNotFoundError(f"input video not found: {local_path}")
    return str(local_path)
