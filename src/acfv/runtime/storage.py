"""Centralised runtime storage locations.

This module defines a writable ``var`` directory (or an override via the
``ACFV_STORAGE_ROOT`` environment variable) that keeps user data out of the
package tree:

``var/processing``  – generated clips/logs/progress files
``var/secrets``     – sensitive tokens / credentials
``var/settings``    – mutable configuration files

The helpers ensure these folders exist on first use and return ``Path`` objects
so callers can work with pathlib consistently.
"""

from __future__ import annotations

import os
from functools import lru_cache
from os import PathLike
from pathlib import Path


@lru_cache(maxsize=1)
def storage_root() -> Path:
    """Return the root directory where runtime data should be stored."""
    custom_root = os.environ.get("ACFV_STORAGE_ROOT")
    if custom_root:
        base = Path(custom_root).expanduser()
    else:
        # Project root (…/src/../../) / "var"
        base = Path(__file__).resolve().parents[3] / "var"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _subdir(name: str) -> Path:
    path = storage_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def processing_path(*parts: str | PathLike[str]) -> Path:
    base = _subdir("processing")
    return base if not parts else base.joinpath(*parts)


def secrets_path(*parts: str | PathLike[str]) -> Path:
    base = _subdir("secrets")
    return base if not parts else base.joinpath(*parts)


def settings_path(*parts: str | PathLike[str]) -> Path:
    base = _subdir("settings")
    return base if not parts else base.joinpath(*parts)


def tools_path(*parts: str | PathLike[str]) -> Path:
    """Return a path inside the runtime tools directory."""
    base = _subdir("tools")
    return base if not parts else base.joinpath(*parts)


def logs_path(*parts: str | PathLike[str]) -> Path:
    """Return a path inside the runtime logs directory."""
    base = _subdir("logs")
    return base if not parts else base.joinpath(*parts)


def resolve_clips_base_dir(config_manager, ensure: bool = False) -> Path:
    """Resolve the base directory used to store generated clips."""
    runtime_root = storage_root().parent
    try:
        configured = config_manager.get("CLIPS_BASE_DIR")  # type: ignore[attr-defined]
    except Exception:
        configured = None

    if configured:
        candidate = Path(str(configured)).expanduser()
        if not candidate.is_absolute():
            candidate = (runtime_root / candidate).resolve()
    else:
        candidate = (runtime_root / "clips").resolve()

    if ensure:
        candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def ensure_runtime_dirs() -> None:
    """Ensure commonly used subdirectories exist."""
    for name in ("processing", "secrets", "settings", "cache", "logs", "tools"):
        _subdir(name)

