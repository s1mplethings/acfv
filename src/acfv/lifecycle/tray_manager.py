"""System tray integration for the PyQt GUI."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon


class TrayManager:
    """Simple wrapper around QSystemTrayIcon with show/exit actions."""

    def __init__(self, window):
        self.window = window
        self.tray_icon: QSystemTrayIcon | None = None
        self.menu: QMenu | None = None
        self._hidden_tip_shown = False
        self.available = QSystemTrayIcon.isSystemTrayAvailable()

    def start(self) -> bool:
        if not self.available:
            logging.info("System tray not available on this platform.")
            return False
        if self.tray_icon:
            return True

        icon = self.window.windowIcon()
        if icon.isNull():
            icon = self._load_fallback_icon()

        tray = QSystemTrayIcon(icon, self.window)
        menu = QMenu()
        show_action = QAction("显示窗口", self.window)
        show_action.triggered.connect(self.window.restore_from_tray)
        exit_action = QAction("退出", self.window)
        exit_action.triggered.connect(self.window.exit_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        tray.setContextMenu(menu)
        tray.setToolTip("ACFV - Twitch Clip Toolkit")
        tray.activated.connect(self._on_activated)
        tray.show()

        self.tray_icon = tray
        self.menu = menu
        logging.info("System tray icon initialized.")
        return True

    def _load_fallback_icon(self) -> QIcon:
        config_dir = getattr(self.window.config_manager, "config_dir", None)
        candidates = [
            Path(self.window.config_manager.get("APP_ICON_PATH", "") or ""),
            Path(config_dir) / "icon.png" if config_dir else None,
            Path(os.getcwd()) / "assets" / "acfv-logo.ico",
            Path(os.getcwd()) / "assets" / "acfv-logo.png",
        ]
        for path in candidates:
            if path and path.exists():
                icon = QIcon(str(path))
                if not icon.isNull():
                    return icon
        return QIcon()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window.restore_from_tray()

    def show_hidden_tip(self) -> None:
        if not self.tray_icon or self._hidden_tip_shown:
            return
        self._hidden_tip_shown = True
        self.tray_icon.showMessage(
            "ACFV",
            "应用已转入后台运行，双击托盘图标可恢复窗口。",
            QSystemTrayIcon.Information,
            4000,
        )

    def shutdown(self) -> None:
        if self.tray_icon:
            self.tray_icon.hide()
            self.tray_icon.deleteLater()
            self.tray_icon = None
            self.menu = None
            logging.info("System tray icon removed.")
