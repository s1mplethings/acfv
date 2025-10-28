"""Factory for the Twitch download tab."""

from __future__ import annotations

from PyQt5.QtWidgets import QWidget

from acfv.processing.twitch_downloader import TwitchTab

from .base import TabHandle


def create_twitch_tab(main_window, config_manager) -> TabHandle:
    container = QWidget()
    controller = TwitchTab(main_window, config_manager)
    controller.init_ui(container)
    return TabHandle(title="Twitch 下载", widget=container, controller=controller)

