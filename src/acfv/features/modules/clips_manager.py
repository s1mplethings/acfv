"""Simplified clips manager facade.

The legacy GUI expects a ``create_clips_manager`` factory returning an object
with ``init_ui`` and (optionally) ``_lazy_load_data``.  The full-featured
implementation from the old interest_rating project has not been migrated yet,
so we provide a light‑weight drop-in that can list generated clips and open the
output directory.  Once the richer manager lands, this module can forward to it.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acfv.runtime.storage import processing_path

__all__ = ["create_clips_manager"]


class _BasicClipsManager:
    """Minimal clips manager to keep the GUI functional."""

    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        self.config_manager = config_manager
        self._list: QListWidget | None = None
        self._output_dir = None

    def init_ui(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)

        layout.addWidget(QLabel("剪辑结果（迁移中，仅列出生成的 mp4 文件）"))
        self._list = QListWidget()
        layout.addWidget(self._list)

        btn_row = QPushButton("打开输出目录")
        btn_row.clicked.connect(self._open_folder)  # type: ignore[attr-defined]
        layout.addWidget(btn_row)

        self._lazy_load_data()

    def _resolve_output_dir(self) -> Path:
        configured = self.config_manager.get("OUTPUT_CLIPS_DIR")
        base = Path(configured) if configured else processing_path("output_clips")
        base.mkdir(parents=True, exist_ok=True)
        self._output_dir = base
        return base

    def _lazy_load_data(self) -> None:
        if not self._list:
            return
        directory = self._resolve_output_dir()
        self._list.clear()
        try:
            clips = sorted(
                (p for p in directory.iterdir() if p.suffix.lower() == ".mp4"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for clip in clips:
                item = QListWidgetItem(clip.name)
                item.setData(256, str(clip))
                self._list.addItem(item)
            logging.info("[clips_manager] 已加载 %d 个剪辑文件", len(clips))
        except FileNotFoundError:
            logging.info("[clips_manager] 输出目录不存在: %s", directory)
        except Exception as exc:  # noqa: BLE001
            logging.error("[clips_manager] 加载剪辑列表失败: %s", exc)

    def _open_folder(self) -> None:
        directory = self._resolve_output_dir()
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", str(directory)])
            elif sys.platform == "darwin":  # type: ignore[name-defined]
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except Exception as exc:  # noqa: BLE001
            logging.error("[clips_manager] 打开目录失败: %s", exc)


def create_clips_manager(main_window, config_manager):
    """Factory used by the GUI."""
    return _BasicClipsManager(main_window, config_manager)
