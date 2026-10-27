import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

class ClipProcessingTracker:
    """切片处理次数跟踪器"""
    
    def __init__(self, base_dir: str = "processing"):
        self.base_dir = base_dir
        self.tracking_file = os.path.join(base_dir, "clip_processing_history.json")
        self.processing_data = self._load_processing_data()
    
    def _load_processing_data(self) -> Dict:
        """加载处理历史数据"""
        try:
            if os.path.exists(self.tracking_file):
                with open(self.tracking_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.warning(f"加载处理历史数据失败: {e}")
        return {}
    
    def _save_processing_data(self):
        """保存处理历史数据"""
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            with open(self.tracking_file, 'w', encoding='utf-8') as f:
                json.dump(self.processing_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"保存处理历史数据失败: {e}")
    
    def record_processing(self, video_dir: str, clip_file: str, processing_type: str = "rag_annotation"):
        """记录切片处理"""
        clip_key = f"{video_dir}/{clip_file}"
        
        if clip_key not in self.processing_data:
            self.processing_data[clip_key] = {
                "processing_count": 0,
                "first_processed": None,
                "last_processed": None,
                "processing_history": []
            }
        
        # 更新处理次数
        self.processing_data[clip_key]["processing_count"] += 1
        
        # 更新时间戳
        current_time = datetime.now().isoformat()
        if not self.processing_data[clip_key]["first_processed"]:
            self.processing_data[clip_key]["first_processed"] = current_time
        self.processing_data[clip_key]["last_processed"] = current_time
        
        # 记录处理历史
        history_entry = {
            "timestamp": current_time,
            "type": processing_type,
            "count": self.processing_data[clip_key]["processing_count"]
        }
        self.processing_data[clip_key]["processing_history"].append(history_entry)
        
        # 只保留最近20次处理记录
        if len(self.processing_data[clip_key]["processing_history"]) > 20:
            self.processing_data[clip_key]["processing_history"] = \
                self.processing_data[clip_key]["processing_history"][-20:]
        
        self._save_processing_data()
        
        logging.info(f"记录切片处理: {clip_file} (第{self.processing_data[clip_key]['processing_count']}次)")
    
    def get_processing_count(self, video_dir: str, clip_file: str) -> int:
        """获取切片处理次数"""
        clip_key = f"{video_dir}/{clip_file}"
        return self.processing_data.get(clip_key, {}).get("processing_count", 0)
    
    def get_processing_info(self, video_dir: str, clip_file: str) -> Dict:
        """获取切片处理详细信息"""
        clip_key = f"{video_dir}/{clip_file}"
        return self.processing_data.get(clip_key, {
            "processing_count": 0,
            "first_processed": None,
            "last_processed": None,
            "processing_history": []
        })
    
    def get_video_processing_stats(self, video_dir: str) -> Dict:
        """获取视频的处理统计信息"""
        stats = {
            "total_clips": 0,
            "processed_clips": 0,
            "total_processing_count": 0,
            "avg_processing_count": 0,
            "most_processed_clip": None,
            "recently_processed": []
        }
        
        for clip_key, data in self.processing_data.items():
            if clip_key.startswith(video_dir):
                stats["total_clips"] += 1
                if data["processing_count"] > 0:
                    stats["processed_clips"] += 1
                    stats["total_processing_count"] += data["processing_count"]
                    
                    # 记录处理次数最多的切片
                    if not stats["most_processed_clip"] or \
                       data["processing_count"] > stats["most_processed_clip"]["count"]:
                        stats["most_processed_clip"] = {
                            "clip": clip_key.split("/")[-1],
                            "count": data["processing_count"]
                        }
        
        if stats["processed_clips"] > 0:
            stats["avg_processing_count"] = stats["total_processing_count"] / stats["processed_clips"]
        
        # 获取最近处理的切片
        recent_clips = []
        for clip_key, data in self.processing_data.items():
            if clip_key.startswith(video_dir) and data["last_processed"]:
                recent_clips.append({
                    "clip": clip_key.split("/")[-1],
                    "last_processed": data["last_processed"],
                    "count": data["processing_count"]
                })
        
        # 按最后处理时间排序，取最近10个
        recent_clips.sort(key=lambda x: x["last_processed"], reverse=True)
        stats["recently_processed"] = recent_clips[:10]
        
        return stats
    
    def get_processing_count_badge(self, count: int) -> str:
        """获取处理次数徽章显示"""
        if count == 0:
            return ""
        elif count == 1:
            return "🔄"
        elif count <= 3:
            return f"🔄{count}"
        elif count <= 5:
            return f"🔄🔄{count}"
        elif count <= 10:
            return f"🔄🔄🔄{count}"
        else:
            return f"🔄🔄🔄🔄{count}"
    
    def get_processing_count_color(self, count: int) -> str:
        """获取处理次数对应的颜色"""
        if count == 0:
            return "#666666"  # 灰色
        elif count == 1:
            return "#4CAF50"  # 绿色
        elif count <= 3:
            return "#FF9800"  # 橙色
        elif count <= 5:
            return "#F44336"  # 红色
        else:
            return "#9C27B0"  # 紫色
    
    def get_processing_tooltip(self, video_dir: str, clip_file: str) -> str:
        """获取处理信息的工具提示"""
        info = self.get_processing_info(video_dir, clip_file)
        count = info["processing_count"]
        
        if count == 0:
            return "未处理过"
        
        tooltip = f"处理次数: {count}次\n"
        
        if info["first_processed"]:
            first_time = datetime.fromisoformat(info["first_processed"])
            tooltip += f"首次处理: {first_time.strftime('%Y-%m-%d %H:%M')}\n"
        
        if info["last_processed"]:
            last_time = datetime.fromisoformat(info["last_processed"])
            tooltip += f"最后处理: {last_time.strftime('%Y-%m-%d %H:%M')}\n"
        
        # 添加最近的处理历史
        if info["processing_history"]:
            tooltip += "\n最近处理记录:\n"
            for entry in info["processing_history"][-5:]:  # 最近5次
                time_obj = datetime.fromisoformat(entry["timestamp"])
                tooltip += f"• {time_obj.strftime('%m-%d %H:%M')} ({entry['type']})\n"
        
        return tooltip
    
    def clear_processing_history(self, video_dir: str = None, clip_file: str = None):
        """清除处理历史"""
        if video_dir and clip_file:
            # 清除特定切片的历史
            clip_key = f"{video_dir}/{clip_file}"
            if clip_key in self.processing_data:
                del self.processing_data[clip_key]
                logging.info(f"清除切片处理历史: {clip_file}")
        elif video_dir:
            # 清除整个视频的历史
            keys_to_remove = [k for k in self.processing_data.keys() if k.startswith(video_dir)]
            for key in keys_to_remove:
                del self.processing_data[key]
            logging.info(f"清除视频处理历史: {video_dir}")
        else:
            # 清除所有历史
            self.processing_data.clear()
            logging.info("清除所有处理历史")
        
        self._save_processing_data()
    
    def export_processing_report(self, output_file: str = None) -> str:
        """导出处理报告"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(self.base_dir, f"processing_report_{timestamp}.json")
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(self.processing_data, f, ensure_ascii=False, indent=2)
            logging.info(f"处理报告已导出: {output_file}")
            return output_file
        except Exception as e:
            logging.error(f"导出处理报告失败: {e}")
            return ""
    
    def should_skip_full_processing(self, video_dir: str) -> bool:
        """判断是否应该跳过完整处理，只进行RAG评分"""
        if not self.processing_data:
            return False
        
        # 检查该视频是否有处理历史
        video_processed_clips = 0
        total_clips = 0
        
        for clip_key, data in self.processing_data.items():
            if clip_key.startswith(video_dir):
                total_clips += 1
                if data["processing_count"] > 0:
                    video_processed_clips += 1
        
        # 如果超过50%的切片已经处理过，则跳过完整处理
        if total_clips > 0 and video_processed_clips / total_clips > 0.5:
            return True
        
        return False
    
    def get_processing_strategy(self, video_dir: str) -> str:
        """获取处理策略建议"""
        if self.should_skip_full_processing(video_dir):
            return "rag_only"  # 只进行RAG评分
        else:
            return "full_processing"  # 完整处理
    
    def get_rag_focus_clips(self, video_dir: str, limit: int = 10) -> list:
        """获取需要RAG重点关注的切片（处理次数较少的）"""
        focus_clips = []
        
        for clip_key, data in self.processing_data.items():
            if clip_key.startswith(video_dir):
                clip_file = clip_key.split("/")[-1]
                processing_count = data.get("processing_count", 0)
                
                # 优先选择处理次数少的切片
                focus_clips.append({
                    "clip_file": clip_file,
                    "processing_count": processing_count,
                    "last_processed": data.get("last_processed")
                })
        
        # 按处理次数排序，处理次数少的优先
        focus_clips.sort(key=lambda x: x["processing_count"])
        
        return focus_clips[:limit]
    
    def get_processing_recommendations(self, video_dir: str) -> dict:
        """获取处理建议"""
        stats = self.get_video_processing_stats(video_dir)
        strategy = self.get_processing_strategy(video_dir)
        focus_clips = self.get_rag_focus_clips(video_dir)
        
        recommendations = {
            "strategy": strategy,
            "reason": "",
            "focus_clips": focus_clips,
            "stats": stats
        }
        
        if strategy == "rag_only":
            recommendations["reason"] = f"该视频已有 {stats['processed_clips']}/{stats['total_clips']} 个切片被处理过，建议只进行RAG评分"
        else:
            recommendations["reason"] = f"该视频处理进度较低 ({stats['processed_clips']}/{stats['total_clips']})，建议进行完整处理"
        
        return recommendations

# 使用示例
if __name__ == "__main__":
    # 创建跟踪器
    tracker = ClipProcessingTracker()
    
    # 模拟记录处理
    tracker.record_processing("video_001", "clip_001.mp4", "rag_annotation")
    tracker.record_processing("video_001", "clip_002.mp4", "rag_annotation")
    tracker.record_processing("video_001", "clip_001.mp4", "rag_annotation")  # 第二次处理
    
    # 获取处理信息
    count = tracker.get_processing_count("video_001", "clip_001.mp4")
    print(f"clip_001处理次数: {count}")
    
    # 获取徽章
    badge = tracker.get_processing_count_badge(count)
    print(f"徽章: {badge}")
    
    # 获取工具提示
    tooltip = tracker.get_processing_tooltip("video_001", "clip_001.mp4")
    print(f"工具提示:\n{tooltip}")
    
    # 获取视频统计
    stats = tracker.get_video_processing_stats("video_001")
    print(f"视频统计: {stats}") 