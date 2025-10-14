"""Adapter to integrate external interest_rating GUI into acfv package.

Phase 1 integration strategy:
 - Dynamically locate the `interest_rating` directory at repository root.
 - Inject its path into sys.path (front) to satisfy its relative imports
   like `from processing.xxx import ...`.
 - Import `main_window.MainWindow` and (prefer) `modules.pipeline_backend.ConfigManager`.
 - Instantiate and return the window for use by `launch_gui()`.

Future phases (not implemented here):
 - Physically relocate required modules under `acfv/interest/`.
 - Replace sys.path hack with proper relative imports.
 - Unify configuration (ConfigManager -> Settings) and logging.
 - Consolidate pipeline backend with src pipeline skeleton.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

class InterestRatingNotFound(RuntimeError):
    pass

def _find_interest_root() -> Path:
    # Heuristic: repository root is two levels above this file; interest_rating sibling to src
    here = Path(__file__).resolve()
    root = here.parents[2]  # repo root (acfv/)
    candidate = root / "interest_rating"
    if candidate.is_dir():
        return candidate
    raise InterestRatingNotFound(f"interest_rating 目录未找到: {candidate}")

def create_interest_main_window() -> Any:
    """Create MainWindow preferring internal integrated package.

    Order of resolution:
      1. acfv.interest (integrated skeleton / migrated code)
      2. External interest_rating directory (legacy fallback)
    """
    # Try internal first
    try:
        from acfv.interest.main_window import MainWindow  # type: ignore
        from acfv.interest.modules.pipeline_backend import ConfigManager  # type: ignore
        cfg = ConfigManager()
        return MainWindow(cfg)
    except Exception as internal_err:  # noqa: BLE001
        # Fallback: legacy external directory
        interest_root = _find_interest_root()
        s = str(interest_root)
        if s not in sys.path:
            sys.path.insert(0, s)
        ConfigManager = None  # type: ignore
        try:
            from modules.pipeline_backend import ConfigManager as CM  # type: ignore
            ConfigManager = CM
        except Exception:
            try:
                from pipeline_backend import ConfigManager as CM2  # type: ignore
                ConfigManager = CM2
            except Exception:
                raise RuntimeError(
                    f"内部集成失败且外部未找到 ConfigManager: {internal_err}"
                ) from internal_err
        from main_window import MainWindow  # type: ignore
        cfg_file = interest_root / "config" / "config.txt"
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg = ConfigManager(str(cfg_file))
        return MainWindow(cfg)

__all__ = ["create_interest_main_window", "InterestRatingNotFound"]
