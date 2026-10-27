"""Compatibility adapter for the workflow-oriented product GUI."""

from __future__ import annotations

import sys
from typing import Any

def create_interest_main_window() -> Any:
    """Instantiate the internal interest GUI using unified settings.

    Returns:
        MainWindow: configured with legacy ConfigManager (for compatibility) and
        injected Settings available to pipeline stages via runPipeline.
    """
    try:
        from acfv.product_gui import ProductMainWindow
        from acfv.config.config import ConfigManager  # legacy for existing UI components
        from acfv.arc.domain.settings import load_settings
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "无法导入内部 GUI 组件。请确认已完成迁移并安装依赖 (PyQt5 等): " + str(e)
        ) from e

    cfg = ConfigManager()
    # Preload settings singleton (bridges legacy config)
    load_settings(cfg=cfg)
    return ProductMainWindow(cfg)

__all__ = ["create_interest_main_window"]
