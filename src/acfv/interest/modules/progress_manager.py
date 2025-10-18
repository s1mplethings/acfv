"""Facade exposing the unified progress manager for interest processing."""
from __future__ import annotations

from acfv.features.modules.progress_manager import (  # noqa: F401
    ProgressManager,
    StageInfo,
)

__all__ = ["ProgressManager", "StageInfo"]
