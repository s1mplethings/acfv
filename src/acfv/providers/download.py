from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Callable
from urllib.parse import urlparse

from acfv.utils.twitch_downloader_setup import ensure_cli_on_path

from .config import provider_name

_TWITCH_VOD_RE = re.compile(r"^/videos/(\d+)/?$", re.IGNORECASE)


class DownloadInterrupted(RuntimeError):
    pass


@dataclass(frozen=True)
class TwitchVodMetadata:
    vod_id: str
    source_url: str
    creator_id: str
    creator_login: str
    creator_name: str
    title: str
    created_at: datetime | None
    duration_ms: int
    category: str | None
    thumbnail_url: str | None
    language: str | None
    provider_metadata: dict[str, Any]


@dataclass(frozen=True)
class TwitchChannelVideo:
    vod_id: str
    creator_id: str
    creator_login: str
    creator_name: str
    title: str
    created_at: str
    published_at: str
    duration_seconds: int
    vod_type: str
    view_count: int
    source_url: str


_PUBLIC_TWITCH_WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_CHANNEL_VIDEOS_QUERY = """
query($login:String!,$first:Int!){
  user(login:$login){
    id login displayName
    videos(first:$first,sort:TIME,types:[ARCHIVE,HIGHLIGHT]){
      edges{node{id title createdAt publishedAt lengthSeconds broadcastType viewCount owner{login displayName}}}
    }
  }
}
"""


def discover_public_twitch_vods(
    creator_login: str, *, limit: int = 20, request_post: Callable[..., Any] | None = None,
) -> list[TwitchChannelVideo]:
    """Discover public channel VOD metadata when Helix credentials are absent.

    This uses the same public metadata endpoint as Twitch's web client.  It is a
    discovery-only fallback: all media acquisition still routes through
    :class:`VodDownloadService` and TwitchDownloaderCLI.
    """
    import requests

    login = creator_login.strip().casefold()
    if not re.fullmatch(r"[a-z0-9_]{1,25}", login):
        raise ValueError("invalid Twitch creator login")
    post = request_post or requests.post
    response = post(
        "https://gql.twitch.tv/gql",
        headers={"Client-Id": _PUBLIC_TWITCH_WEB_CLIENT_ID},
        json={"query": _CHANNEL_VIDEOS_QUERY, "variables": {"login": login, "first": max(1, min(100, int(limit)))}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Twitch public metadata query failed for {login}")
    user = (payload.get("data") or {}).get("user")
    if not isinstance(user, dict):
        return []
    rows: list[TwitchChannelVideo] = []
    for edge in ((user.get("videos") or {}).get("edges") or []):
        node = (edge or {}).get("node") or {}
        vod_id = str(node.get("id") or "")
        owner = node.get("owner") or {}
        if not vod_id.isdigit() or str(owner.get("login") or login).casefold() != login:
            continue
        kind = str(node.get("broadcastType") or "").casefold()
        if kind not in {"archive", "highlight"}:
            continue
        rows.append(TwitchChannelVideo(
            vod_id=vod_id,
            creator_id=str(user.get("id") or ""),
            creator_login=login,
            creator_name=str(user.get("displayName") or login),
            title=str(node.get("title") or f"Twitch VOD {vod_id}"),
            created_at=str(node.get("createdAt") or ""),
            published_at=str(node.get("publishedAt") or node.get("createdAt") or ""),
            duration_seconds=int(node.get("lengthSeconds") or 0),
            vod_type=kind,
            view_count=int(node.get("viewCount") or 0),
            source_url=f"https://www.twitch.tv/videos/{vod_id}",
        ))
    return rows


def parse_twitch_vod_id(src: str) -> str:
    text = (src or "").strip()
    if text.isdigit():
        return text
    parsed = urlparse(text)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
        raise ValueError("Expected a Twitch VOD URL such as https://www.twitch.tv/videos/123 or a numeric VOD ID")
    match = _TWITCH_VOD_RE.fullmatch(parsed.path)
    if not match:
        if parsed.path.strip("/") and "/" not in parsed.path.strip("/"):
            raise ValueError("A Twitch channel URL cannot be used as a VOD download; open a specific /videos/<id> URL")
        raise ValueError("The Twitch URL does not identify a VOD; expected /videos/<id>")
    return match.group(1)


def normalize_twitch_vod_input(src: str) -> tuple[str, str, str]:
    vod_id = parse_twitch_vod_id(src)
    return "twitch", vod_id, f"https://www.twitch.tv/videos/{vod_id}"


def twitch_downloader_version(cli_path: str | None = None) -> str:
    executable = cli_path or ensure_cli_on_path(auto_install=True)
    result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
    )
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0] if text else "unknown"


def fetch_twitch_vod_metadata(src: str, *, cli_path: str | None = None) -> TwitchVodMetadata:
    _, vod_id, source_url = normalize_twitch_vod_input(src)
    executable = cli_path or ensure_cli_on_path(auto_install=True)
    result = subprocess.run(
        [executable, "info", "--id", vod_id, "--format", "Raw", "--banner=false", "--log-level", "None"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit={result.returncode}").strip()
        raise RuntimeError(f"Unable to read Twitch VOD metadata: {detail}")
    video = None
    for line in result.stdout.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate = (payload.get("data") or {}).get("video")
        if isinstance(candidate, dict) and candidate.get("owner"):
            video = candidate
            break
    if not video:
        raise FileNotFoundError(f"Twitch VOD {vod_id} was deleted, is private, or is not accessible")
    owner = video.get("owner") or {}
    created_at = None
    if video.get("createdAt"):
        created_at = datetime.fromisoformat(str(video["createdAt"]).replace("Z", "+00:00"))
    thumbnails = video.get("thumbnailURLs") or []
    return TwitchVodMetadata(
        vod_id=vod_id,
        source_url=source_url,
        creator_id=str(owner.get("id") or owner.get("login") or "").casefold(),
        creator_login=str(owner.get("login") or owner.get("displayName") or "").casefold(),
        creator_name=str(owner.get("displayName") or owner.get("login") or "Unknown Twitch Creator"),
        title=str(video.get("title") or f"Twitch VOD {vod_id}"),
        created_at=created_at,
        duration_ms=int(float(video.get("lengthSeconds") or 0) * 1000),
        category=str((video.get("game") or {}).get("displayName") or "") or None,
        thumbnail_url=str(thumbnails[0]) if thumbnails else None,
        language=str(video.get("language") or "") or None,
        provider_metadata={
            "view_count": video.get("viewCount"),
            "description": video.get("description"),
            "status": video.get("status"),
        },
    )


def download_twitch_vod_to(
    vod_id: str,
    output_path: Path,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    quality: str = "720p",
    threads: int = 4,
    bandwidth_kib_s: int | None = None,
    temp_path: Path | None = None,
    trim_mode: str = "Exact",
    cli_path: str | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: Event | None = None,
    timeout: float = 7200,
) -> Path:
    executable = cli_path or ensure_cli_on_path(auto_install=True)
    if not executable:
        raise RuntimeError("TwitchDownloaderCLI is not available")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path = Path(temp_path or output_path.parent / ".twitch-download-temp")
    cache_path.mkdir(parents=True, exist_ok=True)
    cmd = [
        executable, "videodownload", "--id", vod_id, "--output", str(output_path),
        "--quality", quality, "--threads", str(max(1, int(threads))),
        "--temp-path", str(cache_path),
        "--trim-mode", trim_mode,
        "--collision", "Overwrite", "--banner=false",
    ]
    if bandwidth_kib_s is not None:
        if int(bandwidth_kib_s) <= 0:
            raise ValueError("bandwidth_kib_s must be positive when provided")
        cmd.extend(["--bandwidth", str(int(bandwidth_kib_s))])
    if start_ms is not None:
        cmd.extend(["--beginning", f"{start_ms}ms"])
    if end_ms is not None:
        cmd.extend(["--ending", f"{end_ms}ms"])
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    started = time.monotonic()
    output_lines: list[str] = []
    phase_index = 0
    last_provider_percent: float | None = None
    assert process.stdout is not None
    while True:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            raise DownloadInterrupted("Twitch VOD download was interrupted")
        if time.monotonic() - started > timeout:
            process.kill()
            raise TimeoutError(f"Twitch VOD download exceeded {timeout:.0f} seconds")
        line = process.stdout.readline()
        if line:
            clean = line.strip()
            output_lines.append(clean)
            percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", clean)
            speed_match = re.search(r"(\d+(?:\.\d+)?)\s*([KMGT]i?B)/s", clean, re.IGNORECASE)
            progress: dict[str, Any] = {"downloaded_bytes": output_path.stat().st_size if output_path.exists() else 0}
            if percent_match:
                provider_percent = min(100.0, float(percent_match.group(1)))
                if last_provider_percent is not None and last_provider_percent >= 95.0 and provider_percent <= 5.0:
                    phase_index = min(2, phase_index + 1)
                last_provider_percent = provider_percent
                progress["provider_percent"] = provider_percent
                progress["current_state"] = ("video_download", "audio_download", "media_mux")[phase_index]
                progress["percent"] = min(99.0, (phase_index * 100.0 + provider_percent) / 3.0)
            if speed_match:
                units = {"KB": 1000, "KIB": 1024, "MB": 1000**2, "MIB": 1024**2, "GB": 1000**3, "GIB": 1024**3}
                progress["speed_bps"] = float(speed_match.group(1)) * units[speed_match.group(2).upper()]
            if progress_callback:
                progress_callback(progress)
        elif process.poll() is not None:
            break
        else:
            time.sleep(0.05)
    if process.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
        detail = "\n".join(output_lines[-20:]) or f"exit={process.returncode}"
        raise RuntimeError(f"TwitchDownloaderCLI failed: {detail}")
    if progress_callback:
        progress_callback({"downloaded_bytes": output_path.stat().st_size, "percent": 100.0})
    return output_path


def download_twitch_vod(vod_id: str, workdir_path: Path) -> Path:
    output_path = workdir_path / f"{vod_id}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    last_error = None
    for _ in range(3):
        try:
            return download_twitch_vod_to(vod_id, output_path)
        except Exception as exc:
            last_error = str(exc)
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


def validate_downloaded_media(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"Downloaded media is empty or missing: {path}")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if probe.returncode != 0:
        raise ValueError(f"ffprobe failed: {(probe.stderr or probe.stdout).strip()}")
    try:
        payload = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid JSON") from exc
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError("Downloaded media has no video stream")
    if audio is None:
        raise ValueError("Downloaded media has no audio stream")
    duration = float((payload.get("format") or {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise ValueError("Downloaded media duration is zero")
    decode = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0",
            # The null muxer requires strictly increasing output timestamps.
            # Recovered chunk boundaries can contain duplicate decoded PTS even
            # when every packet is valid, so use validation-only timestamps.
            # This still decodes every video frame and audio sample and leaves
            # actual decoder errors visible in stderr.
            "-vf", "setpts=N/(60*TB)", "-af", "asetpts=N/SR/TB",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=max(300, int(duration * 4)),
    )
    if decode.returncode != 0 or decode.stderr.strip():
        raise ValueError(f"Media decode scan failed: {decode.stderr.strip() or f'exit={decode.returncode}'}")
    silence = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "silencedetect=noise=-50dB:d=10", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=max(300, int(duration * 4)),
    )
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", silence.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", silence.stderr)]
    muted_intervals = [
        {"start_ms": int(start * 1000), "end_ms": int(end * 1000)}
        for start, end in zip(starts, ends) if end > start
    ]
    return {
        "file_size": path.stat().st_size,
        "duration_ms": int(round(duration * 1000)),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "decode_errors": [],
        "has_suspected_muted_sections": bool(muted_intervals),
        "muted_intervals": muted_intervals,
    }


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
    "download_twitch_vod_to",
    "download_with_streamlink",
    "DownloadInterrupted",
    "fetch_twitch_vod_metadata",
    "normalize_twitch_vod_input",
    "parse_twitch_vod_id",
    "resolve_video_source",
    "TwitchVodMetadata",
    "TwitchChannelVideo",
    "discover_public_twitch_vods",
    "twitch_downloader_version",
    "validate_downloaded_media",
]
