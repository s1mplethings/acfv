"""Migrated progress_manager from interest_rating (Phase 1).

Modifications:
 - Removed shebang and encoding comment.
 - Ensured no absolute file paths; history file path stays relative (caller may override).
 - No logging reconfiguration; uses existing global logging.
 - Kept Chinese identifiers / messages for continuity.
"""
from __future__ import annotations

import json
import time
import logging
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

__all__ = ["StageInfo", "ProgressManager"]


@dataclass
class StageInfo:
    name: str
    substages: List[str]
    weight: float
    current_substage: int = 0
    substage_progress: float = 0.0
    start_time: Optional[float] = None
    estimated_duration: float = 60


class ProgressManager:
    def __init__(self, history_file: str = "processing/progress_history.json"):
        self.history_file = history_file
        self.current_stages = {}
        self.total_start_time = None
        self.current_stage_index = 0
        self.stages = [
            StageInfo("音频提取", ["初始化", "提取音轨", "格式转换"], 0.15),
            StageInfo("说话人分离", ["加载模型", "音频分析", "说话人分离", "后处理"], 0.20),
            StageInfo("语音转录", ["加载Whisper", "音频切分", "转录处理", "文本优化"], 0.25),
            StageInfo("情感分析", ["加载模型", "文本分析", "情感评分"], 0.15),
            StageInfo("内容分析", ["关键词提取", "兴趣评分", "片段排序"], 0.15),
            StageInfo("切片生成", ["片段选择", "视频剪切", "文件输出"], 0.10),
        ]
        self.history_data = self._load_history()

    # ---------------- History -----------------
    def _load_history(self) -> Dict:
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:  # noqa: BLE001
            logging.warning(f"加载历史数据失败: {e}")
        return {"completed_sessions": [], "stage_averages": {}, "video_size_factors": {}}

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logging.error(f"保存历史数据失败: {e}")

    # ---------------- Lifecycle ---------------
    def start_processing(self, video_duration: float = 0, file_size: float = 0):
        self.total_start_time = time.time()
        self.current_stage_index = 0
        for stage in self.stages:
            stage.current_substage = 0
            stage.substage_progress = 0.0
            stage.start_time = None
        self._update_estimates(video_duration, file_size)
        logging.info("进度管理器已启动")

    def finish_processing(self):
        if self.total_start_time:
            total_duration = time.time() - self.total_start_time
            session_record = {"timestamp": time.time(), "total_duration": total_duration, "stages": {}}
            for stage in self.stages:
                if stage.start_time:
                    duration = time.time() - stage.start_time
                    session_record["stages"][stage.name] = {
                        "duration": duration,
                        "substages": stage.substages,
                        "weight": stage.weight,
                    }
            self.history_data["completed_sessions"].append(session_record)
            self._save_history()
            logging.info(f"处理完成，总耗时: {self._format_time(total_duration)}")
            self.total_start_time = None

    def stop_processing(self):
        try:
            self.total_start_time = None
            self.current_stage_index = 0
            for stage in self.stages:
                stage.current_substage = 0
                stage.substage_progress = 0.0
                stage.start_time = None
            logging.info("进度管理器已停止")
        except Exception as e:  # noqa: BLE001
            logging.error(f"停止进度管理器失败: {e}")

    # ---------------- Public Query -------------
    def get_progress_data(self) -> Dict:
        try:
            overall_progress, current_stage, eta = self.get_overall_progress()
            return {
                "percentage": overall_progress,
                "current_stage": current_stage,
                "eta": eta,
                "total_start_time": self.total_start_time,
                "current_stage_index": self.current_stage_index,
            }
        except Exception as e:  # noqa: BLE001
            logging.error(f"获取进度数据失败: {e}")
            return {"percentage": 0, "current_stage": "未知", "eta": "计算中...", "total_start_time": None, "current_stage_index": 0}

    def get_history_summary(self) -> List[Dict]:
        return self.history_data.get("completed_sessions", [])

    # ---------------- Internals ----------------
    def _get_filtered_stage_average(self, stage_name: str) -> float:
        try:
            history = self.history_data.get("stages", {}).get(stage_name, [])
            filtered = [x for x in history if 1 <= x <= 600]
            if not filtered:
                return self.stages[self._get_stage_index(stage_name)].estimated_duration if hasattr(self, '_get_stage_index') else 60
            filtered.sort(); n = len(filtered)
            return filtered[n//2] if n % 2 == 1 else (filtered[n//2-1] + filtered[n//2]) / 2
        except Exception:  # noqa: BLE001
            return 60

    def _get_stage_index(self, stage_name: str) -> int:
        for i, stage in enumerate(self.stages):
            if stage.name == stage_name:
                return i
        return 0

    def _update_estimates(self, video_duration: float, file_size: float):
        base_estimates = {
            "音频提取": max(1, video_duration / 10),
            "说话人分离": max(2, video_duration / 5),
            "语音转录": max(3, video_duration / 3),
            "情感分析": max(1, video_duration / 15),
            "内容分析": max(1, video_duration / 20),
            "切片生成": max(1, video_duration / 30),
        }
        size_factor = max(1.0, file_size / 1024 / 1024 / 1024 * 0.3 + 1.0)
        for stage in self.stages:
            base_time = base_estimates.get(stage.name, 60)
            median_time = self._get_filtered_stage_average(stage.name)
            base_time = median_time * 0.7 + base_time * 0.3
            stage.estimated_duration = base_time * size_factor * 60

    # ---------------- Stage Ops ----------------
    def start_stage(self, stage_name: str):
        stage = self._get_stage(stage_name)
        if stage:
            stage.start_time = time.time()
            stage.current_substage = 0
            stage.substage_progress = 0.0
            logging.info(f"开始阶段: {stage_name}")

    def update_substage(self, stage_name: str, substage_index: int, progress: float = 0.0):
        stage = self._get_stage(stage_name)
        if stage:
            stage.current_substage = substage_index
            stage.substage_progress = max(0.0, min(1.0, progress))

    def update_stage_progress(self, stage_name: str, substage_index: int, progress: float = 0.0):
        return self.update_substage(stage_name, substage_index, progress)

    def finish_stage(self, stage_name: str):
        stage = self._get_stage(stage_name)
        if stage and stage.start_time:
            duration = time.time() - stage.start_time
            if "stage_averages" not in self.history_data:
                self.history_data["stage_averages"] = {}
            current_avg = self.history_data["stage_averages"].get(stage_name, duration)
            self.history_data["stage_averages"][stage_name] = current_avg * 0.7 + duration * 0.3
            self._save_history()
            logging.info(f"完成阶段: {stage_name}, 用时: {duration:.1f}秒")

    # ---------------- Progress Calc ------------
    def get_overall_progress(self) -> Tuple[float, str, str]:
        if not self.total_start_time:
            return 0.0, "准备中...", "计算中..."
        total_progress = 0.0
        current_stage_name = ""
        current_substage_name = ""
        for i, stage in enumerate(self.stages):
            if i < self.current_stage_index:
                total_progress += stage.weight
            elif i == self.current_stage_index:
                current_stage_name = stage.name
                if stage.current_substage < len(stage.substages):
                    current_substage_name = stage.substages[stage.current_substage]
                substages_count = len(stage.substages)
                stage_progress = (stage.current_substage + stage.substage_progress) / substages_count
                total_progress += stage.weight * stage_progress
                break
        status_text = f"{current_stage_name} - {current_substage_name}" if current_stage_name and current_substage_name else (current_stage_name or "处理中...")
        eta = self._calculate_eta(total_progress)
        return total_progress, status_text, eta

    def _calculate_eta(self, current_progress: float) -> str:
        if not self.total_start_time or current_progress <= 0:
            try:
                stage = self.stages[self.current_stage_index]
                est = stage.estimated_duration
                if est > 3600:
                    return f"预计 {int(est/3600)}小时{int((est%3600)/60)}分"
                if est > 60:
                    return f"预计 {int(est/60)}分{int(est%60)}秒"
                return f"预计 {int(est)}秒"
            except Exception:  # noqa: BLE001
                return "预计中..."
        elapsed = time.time() - self.total_start_time
        if current_progress >= 0.99:
            return "即将完成"
        try:
            total_estimated = elapsed / max(current_progress, 0.01)
            remaining = total_estimated - elapsed
            if self.history_data.get("stage_averages"):
                historical_remaining = 0
                for i in range(self.current_stage_index, len(self.stages)):
                    stage_name = self.stages[i].name
                    historical_remaining += self.history_data["stage_averages"].get(stage_name, self.stages[i].estimated_duration)
                remaining = remaining * 0.6 + historical_remaining * 0.4
            if remaining < 60:
                stage = self.stages[self.current_stage_index]
                est = stage.estimated_duration
                if est > remaining:
                    remaining = est
            return self._format_time(remaining)
        except Exception:  # noqa: BLE001
            return "预计中..."

    def _format_time(self, seconds: float) -> str:
        if seconds < 0:
            return "即将完成"
        if seconds < 60:
            return f"{int(seconds)}秒"
        if seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}分{secs}秒"
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}时{minutes}分"

    def _get_stage(self, stage_name: str) -> Optional[StageInfo]:
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        return None

    def next_stage(self):
        if self.current_stage_index < len(self.stages) - 1:
            self.current_stage_index += 1

    def get_eta(self) -> str:
        progress_info = self.get_overall_progress()
        current_progress = progress_info[0]
        return self._calculate_eta(current_progress)

    def get_stage_details(self) -> Dict:
        if self.current_stage_index >= len(self.stages):
            return {"stage_name": "已完成", "substage_name": "处理完成", "stage_progress": 1.0, "substages": [], "current_substage_index": 0}
        current_stage = self.stages[self.current_stage_index]
        return {
            "stage_name": current_stage.name,
            "substage_name": current_stage.substages[current_stage.current_substage] if current_stage.current_substage < len(current_stage.substages) else "完成",
            "stage_progress": (current_stage.current_substage + current_stage.substage_progress) / len(current_stage.substages),
            "substages": current_stage.substages,
            "current_substage_index": current_stage.current_substage,
        }
