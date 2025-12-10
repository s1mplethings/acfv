"""Utility helpers for ensuring TwitchDownloaderCLI is available."""


from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Tuple

import requests

from acfv.config import config_manager
from acfv.runtime.storage import tools_path

__all__ = [
    "TwitchDownloaderSetupError",
    "resolve_twitch_cli",
    "ensure_cli_on_path",
]

LOGGER = logging.getLogger("acfv.twitch_downloader")
# Upstream latest release as of 2025-12 (API reports 1.56.2). Keep this in sync
# with a stable version to avoid futile upgrade loops.
DEFAULT_RELEASE_TAG = "v1.56.2"
DEFAULT_ASSET_TEMPLATE = (
    "https://github.com/lay295/TwitchDownloader/releases/download/"
    "{tag}/TwitchDownloaderCLI-Windows-x64.zip"
)
EXE_NAME = "TwitchDownloaderCLI.exe"
_CACHED_PATH: Optional[str] = None
MIN_CLI_VERSION: tuple[int, int, int]


class TwitchDownloaderSetupError(RuntimeError):
    """Raised when the Twitch downloader binary cannot be prepared."""


def _parse_version(value: str) -> tuple[int, int, int]:
    numbers = re.findall(r"\d+", value)
    parts = [int(num) for num in numbers[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


MIN_CLI_VERSION = _parse_version(DEFAULT_RELEASE_TAG)


def resolve_twitch_cli(auto_install: bool = True) -> str:
    """Return the path to ``TwitchDownloaderCLI.exe`` (downloading if needed)."""

    global _CACHED_PATH

    if _CACHED_PATH and Path(_CACHED_PATH).exists():
        return _CACHED_PATH

    candidates = _gather_candidate_paths()
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            if _is_version_sufficient(candidate):
                _CACHED_PATH = str(Path(candidate))
                _persist_config(_CACHED_PATH)
                return _CACHED_PATH
            LOGGER.warning(
                "[TwitchDownloader] Outdated TwitchDownloaderCLI detected at %s; upgrading to %s",
                candidate,
                DEFAULT_RELEASE_TAG,
            )

    if not auto_install:
        raise TwitchDownloaderSetupError(
            "TwitchDownloaderCLI.exe not found in PATH or configured locations."
        )

    try:
        installed_path = _download_and_install_cli()
    except Exception as exc:
        raise TwitchDownloaderSetupError(str(exc)) from exc

    _CACHED_PATH = str(installed_path)
    _persist_config(_CACHED_PATH)
    return _CACHED_PATH


def ensure_cli_on_path(auto_install: bool = True) -> Optional[str]:
    """Resolve the CLI and prepend its directory to ``PATH``."""

    try:
        path = resolve_twitch_cli(auto_install=auto_install)
    except TwitchDownloaderSetupError as exc:
        LOGGER.error("[TwitchDownloader] TwitchDownloaderCLI 未就绪: %s", exc)
        return None

    directory = str(Path(path).parent)
    current_path = os.environ.get("PATH", "")
    if directory not in current_path.split(os.pathsep):
        os.environ["PATH"] = directory + os.pathsep + current_path
    return path


# --------------------------------------------------------------------------- #
# internal helpers


def _gather_candidate_paths() -> list[str]:
    paths: list[str] = []

    cfg_value = config_manager.get("TWITCH_DOWNLOADER_PATH")
    if cfg_value:
        paths.append(str(cfg_value))

    env_value = os.environ.get("TWITCHDOWNLOADER_CLI")
    if env_value:
        paths.append(env_value)

    # Previously installed copy in tools/
    paths.append(str(tools_path(EXE_NAME)))

    # Project-level tools directory (if user placed it there)
    project_root = Path(__file__).resolve().parents[3]
    paths.append(str(project_root / "tools" / EXE_NAME))

    # Local directory fallback
    paths.append(str(project_root / EXE_NAME))
    return paths


def _get_cli_version(path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            output = (result.stdout or "") + (result.stderr or "")
            match = re.search(r"(\d+\.\d+\.\d+)", output)
            if match:
                return match.group(1)
    except Exception:
        LOGGER.debug(
            "[TwitchDownloader] Unable to query CLI version from %s", path, exc_info=True
        )
    return None


def _is_version_sufficient(path: str) -> bool:
    version = _get_cli_version(path)
    if not version:
        return False
    parsed = _parse_version(version)
    if parsed < MIN_CLI_VERSION:
        LOGGER.info(
            "[TwitchDownloader] CLI %s is older than required %s; reinstalling.",
            version,
            DEFAULT_RELEASE_TAG,
        )
        return False
    return True


def _persist_config(path: str) -> None:
    try:
        stored = config_manager.get("TWITCH_DOWNLOADER_PATH")
        if stored != path:
            config_manager.set("TWITCH_DOWNLOADER_PATH", path, persist=True)
    except Exception:
        LOGGER.debug("Failed to persist TWITCH_DOWNLOADER_PATH", exc_info=True)


def _download_and_install_cli() -> Path:
    tools_dir = tools_path()
    tools_dir.mkdir(parents=True, exist_ok=True)

    tag, url = _resolve_release_asset()
    LOGGER.info("[TwitchDownloader] downloading %s from %s", tag, url)

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "twitch_downloader.zip"
        _http_download(url, zip_path)

        with zipfile.ZipFile(zip_path, "r") as archive:
            member = _find_executable_member(archive)
            extracted = Path(archive.extract(member, path=tmp_dir))

        target_path = tools_dir / EXE_NAME
        if target_path.exists():
            target_path.unlink()
        shutil.move(str(extracted), target_path)
        # ensure executable bit (important on POSIX environments)
        target_path.chmod(target_path.stat().st_mode | stat.S_IEXEC)

    LOGGER.info(
        "[TwitchDownloader] installed TwitchDownloaderCLI to %s", target_path
    )
    return target_path


def _resolve_release_asset() -> Tuple[str, str]:
    api_url = "https://api.github.com/repos/lay295/TwitchDownloader/releases/latest"
    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        payload = response.json()
        tag = payload.get("tag_name") or DEFAULT_RELEASE_TAG
        for asset in payload.get("assets", []):
            name = asset.get("name", "")
            if (
                name.endswith(".zip")
                and "Windows" in name
                and "CLI" in name
            ):
                return tag, asset["browser_download_url"]
    except Exception as exc:
        LOGGER.warning(
            "[TwitchDownloader] unable to query GitHub releases (%s), "
            "falling back to default asset.", exc
        )

    fallback_url = DEFAULT_ASSET_TEMPLATE.format(tag=DEFAULT_RELEASE_TAG)
    return DEFAULT_RELEASE_TAG, fallback_url


def _http_download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=30) as response:
        response.raise_for_status()
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 15):
                if chunk:
                    handle.write(chunk)


def _find_executable_member(archive: zipfile.ZipFile) -> str:
    for member in archive.namelist():
        if member.lower().endswith(EXE_NAME.lower()):
            return member
    raise TwitchDownloaderSetupError(
        "TwitchDownloaderCLI executable not found in downloaded archive."
    )
