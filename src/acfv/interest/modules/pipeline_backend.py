"""Incremental migrated pipeline backend (Phase A).

Provides:
 - ConfigManager (compatible with previous usage).
 - run_pipeline(main_window, progress_manager) that simulates core stages
   and updates ProgressManager with substages.
 - Future: replace simulated work with real processing modules (audio extract,
   diarization, transcription, emotion, analysis, clipping).
"""
from __future__ import annotations

import logging
import json
import os
import time
from typing import Callable, Iterable

__all__ = ["ConfigManager", "run_pipeline"]


class ConfigManager:
    def __init__(self, config_file: str = "processing/config.json"):
        self.config_file = config_file
        self.cfg = {
            "VIDEO_FILE": "",
            "CHAT_FILE": "",
            "TRANSCRIPTION_OUTPUT": "processing/transcription.json",
            "ANALYSIS_OUTPUT": "processing/high_interest_segments.json",
            "OUTPUT_CLIPS_DIR": "processing/output_clips",
        }
        self.load()

    def load(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.cfg.update(data)
        except Exception as e:  # noqa: BLE001
            logging.debug(f"加载配置失败: {e}")

    def save(self):  # noqa: D401
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logging.debug(f"保存配置失败: {e}")

    def get(self, key, default=None):  # noqa: D401
        return self.cfg.get(key, default)

    def set(self, key, value):  # noqa: D401
        self.cfg[key] = value
        return value


# -------- Pipeline Simulation Helpers --------
def _simulate_substages(progress_manager, stage_name: str, substages: Iterable[str], per_substage_seconds: float = 0.4):
    progress_manager.start_stage(stage_name)
    for idx, name in enumerate(substages):
        progress_manager.update_substage(stage_name, idx, 0.0)
        # split into micro-progress ticks
        ticks = 4
        for t in range(1, ticks + 1):
            time.sleep(per_substage_seconds / ticks)
            progress_manager.update_substage(stage_name, idx, t / ticks)
        logging.info(f"完成子阶段: {stage_name}/{name}")
    progress_manager.finish_stage(stage_name)
    progress_manager.next_stage()


def run_pipeline(main_window, progress_manager, config: ConfigManager | None = None, callback: Callable | None = None):  # noqa: D401
    """Run integrated pipeline (simulated for now).

    Args:
        main_window: GUI window providing update_status.
        progress_manager: shared ProgressManager instance.
        config: optional ConfigManager.
        callback: optional callable invoked when done.
    """
    video = config.get("VIDEO_FILE") if config else None
    if not video:
        logging.warning("未选择视频，使用模拟占位路径")
        video = "demo_video.mp4"
    main_window.update_status(f"开始处理: {os.path.basename(video)}")
    progress_manager.start_processing()
    # Stages mirror ProgressManager default definitions
    try:
        _simulate_substages(progress_manager, "音频提取", ["初始化", "提取音轨", "格式转换"])
        _simulate_substages(progress_manager, "说话人分离", ["加载模型", "音频分析", "说话人分离", "后处理"])
        _simulate_substages(progress_manager, "语音转录", ["加载Whisper", "音频切分", "转录处理", "文本优化"], per_substage_seconds=0.5)
        _simulate_substages(progress_manager, "情感分析", ["加载模型", "文本分析", "情感评分"], per_substage_seconds=0.3)
        _simulate_substages(progress_manager, "内容分析", ["关键词提取", "兴趣评分", "片段排序"], per_substage_seconds=0.35)
        _simulate_substages(progress_manager, "切片生成", ["片段选择", "视频剪切", "文件输出"], per_substage_seconds=0.25)
        main_window.update_status("处理完成 ✅")
    except Exception as e:  # noqa: BLE001
        logging.error(f"管线执行失败: {e}")
        main_window.update_status("处理失败 ❌")
    finally:
        progress_manager.finish_processing()
        if callback:
            try:
                callback()
            except Exception:  # noqa: BLE001
                pass

