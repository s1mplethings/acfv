#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
智能进度预测器模块
提供基于历史记录的视频处理时间和进度预测功能
"""

import time
import logging
import json
import statistics
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

from acfv.runtime.storage import processing_path


class SmartProgressPredictor:
    """基于历史记录的智能进度预测器"""
    
    def __init__(self):
        self.stages = {}
        self.start_time = None
        self.total_predicted_time = 0
        self.stage_weights = {
            "音频提取": 0.1,
            "说话人分离": 0.15,
            "音频转录": 0.4,
            "情感分析": 0.2,
            "切片生成": 0.15
        }
        
        # 🆕 历史记录相关（运行时 processing 目录）
        self.history_file = processing_path("processing_history.json")
        self.legacy_history_file = Path(__file__).resolve().parent / "processing" / "processing_history.json"
        self.current_session = None
        
        # 确保history目录存在再加载
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.history_data = self._load_history()
    
    def _load_history(self) -> Dict[str, List[Dict]]:
        """加载历史处理记录"""
        try:
            if self.history_file.exists():
                with self.history_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    logging.info(f"📊 加载了 {sum(len(records) for records in data.values())} 条历史处理记录")
                    return data
            if self.legacy_history_file.exists():
                with self.legacy_history_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                logging.info("加载了旧位置的历史记录，将迁移到运行时目录")
                try:
                    with self.history_file.open('w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logging.warning(f"迁移历史记录失败: {e}")
                return data
            logging.info("📊 未找到历史记录文件，创建新的历史数据库")
            return {"video_sessions": []}
        except Exception as e:
            logging.warning(f"加载历史记录失败: {e}")
            return {"video_sessions": []}
    
    def _save_history(self):
        """保存历史记录到文件"""
        try:
            with self.history_file.open('w', encoding='utf-8') as f:
                json.dump(self.history_data, f, ensure_ascii=False, indent=2)
            logging.debug("📊 历史记录已保存")
        except Exception as e:
            logging.warning(f"保存历史记录失败: {e}")
    
    def start_session(self, duration_seconds: float, size_mb: float, video_path: str = None):
        """🆕 开始新的处理会话"""
        self.current_session = {
            "start_time": time.time(),
            "duration_seconds": duration_seconds,
            "size_mb": size_mb,
            "video_path": video_path,
            "stages": {},
            "total_time": None,
            "success": False
        }
        logging.info(f"📊 开始新的处理会话: {duration_seconds/60:.1f}分钟, {size_mb:.1f}MB")
    
    def end_session(self, success: bool = True):
        """🆕 结束当前处理会话并保存记录"""
        if not self.current_session:
            return
            
        self.current_session["total_time"] = time.time() - self.current_session["start_time"]
        self.current_session["success"] = success
        self.current_session["timestamp"] = datetime.now().isoformat()
        
        # 添加到历史记录
        self.history_data["video_sessions"].append(self.current_session.copy())
        
        # 只保留最近100条记录以避免文件过大
        if len(self.history_data["video_sessions"]) > 100:
            self.history_data["video_sessions"] = self.history_data["video_sessions"][-100:]
        
        self._save_history()
        
        logging.info(f"📊 处理会话结束: 总用时 {self.current_session['total_time']:.1f}秒, 成功: {success}")
        self.current_session = None
    
    def predict_video_processing_time(self, duration_seconds: float, size_mb: float) -> str:
        """
        🆕 基于历史记录的智能时间预测
        
        Args:
            duration_seconds: 视频时长（秒）
            size_mb: 视频文件大小（MB）
            
        Returns:
            预测的处理时间字符串
        """
        try:
            # 🆕 优先使用历史记录预测
            historical_prediction = self._predict_from_history(duration_seconds, size_mb)
            if historical_prediction:
                return historical_prediction
            
            # 如果没有足够的历史数据，使用经验预测
            return self._predict_from_experience(duration_seconds, size_mb)
                
        except Exception as e:
            logging.warning(f"预测处理时间时出错: {e}")
            return "无法预测"
    
    def _predict_from_history(self, duration_seconds: float, size_mb: float) -> Optional[str]:
        """🆕 基于历史记录预测处理时间"""
        sessions = self.history_data.get("video_sessions", [])
        successful_sessions = [s for s in sessions if s.get("success", False) and s.get("total_time")]
        
        # 🆕 降低历史记录门槛（2条即可启用历史预测）
        if len(successful_sessions) < 2:
            logging.info("📊 历史记录不足，使用经验预测")
            return None
        
        # 查找相似的视频记录
        similar_sessions = []
        duration_minutes = duration_seconds / 60
        
        for session in successful_sessions:
            session_duration = session.get("duration_seconds", 0) / 60
            session_size = session.get("size_mb", 0)
            
            # 计算相似度分数 (时长和大小的加权相似度)
            duration_diff = abs(duration_minutes - session_duration) / max(duration_minutes, session_duration, 1)
            size_diff = abs(size_mb - session_size) / max(size_mb, session_size, 1)
            similarity_score = 1 - (duration_diff * 0.6 + size_diff * 0.4)
            
            # 🆕 放宽相似度阈值
            if similarity_score > 0.2:
                denom = session.get("duration_seconds", 0) or 1
                similar_sessions.append({
                    "session": session,
                    "similarity": similarity_score,
                    "processing_rate": session["total_time"] / denom  # 秒/秒
                })
        
        # 🆕 如果没有相似样本，使用全局平均处理率作为退路
        if not similar_sessions:
            rates = [s["total_time"] / (s.get("duration_seconds", 1) or 1) for s in successful_sessions[-10:]]
            if rates:
                avg_rate = sum(rates) / len(rates)
                predicted_seconds = duration_seconds * avg_rate * 1.15  # 加安全余量
                logging.info(f"📊 基于全局平均率预测: {predicted_seconds:.1f}秒 (avg_rate: {avg_rate:.3f})")
                self.total_predicted_time = predicted_seconds
                return self._format_time(predicted_seconds)
            logging.info("📊 历史率不可用，回退经验预测")
            return None
        
        # 按相似度排序，取更多邻居
        similar_sessions.sort(key=lambda x: x["similarity"], reverse=True)
        top_k = min(8, len(similar_sessions))
        top_similar = similar_sessions[:top_k]
        
        # 计算加权平均处理率
        total_weight = sum(s["similarity"] for s in top_similar)
        weighted_rate = sum(s["processing_rate"] * s["similarity"] for s in top_similar) / max(total_weight, 1e-6)
        
        # 预测处理时间
        predicted_seconds = duration_seconds * weighted_rate
        
        # 添加一些安全余量（10-20%）
        predicted_seconds *= 1.15
        
        logging.info(f"📊 基于 {top_k} 条相似记录预测: {predicted_seconds:.1f}秒 (处理率: {weighted_rate:.3f})")
        
        self.total_predicted_time = predicted_seconds
        
        return self._format_time(predicted_seconds)
    
    def _predict_from_experience(self, duration_seconds: float, size_mb: float) -> str:
        """基于经验的处理时间预测（原有逻辑）"""
        # 基础时间：每分钟视频约需要30-60秒处理
        base_time = duration_seconds * 0.5  # 基础处理时间
        
        # 根据文件大小调整
        size_factor = min(size_mb / 1000, 2.0)  # 最多增加2倍时间
        
        # 根据视频长度调整
        duration_minutes = duration_seconds / 60
        if duration_minutes > 120:  # 超过2小时的视频
            duration_factor = 1.5
        elif duration_minutes > 60:  # 超过1小时的视频
            duration_factor = 1.2
        else:
            duration_factor = 1.0
        
        predicted_seconds = base_time * size_factor * duration_factor
        self.total_predicted_time = predicted_seconds
        
        logging.info(f"📊 使用经验预测: {predicted_seconds:.1f}秒")
        return self._format_time(predicted_seconds)
    
    def _format_time(self, seconds: float) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}分钟"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}小时{minutes}分钟"
    
    def start_stage(self, stage_name: str, estimated_items: int = 1):
        """
        启动一个处理阶段
        
        Args:
            stage_name: 阶段名称
            estimated_items: 预估处理项目数
        """
        try:
            stage_start_time = time.time()
            self.stages[stage_name] = {
                'start_time': stage_start_time,
                'estimated_items': estimated_items,
                'completed_items': 0,
                'status': 'running'
            }
            
            # 🆕 记录到当前会话
            if self.current_session:
                self.current_session["stages"][stage_name] = {
                    "start_time": stage_start_time,
                    "estimated_items": estimated_items,
                    "status": "running"
                }
            
            if self.start_time is None:
                self.start_time = stage_start_time
                
            logging.debug(f"🚀 启动阶段: {stage_name} (预估{estimated_items}项)")
            
        except Exception as e:
            logging.warning(f"启动阶段 {stage_name} 时出错: {e}")
    
    def update_stage_progress(self, stage_name: str, progress: float, completed_items: int = None):
        """
        更新阶段进度
        
        Args:
            stage_name: 阶段名称
            progress: 进度百分比 (0.0-1.0)
            completed_items: 已完成项目数
        """
        try:
            if stage_name not in self.stages:
                return
            
            stage = self.stages[stage_name]
            stage['progress'] = min(max(progress, 0.0), 1.0)  # 确保在0-1范围内
            
            if completed_items is not None:
                stage['completed_items'] = completed_items
            
            # 计算预估剩余时间
            if progress > 0.1:  # 避免除零错误
                elapsed = time.time() - stage['start_time']
                estimated_total = elapsed / progress
                remaining = estimated_total - elapsed
                stage['estimated_remaining'] = max(remaining, 0)
            
            logging.debug(f"📊 {stage_name}: {progress*100:.1f}%")
            
        except Exception as e:
            logging.warning(f"更新阶段进度 {stage_name} 时出错: {e}")
    
    def finish_stage(self, stage_name: str):
        """
        完成一个阶段
        
        Args:
            stage_name: 阶段名称
        """
        try:
            if stage_name in self.stages:
                stage = self.stages[stage_name]
                end_time = time.time()
                stage['status'] = 'completed'
                stage['end_time'] = end_time
                stage['progress'] = 1.0
                
                duration = end_time - stage['start_time']
                
                # 🆕 记录到当前会话
                if self.current_session and stage_name in self.current_session["stages"]:
                    self.current_session["stages"][stage_name].update({
                        "end_time": end_time,
                        "duration": duration,
                        "status": "completed"
                    })
                
                logging.debug(f"✅ 完成阶段: {stage_name} (耗时{duration:.1f}秒)")
            
        except Exception as e:
            logging.warning(f"完成阶段 {stage_name} 时出错: {e}")
            logging.warning(f"完成阶段 {stage_name} 时出错: {e}")
    
    def get_overall_progress(self) -> float:
        """
        获取整体进度
        
        Returns:
            整体进度百分比 (0.0-1.0)
        """
        try:
            if not self.stages:
                return 0.0
            
            total_weight = 0
            weighted_progress = 0
            
            for stage_name, stage in self.stages.items():
                weight = self.stage_weights.get(stage_name, 0.1)
                progress = stage.get('progress', 0.0)
                
                total_weight += weight
                weighted_progress += weight * progress
            
            return weighted_progress / total_weight if total_weight > 0 else 0.0
            
        except Exception as e:
            logging.warning(f"计算整体进度时出错: {e}")
            return 0.0
    
    def get_estimated_remaining_time(self) -> Optional[str]:
        """
        获取预估剩余时间
        
        Returns:
            剩余时间字符串，如果无法预测则返回None
        """
        try:
            if not self.start_time or not self.total_predicted_time:
                return None
            
            elapsed = time.time() - self.start_time
            overall_progress = self.get_overall_progress()
            
            if overall_progress < 0.05:  # 进度太少，无法准确预测
                return None
            
            estimated_total = elapsed / overall_progress
            remaining = estimated_total - elapsed
            
            if remaining < 0:
                return "即将完成"
            elif remaining < 60:
                return f"{int(remaining)}秒"
            elif remaining < 3600:
                return f"{int(remaining/60)}分钟"
            else:
                hours = int(remaining / 3600)
                minutes = int((remaining % 3600) / 60)
                return f"{hours}小时{minutes}分钟"
                
        except Exception as e:
            logging.warning(f"计算剩余时间时出错: {e}")
            return None
    
    def get_stage_status(self, stage_name: str) -> Dict[str, Any]:
        """
        获取阶段状态
        
        Args:
            stage_name: 阶段名称
            
        Returns:
            阶段状态字典
        """
        return self.stages.get(stage_name, {})
    
    def get_prediction_stats(self) -> Dict[str, Any]:
        """🆕 获取预测统计信息"""
        sessions = self.history_data.get("video_sessions", [])
        successful_sessions = [s for s in sessions if s.get("success", False) and s.get("total_time")]
        
        if not successful_sessions:
            return {"total_sessions": 0, "message": "暂无历史记录"}
        
        # 计算统计数据
        total_time = sum(s["total_time"] for s in successful_sessions)
        avg_processing_rate = statistics.mean(
            s["total_time"] / s["duration_seconds"] 
            for s in successful_sessions 
            if s.get("duration_seconds", 0) > 0
        )
        
        # 按文件大小分类统计
        small_files = [s for s in successful_sessions if s.get("size_mb", 0) < 500]  # <500MB
        large_files = [s for s in successful_sessions if s.get("size_mb", 0) >= 500]  # >=500MB
        
        stats = {
            "total_sessions": len(successful_sessions),
            "total_processing_time": f"{total_time/3600:.1f}小时",
            "average_rate": f"{avg_processing_rate:.2f}倍实时",
            "small_files_count": len(small_files),
            "large_files_count": len(large_files)
        }
        
        if small_files:
            small_avg_rate = statistics.mean(s["total_time"] / s["duration_seconds"] for s in small_files)
            stats["small_files_avg_rate"] = f"{small_avg_rate:.2f}倍实时"
            
        if large_files:
            large_avg_rate = statistics.mean(s["total_time"] / s["duration_seconds"] for s in large_files)
            stats["large_files_avg_rate"] = f"{large_avg_rate:.2f}倍实时"
        
        return stats
    
    def reset(self):
        """重置预测器状态"""
        self.stages.clear()
        self.start_time = None
        self.total_predicted_time = 0
        # 不清除历史记录，只重置当前状态
        logging.debug("🔄 智能进度预测器已重置")


# 简化版预测器，用作fallback
class SimplePredictor:
    """简化版进度预测器，用于智能预测器不可用时的fallback"""
    
    def predict_video_processing_time(self, duration_seconds: float, size_mb: float) -> str:
        """简单的时间预测"""
        minutes = duration_seconds / 60
        # 简单估算：每分钟视频需要0.5-1分钟处理
        estimated_minutes = int(minutes * 0.5)
        max_minutes = int(minutes * 1.0)
        
        if estimated_minutes < 1:
            return "1-2分钟"
        else:
            return f"{estimated_minutes}-{max_minutes}分钟"
    
    def start_stage(self, stage_name: str, estimated_items: int = 1):
        """空实现"""
        pass
    
    def update_stage_progress(self, stage_name: str, progress: float, completed_items: int = None):
        """空实现"""
        pass
    
    def finish_stage(self, stage_name: str):
        """空实现"""
        pass
    
    def get_overall_progress(self) -> float:
        """返回0，表示无法预测"""
        return 0.0
    
    def get_estimated_remaining_time(self) -> Optional[str]:
        """返回None，表示无法预测"""
        return None
    
    def reset(self):
        """空实现"""
        pass
