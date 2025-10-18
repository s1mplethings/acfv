"""Interest GUI shim.

The full PyQt implementation continues to live in :mod:`acfv.main_window`.  This
module re-exports that window class so the rest of the refactored codebase can
import from :mod:`acfv.interest` without losing any functionality while we
finish relocating the source.
"""
from __future__ import annotations

from acfv.main_window import MainWindow  # noqa: F401

__all__ = ["MainWindow"]
