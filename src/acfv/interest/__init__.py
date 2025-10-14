"""Interest rating integrated subpackage.

Phase 1: Thin wrappers & sys.modules shims so legacy relative imports
(from processing / modules / config) still resolve while we progressively
rewrite them to proper absolute imports under acfv.interest.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path

# Dynamic shim (will be removed in later phase once imports normalized)
_pkg_root = _Path(__file__).resolve().parent
for _name in ["processing", "modules", "services", "workers", "config"]:
    _candidate = _pkg_root / _name
    if _candidate.exists() and _candidate.is_dir():
        # expose as top-level for legacy imports e.g. `from processing.x import Y`
        _sys.modules.setdefault(_name, __import__(f"acfv.interest.{_name}", fromlist=[_name]))

del _name, _candidate, _pkg_root, _sys, _Path

__all__ = []
