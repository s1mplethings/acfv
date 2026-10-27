"""Factory for the clips management tab."""

from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QWidget

from acfv.features.modules.clips_manager import create_clips_manager

from .base import TabHandle


def create_clips_tab(main_window, config_manager) -> TabHandle:
    container = QWidget()
    controller = create_clips_manager(main_window, config_manager)
    controller.init_ui(container)

    # 自动触发首次加载，若可用
    try:
        if hasattr(controller, "_lazy_load_data"):
            QTimer.singleShot(0, controller._lazy_load_data)  # type: ignore[attr-defined]
    except Exception:
        pass

    return TabHandle(title="切片管理", widget=container, controller=controller)

