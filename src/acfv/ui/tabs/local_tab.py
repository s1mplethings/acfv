"""Factory for the local replay processing tab."""

from __future__ import annotations

from PyQt5.QtWidgets import QWidget

from acfv.processing.local_video_manager import LocalVideoManager

from .base import TabHandle


def create_local_tab(main_window, config_manager) -> TabHandle:
    container = QWidget()
    controller = LocalVideoManager(main_window, config_manager)
    controller.init_ui(container)
    return TabHandle(title="本地回放处理", widget=container, controller=controller)

