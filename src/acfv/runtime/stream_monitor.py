"""Background StreamGet-based live monitor and recorder.

This module offers a thin layer over the `streamget` library so ACFV can keep
watch on selected live rooms and trigger ffmpeg recordings without launching
the full StreamCap GUI.  The same service can run interactively or as a daemon
process (systemd, pm2, Task Scheduler, etc.).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from asyncio.subprocess import PIPE, Process
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Optional

import requests
import yaml
try:
    import streamget
except ImportError as exc:  # pragma: no cover - better message for missing extra
    raise ImportError(
        "streamget is required for the background monitor. "
        "Install it via 'pip install streamget>=4.0.8'."
    ) from exc

from streamget.data import StreamData

from acfv.runtime.storage import ensure_runtime_dirs, logs_path, processing_path, settings_path
from acfv.utils.twitch_downloader_setup import ensure_cli_on_path

LOGGER = logging.getLogger("acfv.stream_monitor")
_LOG_HANDLERS: dict[Path, tuple[logging.Handler, int]] = {}
SCHEMA_VERSION = "1.0.0"


def _attach_log_file(path: Path) -> Path:
    path = path.resolve()
    record = _LOG_HANDLERS.get(path)
    if record:
        handler, refcount = record
        _LOG_HANDLERS[path] = (handler, refcount + 1)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    _LOG_HANDLERS[path] = (handler, 1)
    return path


def _detach_log_file(path: Path) -> None:
    path = path.resolve()
    record = _LOG_HANDLERS.get(path)
    if not record:
        return
    handler, refcount = record
    if refcount <= 1:
        LOGGER.removeHandler(handler)
        handler.close()
        del _LOG_HANDLERS[path]
    else:
        _LOG_HANDLERS[path] = (handler, refcount - 1)


def _extract_login(url: str) -> str:
    clean = url.split("://", 1)[-1]
    clean = clean.split("?", 1)[0]
    clean = clean.strip("/ ")
    if not clean:
        return ""
    return clean.split("/")[-1].lower()


@dataclass
class MonitorEvent:
    timestamp: datetime
    target: str
    event: str
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _camel_key(name: str) -> str:
    """Convert ``DouyinLiveStream`` -> ``douyin``."""
    base = name[:-10] if name.endswith("LiveStream") else name
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", base)
    return cleaned.lower()


def _build_client_map() -> dict[str, type]:
    mapping: dict[str, type] = {}
    for attr in dir(streamget):
        if not attr.endswith("LiveStream"):
            continue
        cls = getattr(streamget, attr)
        mapping[_camel_key(attr)] = cls
    return mapping


STREAM_CLIENTS = _build_client_map()
PLATFORM_ALIASES = {
    "kuaishou": "kwai",
    "ks": "kwai",
    "xhs": "rednote",
    "xiaohongshu": "rednote",
    "xiaohs": "rednote",
    "douyutv": "douyu",
    "bilibili": "bilibili",
    "b站": "bilibili",
    "youtube": "youtube",
    "yt": "youtube",
    "yy": "yy",
    "huajiao": "huajiao",
    "douyin": "douyin",
    "tik": "tiktok",
    "tiktok": "tiktok",
    "douyu": "douyu",
    "huya": "huya",
}
URL_HINTS = {
    "douyin.com": "douyin",
    "tiktok.com": "tiktok",
    "kuaishou.com": "kwai",
    "huya.com": "huya",
    "douyu.com": "douyu",
    "yy.com": "yy",
    "bilibili.com": "bilibili",
    "popkontv.com": "popkontv",
    "twitcasting.tv": "twitcasting",
    "twitch.tv": "twitch",
    "youtube.com": "youtube",
    "live.douyin": "douyin",
    "live.kuaishou": "kwai",
    "weibo.com": "weibo",
    "acfun.cn": "acfun",
    "look.163.com": "look",
    "live.shopee": "shopee",
    "baidu.com": "baidu",
    "flextv.co.kr": "flextv",
    "sooplive.co.kr": "soop",
    "winktv.co.kr": "winktv",
    "chzzk.naver.com": "chzzk",
    "douyu.tv": "douyu",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "stream"


def resolve_platform(raw: str | None, url: str) -> str:
    """Resolve ``platform`` to a streamget client key."""
    candidate = (raw or "auto").strip().lower()
    if candidate in {"auto", "detect", "default"}:
        candidate = guess_platform(url) or candidate
    candidate = PLATFORM_ALIASES.get(candidate, candidate)
    if candidate not in STREAM_CLIENTS:
        raise ValueError(
            f"Unknown platform '{raw}' for url '{url}'. "
            "Set platform to one of: " + ", ".join(sorted(STREAM_CLIENTS.keys()))
        )
    return candidate


def guess_platform(url: str) -> str | None:
    lowered = url.lower()
    for needle, platform in URL_HINTS.items():
        if needle in lowered:
            return platform
    return None


def _resolve_path(value: str | None, base: Path, default_root: Path) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (default_root / path).resolve()
    return path


def _read_template() -> str:
    template = resources.files("acfv.config").joinpath("stream_monitor.example.yaml")
    return template.read_text(encoding="utf-8")


@dataclass
class StreamTarget:
    name: str
    url: str
    platform: str
    quality: str
    poll_interval: int
    fmt: str
    output_dir: Path
    cookies_file: Path | None = None
    proxy: str | None = None
    enabled: bool = True
    slug: str = field(init=False)

    def __post_init__(self) -> None:
        self.slug = slugify(self.name or self.platform)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def read_cookies(self) -> str | None:
        if not self.cookies_file:
            return None
        try:
            text = self.cookies_file.read_text(encoding="utf-8").strip()
            return text or None
        except FileNotFoundError:
            LOGGER.warning("Cookies file missing for %s: %s", self.name, self.cookies_file)
            return None

    def build_client(self):
        cls = STREAM_CLIENTS[self.platform]
        kwargs: dict[str, Any] = {}
        cookies = self.read_cookies()
        sig = inspect.signature(cls)
        if "proxy_addr" in sig.parameters and self.proxy:
            kwargs["proxy_addr"] = self.proxy
        if "cookies" in sig.parameters and cookies:
            kwargs["cookies"] = cookies
        if "access_token" in sig.parameters and cookies and "twitch" in self.platform:
            # allow storing Twitch integrity tokens alongside cookies
            kwargs["access_token"] = cookies
        try:
            return cls(**kwargs)
        except TypeError:
            # Fallback for constructors that still expect positional args
            return cls()

    def to_dict(self, base_dir: Path) -> dict[str, Any]:
        data = {
            "name": self.name,
            "url": self.url,
            "platform": self.platform,
            "quality": self.quality,
            "poll_interval": self.poll_interval,
            "format": self.fmt,
            "enabled": self.enabled,
        }
        try:
            rel = self.output_dir.relative_to(base_dir)
            data["output_dir"] = str(rel)
        except ValueError:
            data["output_dir"] = str(self.output_dir)
        if self.cookies_file:
            data["cookies_file"] = str(self.cookies_file)
        if self.proxy:
            data["proxy"] = self.proxy
        return data


@dataclass
class StreamMonitorConfig:
    ffmpeg_path: str
    default_quality: str
    default_poll_interval: int
    default_format: str
    output_root: Path
    targets: list[StreamTarget]
    download_chat: bool = False
    twitch_client_id: Optional[str] = None
    twitch_oauth_token: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], cfg_dir: Path) -> "StreamMonitorConfig":
        ffmpeg_path = str(raw.get("ffmpeg_path", "ffmpeg"))
        default_quality = str(raw.get("default_quality", "OD")).upper()
        default_poll_interval = int(raw.get("default_poll_interval", 120))
        default_format = str(raw.get("default_format", "mp4")).lower()
        default_output_root = raw.get("output_root")
        base_root = processing_path("stream_monitor")
        if default_output_root:
            output_root = _resolve_path(default_output_root, cfg_dir, base_root) or base_root
        else:
            output_root = base_root

        targets: list[StreamTarget] = []
        for entry in raw.get("targets", []):
            enabled = entry.get("enabled", True)
            name = str(entry.get("name") or entry.get("url") or f"stream-{len(targets)+1}")
            url = str(entry.get("url", "")).strip()
            if not url:
                LOGGER.warning("Skipping target '%s': missing url", name)
                continue
            try:
                platform = resolve_platform(entry.get("platform"), url)
            except ValueError as exc:
                LOGGER.error(str(exc))
                continue

            poll_interval = int(entry.get("poll_interval", default_poll_interval))
            fmt = str(entry.get("format", default_format)).lower()
            quality = str(entry.get("quality", default_quality)).upper()

            raw_output = entry.get("output_dir") or entry.get("output_subdir")
            if raw_output:
                output_dir = _resolve_path(raw_output, cfg_dir, output_root) or output_root
            else:
                output_dir = output_root / slugify(name)
            cookies_file = entry.get("cookies_file")
            cookies_path = (
                _resolve_path(cookies_file, cfg_dir, cfg_dir) if cookies_file else None
            )

            target = StreamTarget(
                name=name,
                url=url,
                platform=platform,
                quality=quality,
                poll_interval=max(5, poll_interval),
                fmt=fmt,
                output_dir=output_dir,
                cookies_file=cookies_path,
                proxy=entry.get("proxy"),
                enabled=enabled,
            )
            targets.append(target)

        download_chat = bool(raw.get("download_chat", False))
        twitch_client_id = raw.get("twitch_client_id") or None
        twitch_oauth_token = raw.get("twitch_oauth_token") or None

        return cls(
            ffmpeg_path=ffmpeg_path,
            default_quality=default_quality,
            default_poll_interval=default_poll_interval,
            default_format=default_format,
            output_root=output_root,
            download_chat=download_chat,
            twitch_client_id=twitch_client_id,
            twitch_oauth_token=twitch_oauth_token,
            targets=targets,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ffmpeg_path": self.ffmpeg_path,
            "default_quality": self.default_quality,
            "default_poll_interval": self.default_poll_interval,
            "default_format": self.default_format,
            "output_root": str(self.output_root),
            "download_chat": self.download_chat,
            "twitch_client_id": self.twitch_client_id or "",
            "twitch_oauth_token": self.twitch_oauth_token or "",
            "targets": [target.to_dict(self.output_root) for target in self.targets],
        }
        return data


def load_stream_monitor_config(path: str | Path | None = None):
    """Load the monitor config, copying the template on first use."""
    ensure_runtime_dirs()
    cfg_path = Path(path) if path else settings_path("stream_monitor.yaml")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if not cfg_path.exists():
        cfg_path.write_text(_read_template(), encoding="utf-8")
        created = True
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    config = StreamMonitorConfig.from_dict(data, cfg_path.parent)
    return config, cfg_path, created


def save_stream_monitor_config(config: StreamMonitorConfig, path: str | Path | None = None) -> Path:
    """Persist the monitor config to disk."""
    cfg_path = Path(path) if path else settings_path("stream_monitor.yaml")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config.to_dict(), fh, allow_unicode=True, sort_keys=False)
    return cfg_path


class StreamMonitorService:
    """Coordinate watchers and ffmpeg recorders."""

    def __init__(
        self,
        config: StreamMonitorConfig,
        event_hook: Optional[Callable[[MonitorEvent], None]] = None,
        log_path: Optional[Path] = None,
    ):
        self.config = config
        self.event_hook = event_hook
        self.log_path = Path(log_path) if log_path else None
        self._stop_event = asyncio.Event()
        self._active: dict[str, Process] = {}
        self._presence_cache: dict[str, str] = {}
        self._recordings: list[str] = []
        self._chat_logs: list[str] = []
        self._last_poll: Optional[str] = None
        self._log_attachment: Optional[Path] = None
        if self.log_path:
            self._log_attachment = _attach_log_file(self.log_path)

    async def run(self, run_once: bool = False) -> None:
        watchers = [
            asyncio.create_task(self._watch_target(target, run_once))
            for target in self.config.targets
            if target.enabled
        ]
        if not watchers:
            LOGGER.warning("No enabled stream targets. Edit %s to add entries.", "stream_monitor.yaml")
            return

        LOGGER.info("Starting stream monitor (%d active targets)", len(watchers))

        try:
            if run_once:
                await asyncio.gather(*watchers)
            else:
                await self._stop_event.wait()
        finally:
            for task in watchers:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await self._terminate_recordings()
            LOGGER.info("Stream monitor shut down.")
            if self._log_attachment:
                _detach_log_file(self._log_attachment)
                self._log_attachment = None

    async def stop(self) -> None:
        self._stop_event.set()

    async def _watch_target(self, target: StreamTarget, run_once: bool) -> None:
        client = target.build_client()
        LOGGER.info("Watcher online: %s (%s)", target.name, target.platform)
        self._set_presence(target, "watcher_started", f"{target.platform} 监控启动")
        while not self._stop_event.is_set():
            try:
                meta = await client.fetch_web_stream_data(target.url)
                if not meta.get("is_live"):
                    LOGGER.debug("%s offline", target.name)
                    self._set_presence(target, "offline", "当前未开播")
                else:
                    stream_data = await client.fetch_stream_url(meta, target.quality)
                    if isinstance(stream_data, StreamData) and stream_data.is_live:
                        self._set_presence(target, "online", "检测到直播")
                        await self._record_once(target, stream_data)
                    else:
                        LOGGER.debug("Stream offline for %s despite positive status", target.name)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("Watcher error for %s: %s", target.name, exc, exc_info=True)
                self._emit_event(target, "error", str(exc))

            if run_once:
                break
            await self._sleep_with_cancel(target.poll_interval)
            self._last_poll = datetime.utcnow().isoformat() + "Z"

        LOGGER.info("Watcher stopped: %s", target.name)
        self._set_presence(target, "watcher_stopped", "监控结束")

    async def _sleep_with_cancel(self, seconds: int) -> None:
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return

    async def _record_once(self, target: StreamTarget, data: StreamData) -> None:
        if target.slug in self._active:
            LOGGER.debug("Already recording %s, skipping duplicate trigger", target.name)
            return

        record_url = data.record_url or data.m3u8_url or data.flv_url
        if not record_url:
            LOGGER.warning("No playable URL for %s", target.name)
            self._emit_event(target, "recording_skipped", "未找到可播放链接")
            return

        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        anchor = slugify(data.anchor_name or target.name)
        filename = f"{anchor}-{timestamp}.{target.fmt}"
        output_path = target.output_dir / filename

        cmd = [
            self.config.ffmpeg_path,
            "-loglevel",
            "warning",
            "-y",
            "-i",
            record_url,
            "-c",
            "copy",
            str(output_path),
        ]

        LOGGER.info("Recording %s -> %s", target.name, output_path)
        self._emit_event(
            target,
            "recording_started",
            f"开始录制 {target.name}",
            output=str(output_path),
            url=record_url,
        )
        try:
            process = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        except FileNotFoundError:
            LOGGER.error("ffmpeg not found at '%s'. Update ffmpeg_path.", self.config.ffmpeg_path)
            self._emit_event(target, "error", "未找到 ffmpeg，可在配置中设置 ffmpeg_path。")
            await self.stop()
            return

        self._active[target.slug] = process
        try:
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                LOGGER.info("Recording finished: %s", output_path)
                self._recordings.append(str(output_path))
                self._emit_event(
                    target,
                    "recording_finished",
                    f"录制完成：{output_path}",
                    output=str(output_path),
                    url=record_url,
                    returncode=0,
                )
                await self._maybe_download_chat(target, data, output_path)
            else:
                LOGGER.warning(
                    "ffmpeg exited with %s for %s (output: %s)",
                    process.returncode,
                    target.name,
                    (stderr or b"").decode(errors="ignore")[-2000:],
                )
                self._emit_event(
                    target,
                    "recording_failed",
                    f"录制失败（退出码 {process.returncode}）",
                    output=str(output_path),
                    returncode=process.returncode,
                )
        finally:
            self._active.pop(target.slug, None)

    async def _terminate_recordings(self) -> None:
        for slug, process in list(self._active.items()):
            if process.returncode is None:
                process.terminate()
                with suppress(asyncio.TimeoutError, ProcessLookupError):
                    await asyncio.wait_for(process.wait(), timeout=5)
            self._active.pop(slug, None)
        if not self._active:
            self._emit_event(None, "shutdown", "所有录制进程已终止。")

    def _set_presence(self, target: StreamTarget, state: str, message: str | None = None) -> None:
        previous = self._presence_cache.get(target.slug)
        if previous == state:
            return
        self._presence_cache[target.slug] = state
        self._emit_event(target, state, message)

    def _emit_event(
        self,
        target: Optional[StreamTarget],
        event: str,
        message: str | None = None,
        **details: Any,
    ) -> None:
        if not self.event_hook:
            return
        try:
            name = target.name if target else "monitor"
            payload = MonitorEvent(
                timestamp=datetime.utcnow(),
                target=name,
                event=event,
                message=message,
                details=details,
            )
            self.event_hook(payload)
        except Exception:
            LOGGER.debug("Failed to dispatch monitor event", exc_info=True)

    async def _maybe_download_chat(self, target: StreamTarget, stream_data: StreamData, video_path: Path) -> None:
        if not self.config.download_chat:
            return
        if target.platform != "twitch":
            return
        vod_id = await self._fetch_latest_twitch_vod_id(target)
        if not vod_id:
            self._emit_event(target, "chat_skipped", "无法获取对应 VOD ID，已跳过弹幕下载。")
            return
        await self._download_twitch_chat(target, vod_id, video_path)

    async def _fetch_latest_twitch_vod_id(self, target: StreamTarget) -> Optional[str]:
        client_id = self.config.twitch_client_id
        token = self.config.twitch_oauth_token
        if not client_id or not token:
            return None

        login = _extract_login(target.url)
        if not login:
            return None

        def request_latest_vods():
            headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
            user_resp = requests.get(
                "https://api.twitch.tv/helix/users",
                params={"login": login},
                headers=headers,
                timeout=10,
            )
            user_resp.raise_for_status()
            user_data = user_resp.json().get("data", [])
            if not user_data:
                return []
            user_id = user_data[0]["id"]
            vod_resp = requests.get(
                "https://api.twitch.tv/helix/videos",
                params={"user_id": user_id, "type": "archive", "first": 5},
                headers=headers,
                timeout=15,
            )
            vod_resp.raise_for_status()
            return vod_resp.json().get("data", [])

        try:
            vods = await asyncio.to_thread(request_latest_vods)
        except Exception as exc:
            LOGGER.error("Unable to query Twitch Helix for %s: %s", login, exc)
            self._emit_event(target, "chat_error", f"无法查询 Twitch VOD: {exc}")
            return None

        if not vods:
            return None

        now = datetime.utcnow().replace(tzinfo=None)
        candidate_id: Optional[str] = None
        for vod in vods:
            created_at = vod.get("created_at")
            try:
                created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                created_dt = None
            if created_dt and now - created_dt <= timedelta(hours=12):
                candidate_id = vod.get("id")
                break
        if not candidate_id:
            candidate_id = vods[0].get("id")
        return candidate_id

    async def _download_twitch_chat(self, target: StreamTarget, vod_id: str, video_path: Path) -> None:
        try:
            ensure_cli_on_path(auto_install=True)
        except Exception as exc:
            LOGGER.error("TwitchDownloaderCLI unavailable: %s", exc)
            self._emit_event(target, "chat_error", f"TwitchDownloaderCLI 不可用: {exc}")
            return

        chat_path = video_path.with_name(video_path.stem + "_chat.json")
        if chat_path.exists():
            self._chat_logs.append(str(chat_path))
            self._emit_event(target, "chat_skipped", "聊天文件已存在。", output=str(chat_path))
            return

        cmd = [
            "TwitchDownloaderCLI.exe",
            "chatdownload",
            "--id",
            vod_id,
            "-o",
            str(chat_path),
            "--format",
            "json",
        ]
        LOGGER.info("Downloading chat for %s -> %s", target.name, chat_path)
        process = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            self._chat_logs.append(str(chat_path))
            self._emit_event(
                target,
                "chat_downloaded",
                "聊天记录已保存。",
                output=str(chat_path),
            )
        else:
            details = (stderr or b"").decode(errors="ignore")[-1000:]
            LOGGER.warning("Chat download failed with %s: %s", process.returncode, details)
            self._emit_event(
                target,
                "chat_error",
                f"聊天下载失败 (code {process.returncode})",
                output=str(chat_path),
                stderr=details,
            )
