"""Simplified migrated local_video_manager from interest_rating.

Features included:
 - List local downloaded videos from configured folder.
 - Trigger processing callback on main window (if available) with selected video path.
Excluded (can be added later):
 - Thumbnail generation, advanced progress signaling, diarization integration.
"""
from __future__ import annotations

import logging
import os
from typing import List

from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QListWidget, QVBoxLayout, QPushButton, QListWidgetItem

__all__ = ["LocalVideoManager"]


class LocalVideoManager:
    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        self.config_manager = config_manager
        self.list_local: QListWidget | None = None
        self.video_paths: List[str] = []

    def init_ui(self, tab_widget):  # noqa: D401
        layout = QVBoxLayout(tab_widget)
        btn_refresh = QPushButton("刷新本地回放"); btn_refresh.clicked.connect(self.refresh_local_videos)
        layout.addWidget(btn_refresh)
        self.list_local = QListWidget(); self.list_local.setIconSize(QSize(240, 135))
        layout.addWidget(self.list_local)
        btn_process = QPushButton("处理选中回放"); btn_process.clicked.connect(self.process_selected_video)
        layout.addWidget(btn_process)
        self.refresh_local_videos()

    def refresh_local_videos(self):  # noqa: D401
        if not self.list_local:
            return
        folder = self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder") or "./data/twitch"
        if not folder or not os.path.isdir(folder):
            logging.info(f"本地回放目录不存在: {folder}")
            self.list_local.clear(); self.video_paths = []
            return
        try:
            exts = {'.mp4', '.mkv', '.mov'}
            files = [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in exts]
            files.sort(key=lambda x: os.path.getmtime(os.path.join(folder, x)), reverse=True)
            self.list_local.clear(); self.video_paths = []
            for f in files:
                path = os.path.join(folder, f)
                self.video_paths.append(path)
                item = QListWidgetItem(f)
                self.list_local.addItem(item)
            logging.info(f"发现本地回放 {len(files)} 个")
        except Exception as e:  # noqa: BLE001
            logging.error(f"刷新本地视频失败: {e}")

    def process_selected_video(self):  # noqa: D401
        if not self.list_local:
            return
        idx = self.list_local.currentRow()
        if idx < 0 or idx >= len(self.video_paths):
            logging.warning("未选择视频")
            return
        video_path = self.video_paths[idx]
        # Persist into config for downstream pipeline
        self.config_manager.set("VIDEO_FILE", video_path)
        self.config_manager.save()
        if hasattr(self.main_window, 'update_status'):
            self.main_window.update_status(f"已选择视频: {os.path.basename(video_path)}")
        # Invoke pipeline if available
        if hasattr(self.main_window, 'runPipeline'):
            try:
                self.main_window.runPipeline()
            except Exception as e:  # noqa: BLE001
                logging.error(f"触发处理失败: {e}")

