"""Public interest facade for the local video manager.

This simply re-exports :class:`acfv.processing.local_video_manager.LocalVideoManager`
so the GUI integration can depend on the refactored processing package without
maintaining a divergent copy.
"""
from __future__ import annotations

from acfv.processing.local_video_manager import LocalVideoManager  # noqa: F401

__all__ = ["LocalVideoManager"]
