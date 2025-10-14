"""Migrated smart_progress_predictor from interest_rating with adjustments.

Changes:
 - History file stored relative to package (processing/processing_history.json) ensuring directory exists.
 - Removed shebang and encoding comments.
 - Kept Chinese comments/messages.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

__all__ = ["SmartProgressPredictor", "SimplePredictor"]


class SmartProgressPredictor:
    """基于历史记录的智能进度预测器"""

    def __init__(self):
        self.stages: Dict[str, Dict[str, Any]] = {}
        self.start_time: Optional[float] = None
        self.total_predicted_time: float = 0
        self.stage_weights = {
            "音频提取": 0.1,
            "说话人分离": 0.15,
            "音频转录": 0.4,
            "情感分析": 0.2,
            "切片生成": 0.15,
        }

        base_dir = os.path.dirname(os.path.abspath(__file__))
        processing_dir = os.path.join(base_dir, "processing")
        self.history_file = os.path.join(processing_dir, "processing_history.json")
        self.current_session: Optional[Dict[str, Any]] = None
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        self.history_data = self._load_history()

    # -------------- History --------------
    def _load_history(self) -> Dict[str, List[Dict]]:
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logging.info(
                        f"📊 加载了 {sum(len(records) for records in data.values())} 条历史处理记录"
                    )
                    return data
            logging.info("📊 未找到历史记录文件，创建新的历史数据库")
            return {"video_sessions": []}
        except Exception as e:  # noqa: BLE001
            logging.warning(f"加载历史记录失败: {e}")
            return {"video_sessions": []}

    def _save_history(self):
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
            logging.debug("📊 历史记录已保存")
        except Exception as e:  # noqa: BLE001
            logging.warning(f"保存历史记录失败: {e}")

    # -------------- Session --------------
    def start_session(self, duration_seconds: float, size_mb: float, video_path: str | None = None):
        self.current_session = {
            "start_time": time.time(),
            "duration_seconds": duration_seconds,
            "size_mb": size_mb,
            "video_path": video_path,
            "stages": {},
            "total_time": None,
            "success": False,
        }
        logging.info(f"📊 开始新的处理会话: {duration_seconds/60:.1f}分钟, {size_mb:.1f}MB")

    def end_session(self, success: bool = True):
        if not self.current_session:
            return
        self.current_session["total_time"] = time.time() - self.current_session["start_time"]
        self.current_session["success"] = success
        self.current_session["timestamp"] = datetime.now().isoformat()
        self.history_data["video_sessions"].append(self.current_session.copy())
        if len(self.history_data["video_sessions"]) > 100:
            self.history_data["video_sessions"] = self.history_data["video_sessions"][-100:]
        self._save_history()
        logging.info(
            f"📊 处理会话结束: 总用时 {self.current_session['total_time']:.1f}秒, 成功: {success}"
        )
        self.current_session = None

    # -------------- Prediction --------------
    def predict_video_processing_time(self, duration_seconds: float, size_mb: float) -> str:
        try:
            historical_prediction = self._predict_from_history(duration_seconds, size_mb)
            if historical_prediction:
                return historical_prediction
            return self._predict_from_experience(duration_seconds, size_mb)
        except Exception as e:  # noqa: BLE001
            logging.warning(f"预测处理时间时出错: {e}")
            return "无法预测"

    def _predict_from_history(self, duration_seconds: float, size_mb: float) -> Optional[str]:
        sessions = self.history_data.get("video_sessions", [])
        successful_sessions = [s for s in sessions if s.get("success", False) and s.get("total_time")]
        if len(successful_sessions) < 2:
            logging.info("📊 历史记录不足，使用经验预测")
            return None
        similar_sessions = []
        duration_minutes = duration_seconds / 60
        for session in successful_sessions:
            session_duration = session.get("duration_seconds", 0) / 60
            session_size = session.get("size_mb", 0)
            duration_diff = abs(duration_minutes - session_duration) / max(duration_minutes, session_duration, 1)
            size_diff = abs(size_mb - session_size) / max(size_mb, session_size, 1)
            similarity_score = 1 - (duration_diff * 0.6 + size_diff * 0.4)
            if similarity_score > 0.2:
                denom = session.get("duration_seconds", 0) or 1
                similar_sessions.append(
                    {
                        "session": session,
                        "similarity": similarity_score,
                        "processing_rate": session["total_time"] / denom,
                    }
                )
        if not similar_sessions:
            rates = [s["total_time"] / (s.get("duration_seconds", 1) or 1) for s in successful_sessions[-10:]]
            if rates:
                avg_rate = sum(rates) / len(rates)
                predicted_seconds = duration_seconds * avg_rate * 1.15
                logging.info(
                    f"📊 基于全局平均率预测: {predicted_seconds:.1f}秒 (avg_rate: {avg_rate:.3f})"
                )
                return self._format_time(predicted_seconds)
            logging.info("📊 历史率不可用，回退经验预测")
            return None
        similar_sessions.sort(key=lambda x: x["similarity"], reverse=True)
        top_k = min(8, len(similar_sessions))
        top_similar = similar_sessions[:top_k]
        total_weight = sum(s["similarity"] for s in top_similar)
        weighted_rate = sum(s["processing_rate"] * s["similarity"] for s in top_similar) / max(total_weight, 1e-6)
        predicted_seconds = duration_seconds * weighted_rate
        predicted_seconds *= 1.15
        logging.info(
            f"📊 基于 {top_k} 条相似记录预测: {predicted_seconds:.1f}秒 (处理率: {weighted_rate:.3f})"
        )
        return self._format_time(predicted_seconds)

    def _predict_from_experience(self, duration_seconds: float, size_mb: float) -> str:
        base_time = duration_seconds * 0.5
        size_factor = min(size_mb / 1000, 2.0)
        duration_minutes = duration_seconds / 60
        if duration_minutes > 120:
            duration_factor = 1.5
        elif duration_minutes > 60:
            duration_factor = 1.2
        else:
            duration_factor = 1.0
        predicted_seconds = base_time * size_factor * duration_factor
        self.total_predicted_time = predicted_seconds
        logging.info(f"📊 使用经验预测: {predicted_seconds:.1f}秒")
        return self._format_time(predicted_seconds)

    def _format_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}秒"
        if seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}分钟"
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}小时{minutes}分钟"

    # -------------- Stage Ops --------------
    def start_stage(self, stage_name: str, estimated_items: int = 1):
        try:
            stage_start_time = time.time()
            self.stages[stage_name] = {
                'start_time': stage_start_time,
                'estimated_items': estimated_items,
                'completed_items': 0,
                'status': 'running',
            }
            if self.current_session:
                self.current_session["stages"][stage_name] = {
                    "start_time": stage_start_time,
                    "estimated_items": estimated_items,
                    "status": "running",
                }
            if self.start_time is None:
                self.start_time = stage_start_time
            logging.debug(f"🚀 启动阶段: {stage_name} (预估{estimated_items}项)")
        except Exception as e:  # noqa: BLE001
            logging.warning(f"启动阶段 {stage_name} 时出错: {e}")

    def update_stage_progress(self, stage_name: str, progress: float, completed_items: int | None = None):
        try:
            if stage_name not in self.stages:
                return
            stage = self.stages[stage_name]
            stage['progress'] = min(max(progress, 0.0), 1.0)
            if completed_items is not None:
                stage['completed_items'] = completed_items
            if progress > 0.1:
                elapsed = time.time() - stage['start_time']
                estimated_total = elapsed / progress
                remaining = estimated_total - elapsed
                stage['estimated_remaining'] = max(remaining, 0)
            logging.debug(f"📊 {stage_name}: {progress*100:.1f}%")
        except Exception as e:  # noqa: BLE001
            logging.warning(f"更新阶段进度 {stage_name} 时出错: {e}")

    def finish_stage(self, stage_name: str):
        try:
            if stage_name in self.stages:
                stage = self.stages[stage_name]
                end_time = time.time()
                stage['status'] = 'completed'
                stage['end_time'] = end_time
                stage['progress'] = 1.0
                duration = end_time - stage['start_time']
                if self.current_session and stage_name in self.current_session["stages"]:
                    self.current_session["stages"][stage_name].update({
                        "end_time": end_time,
                        "duration": duration,
                        "status": "completed",
                    })
                logging.debug(f"✅ 完成阶段: {stage_name} (耗时{duration:.1f}秒)")
        except Exception as e:  # noqa: BLE001
            logging.warning(f"完成阶段 {stage_name} 时出错: {e}")

    # -------------- Status / Stats --------------
    def get_overall_progress(self) -> float:
        try:
            if not self.stages:
                return 0.0
            total_weight = 0.0
            weighted_progress = 0.0
            for stage_name, stage in self.stages.items():
                weight = self.stage_weights.get(stage_name, 0.1)
                progress = stage.get('progress', 0.0)
                total_weight += weight
                weighted_progress += weight * progress
            return weighted_progress / total_weight if total_weight > 0 else 0.0
        except Exception as e:  # noqa: BLE001
            logging.warning(f"计算整体进度时出错: {e}")
            return 0.0

    def get_estimated_remaining_time(self) -> Optional[str]:
        try:
            if not self.start_time or not self.total_predicted_time:
                return None
            elapsed = time.time() - self.start_time
            overall_progress = self.get_overall_progress()
            if overall_progress < 0.05:
                return None
            estimated_total = elapsed / overall_progress
            remaining = estimated_total - elapsed
            if remaining < 0:
                return "即将完成"
            if remaining < 60:
                return f"{int(remaining)}秒"
            if remaining < 3600:
                return f"{int(remaining/60)}分钟"
            hours = int(remaining / 3600)
            minutes = int((remaining % 3600) / 60)
            return f"{hours}小时{minutes}分钟"
        except Exception as e:  # noqa: BLE001
            logging.warning(f"计算剩余时间时出错: {e}")
            return None

    def get_stage_status(self, stage_name: str) -> Dict[str, Any]:
        return self.stages.get(stage_name, {})

    def get_prediction_stats(self) -> Dict[str, Any]:
        sessions = self.history_data.get("video_sessions", [])
        successful_sessions = [s for s in sessions if s.get("success", False) and s.get("total_time")]
        if not successful_sessions:
            return {"total_sessions": 0, "message": "暂无历史记录"}
        total_time = sum(s["total_time"] for s in successful_sessions)
        avg_processing_rate = statistics.mean(
            s["total_time"] / s["duration_seconds"]
            for s in successful_sessions
            if s.get("duration_seconds", 0) > 0
        )
        small_files = [s for s in successful_sessions if s.get("size_mb", 0) < 500]
        large_files = [s for s in successful_sessions if s.get("size_mb", 0) >= 500]
        stats: Dict[str, Any] = {
            "total_sessions": len(successful_sessions),
            "total_processing_time": f"{total_time/3600:.1f}小时",
            "average_rate": f"{avg_processing_rate:.2f}倍实时",
            "small_files_count": len(small_files),
            "large_files_count": len(large_files),
        }
        if small_files:
            small_avg_rate = statistics.mean(s["total_time"] / s["duration_seconds"] for s in small_files)
            stats["small_files_avg_rate"] = f"{small_avg_rate:.2f}倍实时"
        if large_files:
            large_avg_rate = statistics.mean(s["total_time"] / s["duration_seconds"] for s in large_files)
            stats["large_files_avg_rate"] = f"{large_avg_rate:.2f}倍实时"
        return stats

    def reset(self):  # noqa: D401
        self.stages.clear()
        self.start_time = None
        self.total_predicted_time = 0
        logging.debug("🔄 智能进度预测器已重置")


class SimplePredictor:
    """简化版进度预测器，用于智能预测器不可用时的fallback"""

    def predict_video_processing_time(self, duration_seconds: float, size_mb: float) -> str:  # noqa: D401
        minutes = duration_seconds / 60
        estimated_minutes = int(minutes * 0.5)
        max_minutes = int(minutes * 1.0)
        if estimated_minutes < 1:
            return "1-2分钟"
        return f"{estimated_minutes}-{max_minutes}分钟"

    def start_stage(self, stage_name: str, estimated_items: int = 1):  # noqa: D401
        pass

    def update_stage_progress(self, stage_name: str, progress: float, completed_items: int | None = None):  # noqa: D401
        pass

    def finish_stage(self, stage_name: str):  # noqa: D401
        pass

    def get_overall_progress(self) -> float:  # noqa: D401
        return 0.0

    def get_estimated_remaining_time(self) -> Optional[str]:  # noqa: D401
        return None

    def reset(self):  # noqa: D401
        pass
