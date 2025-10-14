# Phase 1 partial copy: main_window minimal skeleton referencing internal placeholders.
from __future__ import annotations

import logging
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QTabWidget, QStatusBar, QMessageBox
)

from acfv.interest.processing.twitch_downloader import TwitchTab
from acfv.interest.processing.local_video_manager import LocalVideoManager
from acfv.interest.modules.progress_manager import ProgressManager
from acfv.interest.modules.beautiful_progress_widget import (
    SimpleBeautifulProgressBar, BeautifulProgressWidget
)
from acfv.interest.modules.pipeline_backend import run_pipeline, ConfigManager
from acfv.interest.modules.ui_components import Worker

class MainWindow(QMainWindow):  # Upgraded partial integration
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.progress_manager = ProgressManager()
        if not isinstance(self.config_manager, ConfigManager):
            # Wrap external-like manager into our ConfigManager for pipeline needs
            try:
                self.pipeline_config = ConfigManager()
                # carry over known keys if available
                for key in ["VIDEO_FILE", "CHAT_FILE"]:
                    if hasattr(self.config_manager, 'get'):
                        val = self.config_manager.get(key)
                        if val:
                            self.pipeline_config.set(key, val)
            except Exception:  # noqa: BLE001
                self.pipeline_config = ConfigManager()
        else:
            self.pipeline_config = self.config_manager
        self.setWindowTitle("ACFV Interest GUI")
        self.resize(1180, 720)

        # Central layout
        central = QWidget(); self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Tabs
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.tab_twitch = QWidget(); self.tabs.addTab(self.tab_twitch, "Twitch 下载")
        self.twitch_tab = TwitchTab(self, self.config_manager); self.twitch_tab.init_ui(self.tab_twitch)
        self.tab_local = QWidget(); self.tabs.addTab(self.tab_local, "本地回放处理")
        self.local_tab = LocalVideoManager(self, self.config_manager); self.local_tab.init_ui(self.tab_local)

        # Progress Widgets (simple + advanced collapsed initially)
        self.simple_progress = SimpleBeautifulProgressBar(); layout.addWidget(self.simple_progress)
        self.simple_progress.set_progress_manager(self.progress_manager)
        self.advanced_progress = BeautifulProgressWidget(style_theme="modern")
        self.advanced_progress.set_progress_manager(self.progress_manager)
        layout.addWidget(self.advanced_progress)
        self.advanced_progress.setVisible(False)  # hide advanced by default

        # Info label
        self.info_label = QLabel("已迁移: progress_manager, progress widgets, Twitch/本地管理 (简化版). 下一步: pipeline_backend")
        layout.addWidget(self.info_label)

        # Status bar
        sb = QStatusBar(); self.setStatusBar(sb)
        self._status_ref = sb
        self.update_status("就绪")

    # ---------- Status / Progress API (used by managers) ----------
    def update_status(self, text: str):  # noqa: D401
        try:
            if self._status_ref:
                self._status_ref.showMessage(text, 5000)
        except Exception:  # noqa: BLE001
            pass

    def update_detailed_progress(self, detail: str):  # noqa: D401
        # Could map to advanced widget detail label if visible
        if hasattr(self.advanced_progress, 'detail_label'):
            try:
                self.advanced_progress.detail_label.setText(f"📋 {detail}")
            except Exception:  # noqa: BLE001
                pass

    def update_progress_percent(self, percent: int):  # noqa: D401
        try:
            self.simple_progress.setValue(percent)
        except Exception:  # noqa: BLE001
            pass

    def start_processing_progress(self, video_duration: float = 0, file_size: float = 0):  # noqa: D401
        self.progress_manager.start_processing(video_duration=video_duration, file_size=file_size)
        self.simple_progress.setVisible(True)
        self.simple_progress.start_progress("处理中...")
        self.advanced_progress.setVisible(True)
        self.advanced_progress.start_monitoring()

    def stop_processing_progress(self):  # noqa: D401
        try:
            self.progress_manager.finish_processing()
        except Exception:  # noqa: BLE001
            pass
        self.simple_progress.hide_progress()
        self.advanced_progress.stop_monitoring()

    # Backward compat alias
    def runPipeline(self):  # noqa: D401
        self.start_processing_progress()
        run_pipeline(self, self.progress_manager, self.pipeline_config)

__all__ = ["MainWindow"]
