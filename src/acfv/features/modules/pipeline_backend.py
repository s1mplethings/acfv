# Extracted core backend functionality from main.py

from __future__ import annotations

from typing import List, Tuple

def _segment_score(seg: dict) -> float:
    for key in ("score", "interest_score", "rating", "density", "clip_score"):
        val = seg.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except Exception:
            continue
    return 0.0

def _normalize_segments_to_target(
    segments: List[dict],
    desired_count: int,
    video_duration: float,
    min_sec: float,
    target_sec: float,
    max_sec: float,
    prefer_score: bool = True,
) -> List[dict]:
    processed: List[Tuple[float, int, float, float, dict]] = []
    for idx, seg in enumerate(segments):
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except Exception:
            continue
        if end <= start:
            continue
        processed.append((_segment_score(seg), idx, start, end, seg))

    if not processed:
        return []

    highest_end = max(item[3] for item in processed)
    if not video_duration or video_duration < highest_end:
        video_duration = max(highest_end, video_duration or 0.0)

    if prefer_score:
        ordering = sorted(processed, key=lambda x: (x[0], -x[2]), reverse=True)
    else:
        ordering = sorted(processed, key=lambda x: x[2])

    selected: List[dict] = []
    used_indices = set()

    def overlaps(range_a, range_b):
        inter = min(range_a[1], range_b[1]) - max(range_a[0], range_b[0])
        if inter <= 0:
            return 0.0
        union = max(range_a[1], range_b[1]) - min(range_a[0], range_b[0])
        return inter / union if union > 0 else 0.0

    def adjust_window(start: float, end: float) -> Tuple[float, float]:
        length = end - start
        target = target_sec
        if length > max_sec:
            target = max_sec
        elif length < min_sec:
            target = target_sec
        else:
            target = max(min(length, max_sec), min_sec)
        center = (start + end) / 2.0
        start_new = center - target / 2.0
        if start_new < 0.0:
            start_new = 0.0
        end_new = start_new + target
        if end_new > video_duration:
            end_new = video_duration
            start_new = max(0.0, end_new - target)
        if end_new - start_new < min_sec:
            if end_new == video_duration:
                start_new = max(0.0, video_duration - min_sec)
                end_new = video_duration
            else:
                end_new = min(video_duration, start_new + min_sec)
        return start_new, end_new

    def add_candidate(score: float, idx_seg: int, start: float, end: float, origin: dict) -> bool:
        start_adj, end_adj = adjust_window(start, end)
        candidate_range = (start_adj, end_adj)
        for existing in selected:
            if overlaps(candidate_range, (existing['start'], existing['end'])) > 0.35:
                return False
        seg_copy = dict(origin)
        seg_copy['start'] = float(start_adj)
        seg_copy['end'] = float(end_adj)
        seg_copy['score'] = float(score)
        seg_copy['_source_index'] = idx_seg
        selected.append(seg_copy)
        used_indices.add(idx_seg)
        return True

    for score, idx_seg, start, end, seg in ordering:
        if desired_count > 0 and len(selected) >= desired_count:
            break
        add_candidate(score, idx_seg, start, end, seg)

    if desired_count > 0 and len(selected) < desired_count:
        remaining = [item for item in sorted(processed, key=lambda x: x[2]) if item[1] not in used_indices]
        for score, idx_seg, start, end, seg in remaining:
            if desired_count > 0 and len(selected) >= desired_count:
                break
            if not add_candidate(score, idx_seg, start, end, seg):
                start_adj, end_adj = adjust_window(start, end)
                seg_copy = dict(seg)
                seg_copy['start'] = float(start_adj)
                seg_copy['end'] = float(end_adj)
                seg_copy['score'] = float(score)
                seg_copy['_source_index'] = idx_seg
                selected.append(seg_copy)

    if desired_count > 0 and len(selected) > desired_count:
        selected = sorted(selected, key=lambda x: x.get('score', 0.0), reverse=True)[:desired_count]

    selected.sort(key=lambda x: float(x.get('start', 0.0)))
    for seg in selected:
        seg.pop('_source_index', None)
    return selected


import os
import json
import threading
import shutil
import importlib
import logging
import pickle
import subprocess
from pathlib import Path
import re
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("faiss 模块未安装，将跳过相关内容索引功能")
try:
    from PyQt5.QtCore import QThread, pyqtSignal
    PYTQT5_AVAILABLE = True
except ImportError:
    PYTQT5_AVAILABLE = False
    print("PyQt5 模块未安装，将跳过相关功能")

from acfv import config
from acfv.utils import safe_slug
from acfv.runtime.storage import processing_path, settings_path
import sys


def _sanitize_component(text: str) -> str:
    """Sanitize and shorten a filename component for filesystem usage."""
    return safe_slug(text, max_length=80)

# 条件导入各个模块
try:
    from acfv.processing.extract_chat import extract_chat
    EXTRACT_CHAT_AVAILABLE = True
except ImportError as e:
    EXTRACT_CHAT_AVAILABLE = False
    print(f"extract_chat 模块导入失败: {e}")

try:
    from acfv.processing.transcribe_audio import process_audio_segments
    TRANSCRIBE_AUDIO_AVAILABLE = True
except ImportError as e:
    TRANSCRIBE_AUDIO_AVAILABLE = False
    print(f"transcribe_audio 模块导入失败: {e}")

# 将analyze_data的导入移到函数内部，避免循环导入
ANALYZE_DATA_AVAILABLE = True

try:
    from utils import filter_meaningless_content, build_content_index
    UTILS_AVAILABLE = True
except ImportError as e:
    UTILS_AVAILABLE = False
    print(f"utils 模块导入失败: {e}")

try:
    from acfv.processing.clip_video import clip_video
    CLIP_VIDEO_AVAILABLE = True
except ImportError as e:
    CLIP_VIDEO_AVAILABLE = False
    print(f"clip_video 模块导入失败: {e}")

try:
    from acfv.processing.video_emotion_infer import run as infer_emotion
    VIDEO_EMOTION_AVAILABLE = True
except ImportError as e:
    VIDEO_EMOTION_AVAILABLE = False
    print(f"video_emotion_infer 模块导入失败: {e}")

# 配置日志系统
import logging.handlers
import os

# 创建logs目录
os.makedirs("logs", exist_ok=True)

# 配置日志处理器
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 清除现有的处理器
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# 文件处理器 - processing.log
file_handler = logging.handlers.RotatingFileHandler(
    "processing.log", 
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# 详细日志文件 - video_processor.log
detailed_handler = logging.handlers.RotatingFileHandler(
    "logs/video_processor.log", 
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
detailed_handler.setLevel(logging.DEBUG)
detailed_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
detailed_handler.setFormatter(detailed_formatter)
logger.addHandler(detailed_handler)

def log_info(message):
    """记录信息日志"""
    logging.info(message)
    # 确保日志立即写入文件
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.flush()


def log_error(message):
    """记录错误日志"""
    logging.error(message)
    # 确保日志立即写入文件
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.flush()

def log_warning(message):
    """记录警告日志"""
    logging.warning(message)
    # 确保日志立即写入文件
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.flush()


class ConfigManager:
    def __init__(self, config_file=None):
        self.config_file = config_file or str(settings_path("config.json"))
        self.cfg = {
            "VIDEO_FILE": "",
            "CHAT_FILE": "",
            "CHAT_OUTPUT": str(processing_path("chat_with_emotes.json")),
            "TRANSCRIPTION_OUTPUT": str(processing_path("transcription.json")),
            "ANALYSIS_OUTPUT": str(processing_path("high_interest_segments.json")),
            "OUTPUT_CLIPS_DIR": str(processing_path("output_clips")),
            "CLIPS_BASE_DIR": "clips",
            "MAX_CLIP_COUNT": 10,
            "WHISPER_MODEL": "large",
            "LLM_DEVICE": 0,
            "CHAT_DENSITY_WEIGHT": 0.3,
            "CHAT_SENTIMENT_WEIGHT": 0.4,
            "VIDEO_EMOTION_WEIGHT": 0.3,
            "AUDIO_TARGET_BONUS": 1.0,
            "TEXT_TARGET_BONUS": 1.0,
            "INTEREST_SCORE_THRESHOLD": 0.5,
            "LOCAL_EMOTION_MODEL_PATH": "",
            "VIDEO_EMOTION_MODEL_PATH": "",
            "VIDEO_EMOTION_SEGMENT_LENGTH": 4.0,
            "ENABLE_VIDEO_EMOTION": False,
            "twitch_client_id": "",
            "twitch_oauth_token": "",
            "twitch_username": "",
            "twitch_download_folder": "./data/twitch",
        }
        self.load()

    def load(self):
        if not os.path.isfile(self.config_file):
            self.save()
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cfg.update(data)
        except Exception:
            pass

    def save(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def get(self, key):
        return self.cfg.get(key)

    def set(self, key, value):
        self.cfg[key] = value


if PYTQT5_AVAILABLE:
    class Worker(QThread):
        finished = pyqtSignal(object)
        error = pyqtSignal(str)
        progress_update = pyqtSignal(str)
        progress_percent = pyqtSignal(int)

        def __init__(self, func, *args, parent=None, **kwargs):
            super().__init__(parent)
            self.func = func
            self.args = args
            self.kwargs = kwargs
            self._should_stop = False
else:
    class Worker:
        def __init__(self, func, *args, parent=None, **kwargs):
            self.func = func
            self.args = args
            self.kwargs = kwargs
            self._should_stop = False

        def run(self):
            try:
                # 检查线程是否应该停止
                if self._should_stop:
                    return
                    
                import inspect
                sig = inspect.signature(self.func)
                if 'progress_callback' in sig.parameters:
                    self.kwargs['progress_callback'] = self.emit_progress
                res = self.func(*self.args, **self.kwargs)
                
                # 再次检查是否应该停止
                if not self._should_stop:
                    self.finished.emit(res)
            except Exception as e:
                if not self._should_stop:
                    self.error.emit(str(e))

        def emit_progress(self, stage, current, total, message=""):
            if self._should_stop:
                return
                
            if total > 0:
                percent = int((current / total) * 100)
                self.progress_percent.emit(percent)
            progress_text = f"[{stage}] {current}/{total} - {message}"
            self.progress_update.emit(progress_text)
        
        def stop(self):
            """停止线程"""
            self._should_stop = True
            self.quit()
            if not self.wait(2000):  # 等待2秒
                self.terminate()
                self.wait(1000)


def run_pipeline(cfg_manager, video, chat, has_chat, chat_output, transcription_output,
                 video_emotion_output, analysis_output, output_clips_dir,
                 video_clips_dir, progress_callback=None):
    """视频处理管道主函数 - 支持中断停止"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # 全局停止标志检查函数
    def should_stop():
        """检查是否应该停止处理"""
        try:
            stop_flag_file = os.path.join("processing", "stop_flag.txt")
            return os.path.exists(stop_flag_file)
        except Exception:
            return False
    
    def cleanup_stop_flag():
        """清理停止标志文件"""
        try:
            stop_flag_file = os.path.join("processing", "stop_flag.txt")
            if os.path.exists(stop_flag_file):
                os.remove(stop_flag_file)
        except Exception:
            pass
    
    # 清理之前的停止标志
    cleanup_stop_flag()
    
    def emit_progress(stage, current, total, message=""):
        # 检查停止标志
        if should_stop():
            logging.info(f"检测到停止信号，终止处理: {stage}")
            raise InterruptedError("用户中断处理")
            
        if progress_callback:
            progress_callback(stage, current, total, message)
        
        # 更新进度文件，包含更详细的信息
        try:
            import time
            import json
            
            # 计算更准确的进度百分比
            stage_weights = {
                "并行数据准备": 0.4,
                "视频情绪分析": 0.15,
                "数据准备": 0.05,
                "智能分析": 0.2,
                "并行视频切片": 0.15,
                "完成": 0.05
            }
            
            # 获取当前阶段权重
            stage_weight = stage_weights.get(stage, 0.1)
            
            # 计算阶段内进度
            stage_progress = (current / total) if total > 0 else 0
            
            # 计算累积进度（这里需要根据你的实际情况调整）
            base_progress = sum(stage_weights.get(s, 0) for s in stage_weights.keys() 
                               if s != stage and "前面已完成的阶段")
            current_stage_contribution = stage_weight * stage_progress
            total_percentage = (base_progress + current_stage_contribution) * 100
            
            progress_data = {
                "stage": stage,
                "current": current,
                "total": total,
                "message": message,
                "timestamp": time.time(),
                "percentage": min(100, total_percentage),
                "estimated_remaining_minutes": _calculate_smart_remaining_time(total_percentage)
            }
            
            progress_file = processing_path("analysis_progress.json")
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            with progress_file.open('w', encoding='utf-8') as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
        except InterruptedError:
            raise  # 重新抛出中断异常
        except Exception as e:
            logging.error(f"更新进度文件失败: {e}")
    
    def _calculate_smart_remaining_time(percentage):
        """智能计算剩余时间（分钟），优先使用智能预测器，失败则按百分比估算"""
        try:
            if 'smart_predictor' in locals() and smart_predictor:
                remain_str = smart_predictor.get_estimated_remaining_time()
                if remain_str:
                    if "即将完成" in remain_str:
                        return 1
                    if "小时" in remain_str:
                        try:
                            # 形如 "2小时15分钟"
                            parts = remain_str.replace("小时", ":").replace("分钟", "").split(":")
                            hours = int(parts[0])
                            minutes = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                            return max(1, hours * 60 + minutes)
                        except Exception:
                            pass
                    if "分钟" in remain_str:
                        try:
                            minutes = int(remain_str.replace("分钟", "").strip())
                            return max(1, minutes)
                        except Exception:
                            pass
                    if "秒" in remain_str:
                        try:
                            secs = int(remain_str.replace("秒", "").strip())
                            return max(1, (secs + 59) // 60)
                        except Exception:
                            pass
        except Exception:
            pass

        if percentage <= 0:
            return 30
        if percentage >= 100:
            return 0
        remaining_percent = 100 - percentage
        return max(1, int(remaining_percent / 8))
    
    # 启动智能进度预测 (可通过环境变量或配置禁用)
    predicted_time_info = None
    disable_smart = os.environ.get('DISABLE_SMART_PROGRESS', '0') == '1' or \
        str(cfg_manager.get('DISABLE_SMART_PROGRESS') or '').lower() in ('1','true','yes')
    smart_predictor = None
    if disable_smart:
        log_info("⚙️ 已根据配置/环境禁用智能进度预测 (DISABLE_SMART_PROGRESS=1)")
    try:
        if not disable_smart:
            from .smart_progress_predictor import SmartProgressPredictor
            smart_predictor = SmartProgressPredictor()
        
        # 预测视频处理时间
        if os.path.exists(video):
            cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if result.returncode == 0:
                duration = float(result.stdout.strip())
                size_mb = os.path.getsize(video) / (1024 * 1024)
                predicted_time = smart_predictor.predict_video_processing_time(duration, size_mb)
                predicted_time_info = predicted_time
                log_info(f"🎯 预测总处理时间: {predicted_time}")
                # 开始新的预测会话，记录整体用时
                try:
                    smart_predictor.start_session(duration_seconds=duration, size_mb=size_mb, video_path=video)
                except Exception:
                    pass
                
                # 通过进度回调传递预测时间信息
                if progress_callback:
                    progress_callback("预测时间", 1, 1, f"预计处理时间: {predicted_time}")
        
        # 启动各个处理阶段
        if smart_predictor:
            smart_predictor.start_stage("音频提取", 1)
            smart_predictor.start_stage("说话人分离", 1)
            smart_predictor.start_stage("音频转录", 10)
            smart_predictor.start_stage("情感分析", 1)
            smart_predictor.start_stage("切片生成", 1)
            log_info("✅ 智能进度预测启动成功")
        
    except ImportError as e:
        log_info("⚠️ 智能进度预测模块加载失败，使用简化预测器")
        # 使用简化版预测器作为fallback
        try:
            from .smart_progress_predictor import SimplePredictor
            smart_predictor = SimplePredictor() if not disable_smart else None
            
            # 简单预测处理时间
            if os.path.exists(video):
                try:
                    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video]
                    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10)
                    if result.returncode == 0:
                        duration = float(result.stdout.strip())
                        size_mb = os.path.getsize(video) / (1024 * 1024)
                        predicted_time = smart_predictor.predict_video_processing_time(duration, size_mb)
                        predicted_time_info = predicted_time
                        log_info(f"🎯 预测总处理时间(简化): {predicted_time}")
                        
                        # 通过进度回调传递预测时间信息
                        if progress_callback:
                            progress_callback("预测时间", 1, 1, f"预计处理时间: {predicted_time}")
                except Exception:
                    pass
                    
            if smart_predictor:
                log_info("✅ 使用简化进度预测器")
        except ImportError:
            # 如果连SimplePredictor都无法导入，创建一个最基础的替代
            class BasicPredictor:
                def predict_video_processing_time(self, duration, size_mb):
                    return f"{int(duration/30)}-{int(duration/15)}分钟"
                def start_stage(self, stage_name, weight): pass
                def update_progress(self, stage_name, progress): pass
                def complete_stage(self, stage_name): pass
                def finish_stage(self, stage_name): pass
            smart_predictor = BasicPredictor()
            log_info("✅ 使用基础进度预测器")
        
    except Exception as e:
        log_info(f"⚠️ 智能进度预测启动失败，使用基础预测器: {e}")
        # 创建基础预测器
        if not disable_smart:
            class BasicPredictor:
                def predict_video_processing_time(self, duration, size_mb):
                    return f"{int(duration/30)}-{int(duration/15)}分钟"
                def start_stage(self, stage_name, weight): pass
                def update_progress(self, stage_name, progress): pass
                def complete_stage(self, stage_name): pass
                def finish_stage(self, stage_name): pass
            smart_predictor = BasicPredictor()

    enable_video_emotion = cfg_manager.get("ENABLE_VIDEO_EMOTION")
    log_info(f"[pipeline] 视频情绪分析开关状态: {enable_video_emotion}")

    has_transcription = os.path.exists(transcription_output) and os.path.getsize(transcription_output) > 10
    has_chat_json = has_chat and os.path.exists(chat_output) and os.path.getsize(chat_output) > 10
    has_video_emotion = enable_video_emotion and os.path.exists(video_emotion_output) and os.path.getsize(video_emotion_output) > 10

    # 检查是否已有完整处理内容
    has_analysis = os.path.exists(analysis_output) and os.path.getsize(analysis_output) > 10
    
    # 检查clips目录是否存在且有内容（使用运行级输出目录）
    clips_dir_exists = os.path.exists(output_clips_dir)
    existing_clips = []
    if clips_dir_exists:
        try:
            for file in os.listdir(output_clips_dir):
                if file.lower().endswith('.mp4'):
                    clip_path = os.path.join(output_clips_dir, file)
                    if os.path.isfile(clip_path) and os.path.getsize(clip_path) > 1024:  # 大于1KB
                        existing_clips.append(file)
        except Exception as e:
            log_error(f"[pipeline] 检查切片目录失败: {e}")
    
    # 检查data目录是否存在且有内容（基于转录输出所在目录）
    data_dir = os.path.dirname(transcription_output)
    data_dir_exists = os.path.exists(data_dir)
    has_data_files = False
    if data_dir_exists:
        try:
            data_files = os.listdir(data_dir)
            has_data_files = len(data_files) > 0
            log_info(f"[pipeline] data目录包含 {len(data_files)} 个文件")
        except Exception as e:
            log_error(f"[pipeline] 检查data目录失败: {e}")
    
    # 检查是否已有完整处理内容
    has_complete_processing = (
        has_transcription and 
        has_analysis and 
        clips_dir_exists and 
        len(existing_clips) > 0
    )
    
    # 添加调试信息
    log_info(f"[DEBUG] 完整处理检查:")
    log_info(f"[DEBUG] - has_transcription: {has_transcription} ({transcription_output})")
    log_info(f"[DEBUG] - has_analysis: {has_analysis} ({analysis_output})")
    log_info(f"[DEBUG] - clips_dir_exists: {clips_dir_exists} ({output_clips_dir})")
    log_info(f"[DEBUG] - existing_clips: {len(existing_clips)} 个")
    log_info(f"[DEBUG] - has_complete_processing: {has_complete_processing}")
    
    # 如果已有完整处理内容，直接返回
    if has_complete_processing:
        log_info(f"[pipeline] 检测到完整处理内容，跳过处理")
        log_info(f"[pipeline] 转录文件: {'✅' if has_transcription else '❌'}")
        log_info(f"[pipeline] 分析文件: {'✅' if has_analysis else '❌'}")
        log_info(f"[pipeline] 切片目录: {'✅' if clips_dir_exists else '❌'}")
        log_info(f"[pipeline] 切片文件: {len(existing_clips)} 个")
        log_info(f"[pipeline] data目录: {'✅' if data_dir_exists else '❌'}")
        log_info(f"[pipeline] data文件: {'✅' if has_data_files else '❌'}")
        
        # 更新UI进度显示
        emit_progress("检查现有内容", 1, 6, "检测到完整处理内容...")
        emit_progress("跳过转录", 2, 6, "转录文件已存在")
        emit_progress("跳过分析", 3, 6, "分析文件已存在")
        emit_progress("跳过切片", 4, 6, f"已有{len(existing_clips)}个切片文件")
        emit_progress("完成", 6, 6, f"使用现有处理结果，已有{len(existing_clips)}个切片")
        
        # 更新智能进度预测 - 立即完成所有阶段
        if smart_predictor:
            smart_predictor.finish_stage("音频提取")
            smart_predictor.finish_stage("说话人分离")
            smart_predictor.finish_stage("音频转录")
            smart_predictor.finish_stage("情感分析")
            smart_predictor.finish_stage("切片生成")
            # 强制更新进度显示
            emit_progress("检查", 1, 1, "✅ 检测到已有处理内容，跳过所有步骤")
        
        return output_clips_dir, existing_clips, has_chat

    total_steps = 6
    current_step = 0

    # step 1-3: 并行数据准备
    current_step += 1
    emit_progress("并行数据准备", current_step, total_steps, "并行处理聊天提取、转录、情绪分析和主播分离...")
    
    # 添加停止检查
    if should_stop():
        logging.info("处理被中断 - 并行数据准备阶段")
        cleanup_stop_flag()
        return None, None, False
    
    # 检查强制重转录
    force_retranscription_value = cfg_manager.get("FORCE_RETRANSCRIPTION", False)
    if isinstance(force_retranscription_value, str):
        force_retranscription = force_retranscription_value
    else:
        force_retranscription = bool(force_retranscription_value)
    
    # 检查主播分离
    enable_speaker_separation_value = cfg_manager.get("ENABLE_SPEAKER_SEPARATION", False)
    if isinstance(enable_speaker_separation_value, str):
        enable_speaker_separation = enable_speaker_separation_value
    else:
        enable_speaker_separation = bool(enable_speaker_separation_value)
    
    # 并行执行数据准备任务
    host_audio_path = None
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        
        # 停止检查
        if should_stop():
            logging.info("处理被中断 - 数据准备阶段")
            cleanup_stop_flag()
            return None, None, False
        
        # 聊天提取任务
        if has_chat and not has_chat_json:
            log_info(f"[pipeline] 并行提取聊天: {chat} -> {chat_output}")
            futures['chat'] = executor.submit(extract_chat, chat, chat_output)
        
        # 音频提取任务（优先执行，确保完整提取）
        audio_save_dir = os.path.join(os.path.dirname(transcription_output), "audio")
        # 只在真正需要时才创建目录
        # os.makedirs(audio_save_dir, exist_ok=True)
        audio_save_path = os.path.join(audio_save_dir, "extracted_audio.wav")
        
        if not os.path.exists(audio_save_path):
            # 停止检查
            if should_stop():
                logging.info("处理被中断 - 音频提取前")
                cleanup_stop_flag()
                return None, None, False
            
            # 在真正需要音频提取时才创建目录
            os.makedirs(audio_save_dir, exist_ok=True)
            
            log_info("[pipeline] 开始完整音频提取...")
            emit_progress("音频提取", 1, 3, "正在从视频中提取完整音频...")
            
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-hide_banner", "-loglevel", "error", "-nostdin",
                    "-i", video, "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1",
                    "-threads", "0",
                    audio_save_path
                ]
                # 根据视频时长动态计算超时时间
                try:
                    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video]
                    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30)
                    if probe_result.returncode == 0:
                        import json
                        probe_data = json.loads(probe_result.stdout)
                        video_duration = float(probe_data['format']['duration'])
                        # 超时时间 = 视频时长 * 2 + 300秒缓冲
                        timeout_seconds = min(int(video_duration * 2) + 300, 7200)  # 最大2小时
                    else:
                        timeout_seconds = 3600  # 默认1小时
                except:
                    timeout_seconds = 3600  # 默认1小时
                
                log_info(f"[pipeline] 音频提取超时设置: {timeout_seconds}秒")
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=timeout_seconds)
                
                # 再次停止检查
                if should_stop():
                    logging.info("处理被中断 - 音频提取后")
                    cleanup_stop_flag()
                    return None, None, False
                
                # 检查音频文件是否成功生成（即使FFmpeg被中断，文件可能已经生成）
                if os.path.exists(audio_save_path) and os.path.getsize(audio_save_path) > 1024 * 1024:  # 大于1MB
                    file_size_mb = os.path.getsize(audio_save_path) / (1024 * 1024)
                    log_info(f"[pipeline] 音频文件已保存: {audio_save_path} ({file_size_mb:.1f}MB)")
                    emit_progress("音频提取", 2, 3, f"音频提取完成 ({file_size_mb:.1f}MB)")
                elif result.returncode == 0:
                    file_size_mb = os.path.getsize(audio_save_path) / (1024 * 1024)
                    log_info(f"[pipeline] 音频文件已保存: {audio_save_path} ({file_size_mb:.1f}MB)")
                    emit_progress("音频提取", 2, 3, f"音频提取完成 ({file_size_mb:.1f}MB)")
                else:
                    log_error(f"[pipeline] 音频文件保存失败: {result.stderr}")
                    emit_progress("音频提取", 3, 3, "音频提取失败")
                    cleanup_stop_flag()
                    return None, None, False
            except subprocess.TimeoutExpired:
                log_error("[pipeline] 音频提取超时")
                emit_progress("音频提取", 3, 3, "音频提取超时")
                cleanup_stop_flag()
                return None, None, False
            except InterruptedError:
                log_info("[pipeline] 音频提取被用户中断")
                cleanup_stop_flag()
                return None, None, False
            except Exception as e:
                log_error(f"[pipeline] 音频文件保存异常: {e}")
                cleanup_stop_flag()
                return None, None, False
                emit_progress("音频提取", 3, 3, f"音频提取异常: {e}")
                return None, None, False
        else:
            file_size_mb = os.path.getsize(audio_save_path) / (1024 * 1024)
            log_info(f"[pipeline] 音频文件已存在: {audio_save_path} ({file_size_mb:.1f}MB)")
            emit_progress("音频提取", 3, 3, f"使用现有音频文件 ({file_size_mb:.1f}MB)")
        
        # 转录任务（使用提取的音频）
        if not has_transcription or force_retranscription:
            log_info(f"[pipeline] 开始音频转录: {audio_save_path} -> {transcription_output}")
            whisper_model_name = cfg_manager.get("WHISPER_MODEL", "medium")
            emit_progress("音频转录", 1, 2, f"使用 {whisper_model_name} 模型进行转录...")
            
            futures['transcription'] = executor.submit(
                process_audio_segments,
                audio_path=audio_save_path,  # 使用提取的音频文件
                output_file=transcription_output,
                segment_length=cfg_manager.get("SEGMENT_LENGTH", 300),
                whisper_model_name=whisper_model_name
            )
        
        # 情绪分析任务
        if enable_video_emotion and not has_video_emotion:
            log_info(f"[pipeline] 并行情绪分析: {video} -> {video_emotion_output}")
            class EmotionArgs:
                def __init__(self, cfg_manager):
                    self.segment_length = float(cfg_manager.get("VIDEO_EMOTION_SEGMENT_LENGTH") or 4.0)
                    self.model_path = cfg_manager.get("VIDEO_EMOTION_MODEL_PATH") or ""
                    self.device = cfg_manager.get("LLM_DEVICE") or 0
            emotion_args = EmotionArgs(cfg_manager)
            futures['emotion'] = executor.submit(infer_emotion, video, video_emotion_output, emotion_args)
        
        # 主播分离任务（可选，失败不影响主流程）
        if enable_speaker_separation:
            log_info("[pipeline] 并行主播音频分离...")
            try:
                from acfv.processing.speaker_separation_integration import SpeakerSeparationIntegration
                separation_output_dir = os.path.join(os.path.dirname(transcription_output), "speaker_separation")
                speaker_separation = SpeakerSeparationIntegration(cfg_manager)
                speaker_separation.set_progress_callback(emit_progress)
                
                # 设置较短的超时时间，避免阻塞
                futures['speaker_separation'] = executor.submit(
                    speaker_separation.process_video_with_speaker_separation,
                    video_path=video,
                    output_dir=separation_output_dir
                )
            except Exception as e:
                log_error(f"[pipeline] 主播分离任务创建失败: {e}")
                # 不阻止整个流程继续
                pass
        
        # 等待所有任务完成
        for name, future in futures.items():
            try:
                # 为说话人分离设置可配置的超时时间，因为音频文件可能很大
                speaker_timeout = cfg_manager.get("SPEAKER_SEPARATION_TIMEOUT", 1800)
                timeout = speaker_timeout if name == 'speaker_separation' else 1800  # 说话人分离可配置，其他30分钟
                result = future.result(timeout=timeout)
                if name == 'speaker_separation' and result and result.get('host_audio_file'):
                    host_audio_path = result['host_audio_file']
                    log_info(f"[pipeline] 主播音频分离完成: {host_audio_path}")
                log_info(f"[pipeline] 并行任务 {name} 完成")
                
                # 更新智能进度预测
                if smart_predictor:
                    if name == 'chat':
                        smart_predictor.finish_stage("音频提取")
                    elif name == 'speaker_separation':
                        smart_predictor.finish_stage("说话人分离")
                    elif name == 'transcription':
                        smart_predictor.finish_stage("音频转录")
                    elif name == 'emotion':
                        smart_predictor.finish_stage("情感分析")
                        
            except Exception as e:
                log_error(f"[pipeline] 并行任务 {name} 失败: {e}")
                # 对于说话人分离失败，不阻止整个流程
                if name == 'speaker_separation':
                    log_warning(f"[pipeline] 说话人分离失败，继续其他处理: {e}")
                    # 更新智能进度预测，标记说话人分离完成（即使失败）
                    if smart_predictor:
                        smart_predictor.finish_stage("说话人分离")
                else:
                    log_error(f"[pipeline] 关键任务 {name} 失败，可能影响后续处理")
                                    # 更新智能进度预测
                if smart_predictor:
                    if name == 'chat':
                        smart_predictor.finish_stage("音频提取")
                    elif name == 'transcription':
                        smart_predictor.finish_stage("音频转录")
                    elif name == 'emotion':
                        smart_predictor.finish_stage("情感分析")
                    elif name == 'speaker_separation':
                        smart_predictor.finish_stage("说话人分离")
    
    # 处理未并行执行的任务
    if has_chat and not has_chat_json and 'chat' not in futures:
        log_info(f"[pipeline] 串行提取聊天: {chat} -> {chat_output}")
        try:
            extract_chat(chat, chat_output)
        except Exception as e:
            log_error(f"[pipeline] 聊天提取失败: {e}")
    
    if not has_transcription or force_retranscription:
        if 'transcription' not in futures:
            log_info(f"[pipeline] 串行转录: {video} -> {transcription_output}")
            try:
                process_audio_segments(
                    audio_path=video,
                    output_file=transcription_output,
                    segment_length=cfg_manager.get("SEGMENT_LENGTH", 300),
                    whisper_model_name="medium"
                )
                
                # 同时保存音频文件到clip目录
                audio_save_dir = os.path.join(os.path.dirname(transcription_output), "audio")
                # 只在真正需要时才创建目录
                # os.makedirs(audio_save_dir, exist_ok=True)
                audio_save_path = os.path.join(audio_save_dir, "extracted_audio.wav")
                
                # 提取并保存音频文件
                log_info("[pipeline] 保存音频文件...")
                try:
                    cmd = [
                        "ffmpeg", "-y",
                        "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-i", video, "-vn", "-acodec", "pcm_s16le",
                        "-ar", "16000", "-ac", "1",
                        "-threads", "0",
                        audio_save_path
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=600)
                    if result.returncode == 0:
                        log_info(f"[pipeline] 音频文件已保存: {audio_save_path}")
                        emit_progress("音频提取", 1, 1, f"音频文件已保存: {os.path.basename(audio_save_path)}")
                    else:
                        log_error(f"[pipeline] 音频文件保存失败: {result.stderr}")
                except Exception as e:
                    log_error(f"[pipeline] 音频文件保存异常: {e}")
                    
            except Exception as e:
                log_error(f"[pipeline] 转录失败: {e}")
    
    if enable_video_emotion and not has_video_emotion:
        if 'emotion' not in futures:
            log_info(f"[pipeline] 串行情绪分析: {video} -> {video_emotion_output}")
            try:
                class EmotionArgs:
                    def __init__(self, cfg_manager):
                        self.segment_length = float(cfg_manager.get("VIDEO_EMOTION_SEGMENT_LENGTH") or 4.0)
                        self.model_path = cfg_manager.get("VIDEO_EMOTION_MODEL_PATH") or ""
                        self.device = cfg_manager.get("LLM_DEVICE") or 0
                emotion_args = EmotionArgs(cfg_manager)
                infer_emotion(video, video_emotion_output, emotion_args)
            except Exception as e:
                log_error(f"[pipeline] 情绪分析失败: {e}")
    
    if enable_speaker_separation and 'speaker_separation' not in futures:
        log_info("[pipeline] 串行主播音频分离...")
        try:
            from acfv.processing.speaker_separation_integration import SpeakerSeparationIntegration
            separation_output_dir = os.path.join(os.path.dirname(transcription_output), "speaker_separation")
            speaker_separation = SpeakerSeparationIntegration(cfg_manager)
            speaker_separation.set_progress_callback(emit_progress)
            
            separation_result = speaker_separation.process_video_with_speaker_separation(
                video_path=video,
                output_dir=separation_output_dir
            )
            
            if separation_result and separation_result.get('host_audio_file'):
                host_audio_path = separation_result['host_audio_file']
                log_info(f"[pipeline] 主播音频分离完成: {host_audio_path}")
        except Exception as e:
            log_error(f"[pipeline] 主播分离失败: {e}")
            log_warning(f"[pipeline] 说话人分离失败，但不会阻止整个处理流程")
    
    log_info("[pipeline] 并行数据准备完成")

    # step 3 video emotion
    current_step += 1
    emit_progress("视频情绪分析", current_step, total_steps,
                  "使用深度学习模型分析视频情绪..." if enable_video_emotion else "跳过视频情绪分析...")
    t3 = None
    if enable_video_emotion and not has_video_emotion:
        log_info(f"[pipeline] Processing video emotion inference: {video} -> {video_emotion_output}")
        try:
            class EmotionArgs:
                def __init__(self, cfg_manager):
                    self.segment_length = float(cfg_manager.get("VIDEO_EMOTION_SEGMENT_LENGTH") or 4.0)
                    self.model_path = cfg_manager.get("VIDEO_EMOTION_MODEL_PATH") or ""
                    self.device = cfg_manager.get("LLM_DEVICE") or 0
            emotion_args = EmotionArgs(cfg_manager)
            t3 = threading.Thread(target=infer_emotion, args=(video, video_emotion_output, emotion_args))
            t3.start()
        except Exception as e:
            log_error(f"[pipeline] Error starting video emotion inference: {e}")
            with open(video_emotion_output, "w", encoding="utf-8") as f:
                import json
                json.dump([], f)
    elif not enable_video_emotion:
        log_info(f"[pipeline] Video emotion analysis disabled, creating empty emotion file: {video_emotion_output}")
        with open(video_emotion_output, "w", encoding="utf-8") as f:
            import json
            json.dump([], f)
    else:
        log_info(f"[pipeline] Using existing video emotion file: {video_emotion_output}")

    # 等待t3线程完成（如果存在）
    if t3:
        t3.join()

    # step 4 data prep
    current_step += 1
    emit_progress("数据准备", current_step, total_steps, "准备分析数据...")
    if not has_chat and not os.path.exists(chat_output):
        with open(chat_output, "w", encoding="utf-8") as f:
            import json
            json.dump([], f)
            log_info(f"[pipeline] Created empty chat file: {chat_output}")

    # step 5 analyze
    current_step += 1
    emit_progress("智能分析", current_step, total_steps, "使用AI进行内容兴趣度分析...")
    # 安全地重载/导入 config，避免 "module config not in sys.modules" 异常
    try:
        if 'config' in sys.modules:
            importlib.reload(sys.modules['config'])
        else:
            importlib.import_module('config')
    except Exception as e:
        log_error(f"[pipeline] config 模块重载失败，将使用 cfg_manager 值: {e}")

    # 将配置写回 config 模块（若存在）供下游读取；失败则忽略并依赖 cfg_manager
    try:
        cfg_mod = sys.modules.get('config')
        if cfg_mod is not None:
            cfg_mod.CHAT_DENSITY_WEIGHT = cfg_manager.get("CHAT_DENSITY_WEIGHT")
            cfg_mod.CHAT_SENTIMENT_WEIGHT = cfg_manager.get("CHAT_SENTIMENT_WEIGHT")
            cfg_mod.TEXT_TARGET_BONUS = cfg_manager.get("TEXT_TARGET_BONUS")
            cfg_mod.AUDIO_TARGET_BONUS = cfg_manager.get("AUDIO_TARGET_BONUS")
            cfg_mod.CLIPS_BASE_DIR = cfg_manager.get("CLIPS_BASE_DIR")
            cfg_mod.OUTPUT_CLIPS_DIR = output_clips_dir
    except Exception as e:
        log_error(f"[pipeline] 回写 config 模块配置失败（将直接使用 cfg_manager）: {e}")
    max_clips = int(cfg_manager.get("MAX_CLIP_COUNT") or 0)
    video_emotion_weight = float(cfg_manager.get("VIDEO_EMOTION_WEIGHT") or 0.3) if enable_video_emotion else 0.0
    log_info(f"[pipeline] Analysis configuration: max_clips={max_clips}, video_emotion_weight={video_emotion_weight}, enable_video_emotion={enable_video_emotion}")
    segments_data = []
    analysis_success = False
    try:
        import inspect
        # 尝试从 processing.analyze_data 导入函数
        analyze_params = []
        _analyze_func = None
        try:
            from acfv.processing.analyze_data import analyze_data as _analyze_func  # 兼容旧接口
        except ImportError:
            try:
                from acfv.processing.analyze_data import analyze_data_with_checkpoint as _analyze_func
            except ImportError:
                _analyze_func = None
        if _analyze_func is not None:
            analyze_sig = inspect.signature(_analyze_func)
            analyze_params = list(analyze_sig.parameters.keys())
            log_info(f"[pipeline] analyze_data function parameters: {analyze_params}")
        else:
            log_warning("[pipeline] 未找到 processing.analyze_data 中的分析函数，后续将直接回退")
        analyze_kwargs = {
            'chat_file': chat_output,
            'transcription_file': transcription_output,
            'output_file': analysis_output
        }
        if 'progress_callback' in analyze_params:
            analyze_kwargs['progress_callback'] = emit_progress
        if 'enable_video_emotion' in analyze_params:
            analyze_kwargs.update({
                'video_emotion_file': video_emotion_output,
                'video_emotion_weight': video_emotion_weight,
                'top_n': max_clips if max_clips > 0 else 9999,
                'enable_video_emotion': enable_video_emotion,
                'device': 'cuda:0'
            })
        elif 'video_emotion_file' in analyze_params and 'video_emotion_weight' in analyze_params:
            analyze_kwargs.update({
                'video_emotion_file': video_emotion_output,
                'video_emotion_weight': video_emotion_weight,
                'top_n': max_clips if max_clips > 0 else 9999
            })
        elif 'top_n' in analyze_params:
            analyze_kwargs['top_n'] = max_clips if max_clips > 0 else 9999
        
        # 语义自适应分析
        log_info("[pipeline] 使用语义自适应分析模式")
        if _analyze_func is not None:
            segments_data = _analyze_func(**analyze_kwargs)
        else:
            try:
                from acfv.processing.analyze_data import analyze_data_with_checkpoint as _fallback_analyze
                segments_data = _fallback_analyze(**analyze_kwargs)
            except Exception as _ie:
                log_warning(f"[pipeline] 无法导入 processing.analyze_data: {_ie}; 使用空结果回退")
                segments_data = []
        if segments_data:
            analysis_success = True
            log_info("[pipeline] Analysis completed successfully")
            
            # 更新智能进度预测
            if smart_predictor:
                smart_predictor.finish_stage("情感分析")
            # ✅ 额外校验：确认分析输出文件是否真正写出
            try:
                if not os.path.exists(analysis_output) or os.path.getsize(analysis_output) < 50:
                    log_warning(f"[pipeline][diagnostic] 分析函数返回了 {len(segments_data)} 个片段，但未检测到有效分析输出文件: {analysis_output}，尝试补写…")
                    try:
                        os.makedirs(os.path.dirname(analysis_output), exist_ok=True)
                        with open(analysis_output, 'w', encoding='utf-8') as _af:
                            json.dump(segments_data, _af, ensure_ascii=False, indent=2)
                        log_info("[pipeline][diagnostic] 已补写 analysis_output 文件")
                    except Exception as _we:
                        log_error(f"[pipeline][diagnostic] 补写 analysis_output 失败: {_we}")
                else:
                    log_info(f"[pipeline][diagnostic] 检测到分析输出文件: {analysis_output} ({os.path.getsize(analysis_output)} bytes)")
            except Exception as _ce:
                log_warning(f"[pipeline][diagnostic] 分析输出文件校验失败: {_ce}")
            
            # ✅ 评估score分布，辅助发现全0问题
            try:
                scores = [float(s.get('score', 0) or 0) for s in segments_data if isinstance(s, dict)]
                if scores:
                    mx = max(scores); mn = min(scores); avg = sum(scores)/len(scores)
                    non_zero = sum(1 for v in scores if v > 0)
                    log_info(f"[pipeline][diagnostic] 评分统计: count={len(scores)}, non_zero={non_zero}, min={mn:.4f}, max={mx:.4f}, avg={avg:.4f}")
                    if mx <= 0.05:
                        log_warning("[pipeline][diagnostic] 检测到所有评分非常低 (max <= 0.05)，可能聊天/文本/权重全部为0 或被拆分稀释")
                else:
                    log_warning("[pipeline][diagnostic] 分析返回的片段缺少 score 字段")
            except Exception as _se:
                log_warning(f"[pipeline][diagnostic] 评分统计失败: {_se}")
                
    except Exception as e:
        log_error(f"[pipeline] Analysis failed: {e}")
        analysis_success = False

    current_step += 1
    emit_progress("并行视频切片", current_step, total_steps, "并行生成视频切片文件...")

    if not analysis_success:
        if os.path.exists(analysis_output) and os.path.getsize(analysis_output) > 10:
            log_info(f"[pipeline] Reading analysis result: {analysis_output}")
            try:
                with open(analysis_output, "r", encoding="utf-8") as f:
                    segments_data = json.load(f)
                log_info(f"[pipeline] Found {len(segments_data)} segments in analysis result")
                # 确保先按评分排序再限制数量，避免按时间截取
                try:
                    segments_data = sorted(segments_data, key=lambda x: x.get('score', 0), reverse=True)
                except Exception:
                    pass
                if max_clips > 0 and len(segments_data) > max_clips:
                    original_count = len(segments_data)
                    segments_data = segments_data[:max_clips]
                    log_info(f"[pipeline] Limited segments from {original_count} to {len(segments_data)} based on MAX_CLIP_COUNT={max_clips}")
                # Fallback 情况下同样给出评分分布诊断
                try:
                    scores = [float(s.get('score', 0) or 0) for s in segments_data if isinstance(s, dict)]
                    if scores:
                        mx = max(scores); mn = min(scores); avg = sum(scores)/len(scores)
                        non_zero = sum(1 for v in scores if v > 0)
                        log_info(f"[pipeline][diagnostic][fallback] 评分统计: count={len(scores)}, non_zero={non_zero}, min={mn:.4f}, max={mx:.4f}, avg={avg:.4f}")
                        if mx <= 0.05:
                            log_warning("[pipeline][diagnostic][fallback] 分析结果评分全部极低或为0，可能 upstream 未写入有效评分")
                except Exception:
                    pass
            except Exception as e:
                log_error(f"[pipeline] Error reading analysis result: {e}")
                segments_data = []
        else:
            log_warning("[pipeline][diagnostic] 分析失败且未找到可用的分析输出文件，后续步骤将使用空片段列表")

    # 切片前简单检测是否存在新的评分（仅日志提示）
    try:
        run_dir = os.path.dirname(analysis_output)
        ratings_log_path = os.path.join(run_dir, 'acfv_ratings.jsonl')
        if os.path.exists(ratings_log_path) and os.path.getsize(ratings_log_path) > 0:
            with open(ratings_log_path, 'r', encoding='utf-8') as f:
                ratings_lines = sum(1 for _ in f)
            log_info(f"[pipeline][RAG] 检测到评分记录 {ratings_lines} 条（仅检测，不进行RAG处理）")
        else:
            log_info("[pipeline][RAG] 未检测到评分记录或评分文件为空")
    except Exception as e:
        log_warning(f"[pipeline][RAG] 评分检测失败: {e}")

    # 二次保障（可选）：从 ratings.json 重建片段顺序
    try:
        prefer_from_ratings = False
        try:
            prefer_from_ratings = bool(cfg_manager.get("PREFER_RATINGS_JSON", False))
        except Exception:
            prefer_from_ratings = False
        if prefer_from_ratings and not use_semantic_segment_mode:
            ratings_path = os.path.join(os.path.dirname(analysis_output), "ratings.json")
            video_dir = os.path.dirname(video)
            latest_dir = os.path.join(video_dir, "runs", "latest")
            candidate_latest = os.path.join(latest_dir, "ratings.json")
            candidate_video = os.path.join(video_dir, "ratings.json")
            if not os.path.exists(ratings_path):
                if os.path.exists(candidate_latest):
                    ratings_path = candidate_latest
                elif os.path.exists(candidate_video):
                    ratings_path = candidate_video
            if os.path.exists(ratings_path):
                with open(ratings_path, 'r', encoding='utf-8') as f:
                    ratings_data = json.load(f)
                rated_segments = []
                for clip_name, data in ratings_data.items():
                    try:
                        rated_segments.append({
                            'start': float(data.get('start', 0.0)),
                            'end': float(data.get('end', 0.0)),
                            'score': float(data.get('rating', 0.0)),
                            'text': data.get('text', ''),
                            'source': 'ratings.json'
                        })
                    except Exception:
                        continue
                if rated_segments:
                    rated_segments.sort(key=lambda x: x.get('score', 0.0), reverse=True)
                    if max_clips > 0 and len(rated_segments) > max_clips:
                        rated_segments = rated_segments[:max_clips]
                    segments_data = rated_segments
                    log_info(f"[pipeline] 采用 ratings.json 评分重建片段顺序，共 {len(segments_data)} 个")
        else:
            log_info("[pipeline] 已禁用从 ratings.json 重建片段（PREFER_RATINGS_JSON=False）")
    except Exception as e:
        log_warning(f"[pipeline] 使用 ratings.json 重排失败: {e}")

    log_info(f"[pipeline] Final segments count: {len(segments_data)}")

    def _has_ranking_signals(items):
        try:
            for seg in items:
                if not isinstance(seg, dict):
                    continue
                score = seg.get("score")
                if score is not None:
                    try:
                        if float(score) > 0:
                            return True
                    except Exception:
                        return True
                source = str(seg.get("source", "")).lower()
                if source in {"ratings.json", "manual", "acfv_ratings", "manual_rating"}:
                    return True
            return False
        except Exception:
            return False

    ranked_segments_detected = bool(segments_data) and _has_ranking_signals(segments_data)

    # 语义分段模式（从头到尾按语义连续分段，目标约4分钟，避免过短）
    try:
        val = cfg_manager.get("SEMANTIC_SEGMENT_MODE")
        # 默认开启语义分段模式（用户期望"从一开始就按语义切块"）
        use_semantic_segment_mode = bool(val) if val is not None else True
    except Exception:
        use_semantic_segment_mode = True

    if use_semantic_segment_mode and ranked_segments_detected:
        try:
            raw_force_semantic = cfg_manager.get("FORCE_SEMANTIC_SEGMENT")
        except Exception:
            raw_force_semantic = None
        force_semantic = bool(raw_force_semantic) if raw_force_semantic is not None else False
        if not force_semantic:
            log_info("[pipeline] 检测到评分驱动的片段排序，优先保留评分结果，跳过语义分段。如需强制语义切块，请开启 FORCE_SEMANTIC_SEGMENT。")
            use_semantic_segment_mode = False
        else:
            log_info("[pipeline] FORCE_SEMANTIC_SEGMENT 已启用，检测到评分也继续执行语义分段。")

    if use_semantic_segment_mode:
        log_info("[pipeline] 启用语义分段模式：从头按语义连续切分（约4分钟）")
        try:
            # 加载完整转录作为分段依据
            if os.path.exists(transcription_output):
                with open(transcription_output, 'r', encoding='utf-8') as f:
                    transcription_data = json.load(f)
            else:
                transcription_data = []
            # 参数
            target_sec = float(cfg_manager.get("SEMANTIC_TARGET_DURATION") or 240.0)
            min_sec = float(cfg_manager.get("MIN_CLIP_DURATION") or max(60.0, target_sec * 0.6))
            max_sec = float(cfg_manager.get("MAX_CLIP_DURATION") or min(target_sec * 1.6, 600.0))
            sim_threshold = float(cfg_manager.get("SEMANTIC_SIMILARITY_THRESHOLD") or 0.75)
            max_gap = float(cfg_manager.get("SEMANTIC_MAX_TIME_GAP") or 60.0)

            # 预处理转录片段
            segs = []
            for seg in transcription_data:
                try:
                    s = float(seg.get('start', 0.0)); e = float(seg.get('end', 0.0))
                    txt = seg.get('text', '') or ''
                    if e > s and txt.strip():
                        segs.append({'start': s, 'end': e, 'text': txt})
                except Exception:
                    continue
            segs.sort(key=lambda x: x['start'])

            # 向量化（TF-IDF优先；失败则BOW）
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                from sklearn.metrics.pairwise import cosine_similarity
                texts = [s['text'] for s in segs]
                vectorizer = TfidfVectorizer(max_features=5000)
                mat = vectorizer.fit_transform(texts) if texts else None
                def cosine(i, j):
                    try:
                        return float(cosine_similarity(mat[i], mat[j])[0][0]) if mat is not None else 1.0
                    except Exception:
                        return 1.0
            except Exception:
                # 退化为简单词袋余弦
                def to_bow(t):
                    import re
                    toks = re.findall(r"\w+", (t or '').lower())
                    from collections import Counter
                    return Counter(toks)
                bows = [to_bow(s['text']) for s in segs]
                import math
                def cosine(i, j):
                    a, b = bows[i], bows[j]
                    if not a or not b:
                        return 0.0
                    keys = set(a) | set(b)
                    dot = sum(a.get(k,0) * b.get(k,0) for k in keys)
                    na = math.sqrt(sum(v*v for v in a.values())); nb = math.sqrt(sum(v*v for v in b.values()))
                    return (dot / (na*nb)) if na>0 and nb>0 else 0.0

            # 顺序合并为语义块
            def _avg(values):
                return sum(values) / len(values) if values else None

            def _aggregate_segment_scores(group, group_start, group_end):
                scores = []
                interest_scores = []
                densities = []
                rag_priors = []
                volumes = []
                for seg in group:
                    try:
                        if seg.get("score") is not None:
                            scores.append(float(seg.get("score")))
                    except Exception:
                        pass
                    try:
                        if seg.get("interest_score") is not None:
                            interest_scores.append(float(seg.get("interest_score")))
                    except Exception:
                        pass
                    try:
                        if seg.get("density") is not None:
                            densities.append(float(seg.get("density")))
                    except Exception:
                        pass
                    try:
                        if seg.get("rag_prior") is not None:
                            rag_priors.append(float(seg.get("rag_prior")))
                    except Exception:
                        pass
                    try:
                        if seg.get("volume_penalty") is not None:
                            volumes.append(float(seg.get("volume_penalty")))
                    except Exception:
                        pass
                payload = {}
                avg_interest = _avg(scores or interest_scores)
                if avg_interest is not None:
                    payload["score"] = avg_interest
                    payload["interest_score"] = avg_interest
                avg_density = _avg(densities)
                if avg_density is not None:
                    payload["density"] = avg_density
                avg_rag = _avg(rag_priors)
                if avg_rag is not None:
                    payload["rag_prior"] = avg_rag
                avg_volume = _avg(volumes)
                if avg_volume is not None:
                    payload["volume_penalty"] = avg_volume
                if "score" not in payload:
                    duration_score = max(group_end - group_start, 0.005)
                    payload["score"] = duration_score
                    payload["interest_score"] = duration_score
                return payload

            semantic_segments = []
            cur_start = None; cur_end = None; cur_last_idx = None; cur_texts = []; cur_segments = []
            for idx, seg in enumerate(segs):
                s = seg['start']; e = seg['end']
                if cur_start is None:
                    cur_start, cur_end, cur_last_idx, cur_texts = s, e, idx, [seg['text']]
                    cur_segments = [seg]
                    continue
                gap = s - cur_end
                similar = True
                try:
                    similar = cosine(cur_last_idx, idx) >= sim_threshold
                except Exception:
                    similar = True
                new_dur = max(cur_end, e) - cur_start
                # 满足以下任一条件则切块：
                # 1) 间隔过大；2) 达到上限；3) 已接近目标且相似度不足
                if (gap > max_gap) or (new_dur >= max_sec) or ((new_dur >= target_sec) and (not similar)):
                    # 若当前块过短，尽量并入
                    if (cur_end - cur_start) < min_sec and (new_dur <= max_sec):
                        cur_end = max(cur_end, e)
                        cur_last_idx = idx
                        cur_texts.append(seg['text'])
                        cur_segments.append(seg)
                    else:
                        merged = {'start': cur_start, 'end': cur_end, 'text': ' '.join(cur_texts)}
                        merged.update(_aggregate_segment_scores(cur_segments, cur_start, cur_end))
                        semantic_segments.append(merged)
                        cur_start, cur_end, cur_last_idx, cur_texts = s, e, idx, [seg['text']]
                        cur_segments = [seg]
                else:
                    cur_end = max(cur_end, e)
                    cur_last_idx = idx
                    cur_texts.append(seg['text'])
                    cur_segments.append(seg)
            if cur_start is not None:
                merged = {'start': cur_start, 'end': cur_end, 'text': ' '.join(cur_texts)}
                merged.update(_aggregate_segment_scores(cur_segments, cur_start, cur_end))
                semantic_segments.append(merged)

            # 覆盖 segments_data（顺序输出，不再按分数重排）
            segments_data = semantic_segments
            log_info(f"[pipeline] 语义分段完成，共 {len(segments_data)} 段（目标≈{target_sec:.0f}s）")

            # 保证输出恰好 N 段且不重叠（不足则按转录边界拆分最长段，超出则裁剪）
            try:
                desired_count = int(cfg_manager.get("MAX_CLIP_COUNT") or 10)
                if desired_count <= 0:
                    desired_count = 10
            except Exception:
                desired_count = 10

            # 根据转录边界在片段内部寻找最优拆分点
            def _find_split_time_within(seg_start: float, seg_end: float, transcription_list, prefer_time: float,
                                        min_side: float) -> float:
                try:
                    candidates = []
                    for t in transcription_list:
                        try:
                            ts = float(t.get('start', 0.0)); te = float(t.get('end', 0.0))
                        except Exception:
                            continue
                        if ts <= seg_start or te >= seg_end:
                            continue
                        # 选用句子边界的中点作为候选，以偏向自然停顿
                        mid = (ts + te) / 2.0
                        # 两侧需保留最小长度
                        if (mid - seg_start) >= min_side and (seg_end - mid) >= min_side:
                            candidates.append(mid)
                    if not candidates:
                        return 0.0
                    # 选择最接近期望时间点（通常为中点）的边界
                    best = min(candidates, key=lambda x: abs(x - prefer_time))
                    return float(best)
                except Exception:
                    return 0.0

            def _split_longest_until_exact(segments, target_n: int, transcription_list, min_len: float, video_len: float):
                # 允许的最低拆分子片段长度（在min_len基础上适度放宽）
                min_child = max(min_len * 0.75, 30.0)
                safety_counter = 0
                while len(segments) < target_n and safety_counter < 200:
                    safety_counter += 1
                    # 选可拆分的最长片段
                    idx = -1
                    max_dur = -1.0
                    for i, s in enumerate(segments):
                        try:
                            ds = float(s.get('start', 0.0)); de = float(s.get('end', 0.0))
                        except Exception:
                            continue
                        dur = max(0.0, de - ds)
                        # 至少能拆成两个不小于 min_child 的子段
                        if dur >= (2.0 * min_child) and dur > max_dur:
                            max_dur = dur
                            idx = i
                    if idx < 0:
                        break  # 没有可拆分的片段

                    base = segments[idx]
                    s0 = float(base.get('start', 0.0)); e0 = float(base.get('end', 0.0))
                    mid_pref = (s0 + e0) / 2.0
                    split_t = _find_split_time_within(s0, e0, transcription_list, mid_pref, min_child)
                    if split_t <= 0.0:
                        # 没有合适的转录边界，使用中点但遵守最小长度
                        left = max(s0, min(mid_pref, e0 - min_child))
                        right = min(e0, max(mid_pref, s0 + min_child))
                        split_t = (left + right) / 2.0
                    # 构造两个新片段
                    left_seg = dict(base)
                    right_seg = dict(base)
                    left_seg['start'] = float(s0)
                    left_seg['end'] = float(split_t)
                    right_seg['start'] = float(split_t)
                    right_seg['end'] = float(e0)
                    # 校验长度
                    if (left_seg['end'] - left_seg['start']) < min_child or (right_seg['end'] - right_seg['start']) < min_child:
                        # 无法满足最小长度，放弃本次拆分
                        break
                    # 替换并保持时间顺序
                    segments.pop(idx)
                    segments.insert(idx, right_seg)
                    segments.insert(idx, left_seg)
                    segments.sort(key=lambda x: float(x.get('start', 0.0)))
                return segments

            # 裁剪或拆分，保证恰好 desired_count 段
            try:
                # 先合规排序
                segments_data = sorted(segments_data, key=lambda x: float(x.get('start', 0.0)))
                if len(segments_data) > desired_count:
                    # 若无score字段，则直接取时间顺序前N段
                    try:
                        segments_data = sorted(segments_data, key=lambda x: x.get('score', 0.0), reverse=True)[:desired_count]
                        segments_data = sorted(segments_data, key=lambda x: float(x.get('start', 0.0)))
                    except Exception:
                        segments_data = segments_data[:desired_count]
                elif len(segments_data) < desired_count:
                    # 拆分最长段直至达到N段
                    segments_data = _split_longest_until_exact(segments_data, desired_count, transcription_data, min_sec, 0.0)
                # 再次确认数量
                if len(segments_data) != desired_count:
                    log_warning(f"[pipeline] 无法严格达到 {desired_count} 段，当前 {len(segments_data)} 段（已尽最大努力）")
                # 最终确保不重叠（顺序压紧：每段结束不超过下一段开始）
                segments_data = sorted(segments_data, key=lambda x: float(x.get('start', 0.0)))
                for i in range(len(segments_data) - 1):
                    try:
                        if float(segments_data[i]['end']) > float(segments_data[i+1]['start']):
                            segments_data[i]['end'] = float(segments_data[i+1]['start'])
                    except Exception:
                        pass
            except Exception as _e:
                log_warning(f"[pipeline] 调整为恰好N段失败，将使用语义分段原始结果: {_e}")
        except Exception as e:
            log_warning(f"[pipeline] 语义分段模式失败，回退到分析结果: {e}")
    
    # 应用切片时长扩展逻辑
    if segments_data:
        # 语义可变时长：使用配置或默认值
        if use_semantic_segment_mode:
            # 在语义分段模式下，固定强约束，避免外部把min设到300s
            target_sec = float(cfg_manager.get("SEMANTIC_TARGET_DURATION") or 240.0)
            min_clip_duration = max(150.0, target_sec * 0.6)
            context_extend = float(cfg_manager.get("CLIP_CONTEXT_EXTEND") or 0.0)
        else:
            min_clip_duration = float(cfg_manager.get("MIN_CLIP_DURATION") or 60.0)
            context_extend = float(cfg_manager.get("CLIP_CONTEXT_EXTEND") or 0.0)
        
        # 获取视频总时长
        try:
            probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30)
            if probe_result.returncode == 0:
                import json
                probe_data = json.loads(probe_result.stdout)
                video_duration = float(probe_data['format']['duration'])
            else:
                video_duration = 30000  # 默认30分钟
        except:
            video_duration = 30000  # 默认30分钟
        
        log_info(f"[pipeline] 视频总时长: {video_duration:.1f}秒")
        log_info(f"[pipeline] 切片配置: 最小时长={min_clip_duration}秒, 前后文扩展={context_extend}秒")
        
        # 扩展片段时长
        from acfv.processing.clip_video import ensure_min_duration, extend_segment
        
        # 步骤1：扩展片段前后文
        if context_extend > 0:
            log_info(f"[pipeline] 扩展片段前后文 {context_extend}秒...")
            segments_data = [extend_segment(seg, context_extend, video_duration) for seg in segments_data]
        
        # 步骤2：确保达到最小时长
        log_info(f"[pipeline] 确保切片达到最小时长 {min_clip_duration}秒...")
        segments_data = ensure_min_duration(segments_data, min_clip_duration, video_duration)
        
        # 步骤3：以评分优先安排为"严格不重叠"的时间表（含可配置缓冲）
        buffer_sec = 0.0
        try:
            buf = cfg_manager.get("NON_OVERLAP_BUFFER_SECONDS")
            if isinstance(buf, (int, float)):
                buffer_sec = max(0.0, float(buf))
        except Exception:
            buffer_sec = 0.0

        if not use_semantic_segment_mode:
            log_info(f"[pipeline] 按评分优先安排片段，保证无重叠（缓冲={buffer_sec:.1f}s）...")

            # 评分高→低排列，逐个在时间轴上安放
            candidates = sorted(segments_data, key=lambda x: x.get('score', 0.0), reverse=True)
            # 标记原始索引，便于回填
            for _i, _seg in enumerate(candidates):
                try:
                    _seg['__orig_idx'] = _i
                except Exception:
                    pass
            scheduled = []  # 已占用区间
            placed_indices = set()

            def _windows_from_scheduled():
                # 由已占用构造空闲窗口列表
                free = []
                cursor = 0.0
                for occ in sorted(scheduled, key=lambda x: x['start']):
                    os, oe = float(occ['start']), float(occ['end'])
                    if os - buffer_sec > cursor:
                        free.append((cursor, os - buffer_sec))
                    cursor = max(cursor, oe + buffer_sec)
                if cursor < video_duration:
                    free.append((cursor, video_duration))
                return free

            drops_due_to_space = 0

            for seg in candidates:
                try:
                    base_s = float(seg.get('start', 0.0))
                    base_e = float(seg.get('end', 0.0))
                except Exception:
                    continue
                if base_e <= base_s:
                    continue

                # 已经应用过前后文扩展与最小时长，这里只确保在空窗内落位
                desired_s = max(0.0, min(base_s, video_duration))
                desired_e = max(0.0, min(base_e, video_duration))
                target_len = max(0.0, desired_e - desired_s)
                if target_len <= 0.0:
                    continue

                # 遍历当前空窗，选择与原中心最近的可放置窗口
                free_windows = _windows_from_scheduled()
                if not free_windows:
                    drops_due_to_space += 1
                    continue
                center = (desired_s + desired_e) / 2.0
                free_windows.sort(key=lambda w: abs(((w[0] + w[1]) / 2.0) - center))

                placed = False
                for (L, R) in free_windows:
                    # 在该窗口内尽量保持原区间，若不够则夹紧
                    s = max(L, desired_s)
                    e = min(R, desired_e)
                    if e - s <= 0.0:
                        continue
                    # 保持原长度的前提下，若窗口较大，尝试居中放置
                    length = min(target_len, R - L)
                    if length <= 0.0:
                        continue
                    # 调整为与原中心对齐的等长区间
                    half = length / 2.0
                    s_candidate = max(L, min(center - half, R - length))
                    e_candidate = s_candidate + length
                    if e_candidate - s_candidate > 0.0:
                        new_seg = dict(seg)
                        new_seg['start'] = float(s_candidate)
                        new_seg['end'] = float(e_candidate)
                        scheduled.append(new_seg)
                        if '__orig_idx' in seg:
                            placed_indices.add(seg['__orig_idx'])
                        placed = True
                        break

                if not placed:
                    drops_due_to_space += 1

            # 二次回填：逐步减少缓冲、按可用空窗剪裁放入，直至凑满Top-N
            if max_clips > 0 and len(scheduled) < max_clips:
                def windows_with_buffer(cur_sched, cur_buf):
                    free = []
                    cursor = 0.0
                    for occ in sorted(cur_sched, key=lambda x: x['start']):
                        os, oe = float(occ['start']), float(occ['end'])
                        if os - cur_buf > cursor:
                            free.append((cursor, os - cur_buf))
                        cursor = max(cursor, oe + cur_buf)
                    if cursor < video_duration:
                        free.append((cursor, video_duration))
                    return sorted(free, key=lambda w: (w[1]-w[0]), reverse=True)

                unplaced = [seg for seg in candidates if seg.get('__orig_idx') not in placed_indices]
                relax_buffers = [max(buffer_sec/2.0, 0.0), 0.0]
                relax_min = [min_clip_duration, max(min_clip_duration*0.75, 60.0), max(min_clip_duration*0.5, 45.0)]
                for rb in relax_buffers:
                    if len(scheduled) >= max_clips:
                        break
                    free_ws = windows_with_buffer(scheduled, rb)
                    for seg in unplaced:
                        if len(scheduled) >= max_clips:
                            break
                        base_s = float(seg.get('start', 0.0)); base_e = float(seg.get('end', 0.0))
                        if base_e <= base_s:
                            continue
                        orig_len = base_e - base_s
                        # 选最大的空窗，按长度剪裁放入
                        for L, R in free_ws:
                            win_len = max(0.0, R - L)
                            if win_len <= 0.0:
                                continue
                            # 依次尝试更严格的最短长度
                            placed2 = False
                            for mn in relax_min:
                                if win_len < mn:
                                    continue
                                length = min(orig_len, win_len)
                                # 居中摆放到窗口
                                s_cand = L + max(0.0, (win_len - length)/2.0)
                                e_cand = s_cand + length
                                if e_cand - s_cand > 0.0:
                                    new_seg = dict(seg)
                                    new_seg['start'] = float(s_cand)
                                    new_seg['end'] = float(e_cand)
                                    scheduled.append(new_seg)
                                    placed2 = True
                                    break
                            if placed2:
                                # 重新计算空窗
                                free_ws = windows_with_buffer(scheduled, rb)
                                break

                # 如仍不足，记录但不阻塞
                if len(scheduled) < max_clips:
                    remaining = max_clips - len(scheduled)
                    log_warning(f"[pipeline] 由于时间轴拥挤，仍有 {remaining} 个未能安放（已回填到最大可能）")

            # 输出为"评分优先+严格无重叠"的序列，并裁剪为Top-N
            segments_data = sorted(scheduled, key=lambda x: x.get('score', 0), reverse=True)
            if max_clips > 0 and len(segments_data) > max_clips:
                segments_data = segments_data[:max_clips]
        else:
            # 语义分段模式：按时间顺序输出，若有短段则顺序并入后继直至达到最小时长
            segments_data = sorted(segments_data, key=lambda x: float(x.get('start', 0.0)))
            merged = []
            i = 0
            while i < len(segments_data):
                s = float(segments_data[i].get('start', 0.0))
                e = float(segments_data[i].get('end', 0.0))
                txt = segments_data[i].get('text', '')
                j = i
                while (e - s) < min_clip_duration and (j + 1) < len(segments_data):
                    j += 1
                    e = float(segments_data[j].get('end', e))
                    txt = (txt + ' ' + segments_data[j].get('text', '')).strip()
                merged.append({'start': s, 'end': e, 'text': txt})
                i = j + 1
            segments_data = merged
            # 再次保证"恰好N段且不重叠"（合并后可能减少数量）
            try:
                desired_count = int(cfg_manager.get("MAX_CLIP_COUNT") or 10)
            except Exception:
                desired_count = 10
            # 裁剪过多
            if desired_count > 0 and len(segments_data) > desired_count:
                pass  # selection handled in normalize step
            # 拆分不足
            if desired_count > 0 and len(segments_data) < desired_count:
                # 加载转录以便按边界拆分
                transcription_list = []
                try:
                    if os.path.exists(transcription_output):
                        with open(transcription_output, 'r', encoding='utf-8') as f:
                            transcription_list = json.load(f) or []
                except Exception:
                    transcription_list = []
                def _split_by_mid(seg, min_child_len):
                    s0 = float(seg.get('start', 0.0)); e0 = float(seg.get('end', 0.0))
                    mid = (s0 + e0) / 2.0
                    base_score = float(seg.get('score', seg.get('interest_score', 0.0)) or 0.0)
                    dur = max(e0 - s0, 1e-6)
                    # 评分按时长比例拆分，保持总量守恒
                    left_score = base_score * (mid - s0) / dur
                    right_score = base_score * (e0 - mid) / dur
                    left = {'start': s0, 'end': mid, 'text': seg.get('text',''), 'score': left_score}
                    right = {'start': mid, 'end': e0, 'text': seg.get('text',''), 'score': right_score}
                    if (right['end']-right['start']) < min_child_len or (left['end']-left['start']) < min_child_len:
                        return None
                    return [left, right]
                def _split_longest_semantic(segments, need_count, min_child_len):
                    safety = 0
                    while len(segments) < need_count and safety < 200:
                        safety += 1
                        # 选最长者
                        idx = max(range(len(segments)), key=lambda i: float(segments[i].get('end',0.0)) - float(segments[i].get('start',0.0))) if segments else -1
                        if idx < 0:
                            break
                        base = segments[idx]
                        s0 = float(base.get('start', 0.0)); e0 = float(base.get('end', 0.0))
                        if (e0 - s0) < (2.0 * min_child_len):
                            break
                        # 首选在转录边界中点附近拆分
                        try:
                            candidates = []
                            for t in transcription_list:
                                try:
                                    ts = float(t.get('start', 0.0)); te = float(t.get('end', 0.0))
                                except Exception:
                                    continue
                                if ts <= s0 or te >= e0:
                                    continue
                                mid = (ts + te) / 2.0
                                if (mid - s0) >= min_child_len and (e0 - mid) >= min_child_len:
                                    candidates.append(mid)
                            if candidates:
                                pref = (s0 + e0)/2.0
                                split_t = min(candidates, key=lambda x: abs(x - pref))
                                base_score = float(base.get('score', base.get('interest_score', 0.0)) or 0.0)
                                dur = max(e0 - s0, 1e-6)
                                left_score = base_score * (split_t - s0) / dur
                                right_score = base_score * (e0 - split_t) / dur
                                left = {'start': s0, 'end': split_t, 'text': base.get('text',''), 'score': left_score}
                                right = {'start': split_t, 'end': e0, 'text': base.get('text',''), 'score': right_score}
                                segments.pop(idx)
                                segments.extend([left, right])
                                segments.sort(key=lambda x: float(x.get('start', 0.0)))
                                continue
                        except Exception:
                            pass
                        # 回退：用中点拆分
                        sp = _split_by_mid(base, min_child_len)
                        if not sp:
                            break
                        segments.pop(idx)
                        segments.extend(sp)
                        segments.sort(key=lambda x: float(x.get('start', 0.0)))
                    return segments
                min_child = max(min_clip_duration * 0.5, 30.0)
                segments_data = _split_longest_semantic(segments_data, desired_count, min_child)
            # 最终去重叠（压紧到相邻）
            segments_data = sorted(segments_data, key=lambda x: float(x.get('start', 0.0)))
            for i in range(len(segments_data)-1):
                try:
                    if float(segments_data[i]['end']) > float(segments_data[i+1]['start']):
                        segments_data[i]['end'] = float(segments_data[i+1]['start'])
                except Exception:
                    pass

        # 确保每个片段都有 score（语义拆分后继承/估算）
        for _seg in segments_data:
            if 'score' not in _seg or _seg['score'] is None:
                base_val = float(_seg.get('interest_score', 0.0) or 0.0)
                # 给一个很小的正值防止都是 0.000
                _seg['score'] = max(base_val, 0.005) if base_val > 0 else 0.005
        
        # 显示最终的评分顺序
        final_scores = [f"{seg.get('score', 0):.3f}" for seg in segments_data[:5]]
        log_info(f"[pipeline] 最终片段顺序（按评分）: {final_scores}")
        
        log_info(f"[pipeline] 切片时长扩展完成，共 {len(segments_data)} 个片段")

        # 最后保险：清洗片段时间，避免出现 end < start 或持续时间为非正导致 -t 负数
        try:
            cleaned_segments = []
            auto_fixed = 0
            for _seg in segments_data:
                try:
                    s = float(_seg.get('start', 0.0))
                    e = float(_seg.get('end', 0.0))
                except Exception:
                    continue
                # 修复颠倒
                if e < s:
                    s, e = e, s
                    auto_fixed += 1
                # 约束到视频范围
                s = max(0.0, min(s, video_duration))
                e = max(0.0, min(e, video_duration))
                # 确保最小正时长
                if e <= s:
                    e = min(video_duration, s + 1.0)
                if e <= s:
                    continue
                _seg['start'] = s
                _seg['end'] = e
                cleaned_segments.append(_seg)
            if auto_fixed > 0:
                log_warning(f"[pipeline] 片段时间存在颠倒，已自动修复 {auto_fixed} 个")
            if len(cleaned_segments) != len(segments_data):
                log_warning(f"[pipeline] 清洗后片段数量: {len(cleaned_segments)}/{len(segments_data)}")
            segments_data = cleaned_segments
        except Exception as _e:
            log_warning(f"[pipeline] 片段时间清洗失败，继续使用原片段: {_e}")
    
    log_info(f"[pipeline] Clipping video directly to: {output_clips_dir}")
    os.makedirs(output_clips_dir, exist_ok=True)
    clip_files = []
    
    if segments_data:
        def sequential_clip_generation(segments, video_path, output_dir, audio_source=None, progress_callback=None):
            """串行切片生成"""
            # 验证输入参数
            if not segments:
                log_error("[pipeline] 没有片段数据，无法生成切片")
                return []
            
            if not os.path.exists(video_path):
                log_error(f"[pipeline] 视频文件不存在: {video_path}")
                return []
            
            log_info(f"[pipeline] 开始串行切片生成，共 {len(segments)} 个片段")
            
            clip_files = []
            video_base = _sanitize_component(Path(video_path).stem)
            
            # 预先探测一次视频时长，避免每个片段重复ffprobe
            try:
                _probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video_path]
                _probe_result = subprocess.run(_probe_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30)
                if _probe_result.returncode == 0:
                    import json as _json
                    _probe_data = _json.loads(_probe_result.stdout)
                    video_duration_global = float(_probe_data['format']['duration'])
                else:
                    video_duration_global = 30000.0
            except Exception:
                video_duration_global = 30000.0

            # 统计总输出秒数用于"切片生成"阶段进度估计
            try:
                total_output_seconds = sum(max(0.0, float(seg['end']) - float(seg['start'])) for seg in segments)
            except Exception:
                total_output_seconds = float(len(segments)) * 60.0
            processed_output_seconds = 0.0

            def generate_single_clip(segment, index):
                """生成单个切片"""
                try:
                    start_time = segment['start']
                    end_time = segment['end']
                    duration = end_time - start_time
                    # 保险：若外层存在异常，防止出现非正时长
                    if duration <= 0:
                        end_time = min(video_duration_global, start_time + 1.0)
                        duration = max(0.5, end_time - start_time)
                    
                    # 生成输出文件名 - 确保索引正确
                    segment_index = index + 1  # 确保从1开始
                    clip_filename = f"{video_base}__clip_{segment_index:03d}_{start_time:.1f}s-{end_time:.1f}s.mp4"
                    output_path = os.path.join(output_dir, clip_filename)
                    
                    # 清理可能存在的旧文件
                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                            log_info(f"[pipeline] 清理旧文件: {output_path}")
                        except Exception as e:
                            log_warning(f"[pipeline] 清理旧文件失败: {e}")
                    
                    log_info(f"[pipeline] 生成切片 {index+1}/{len(segments)}: {clip_filename} ({duration:.1f}s)")
                    
                    # 使用预先探测的视频时长
                    video_duration = video_duration_global
                    use_fast_seek = start_time > video_duration_global * 0.5
                    
                    # 使用快速切片方法（直接复制流，不重新编码）
                    def cut_video_ffmpeg_fast(input_path, output_path, start_time, duration):
                        """使用FFmpeg快速切片：复制视频流，音频转AAC，避免无声/不兼容容器"""
                        cmd = [
                            "ffmpeg", "-y",
                            "-hide_banner", "-loglevel", "error", "-nostdin",
                            "-ss", str(start_time),         # 起始时间（输入寻址，快）
                            "-i", input_path,               # 输入视频
                            "-t", str(duration),            # 片段时长（秒）
                            "-map", "0:v:0",               # 明确映射视频
                            "-map", "0:a?",                # 可选映射音频
                            "-c:v", "copy",                # 复制视频
                            "-c:a", "aac",                 # 统一AAC音频
                            "-b:a", "160k",
                            "-movflags", "+faststart",     # 快速启动
                            output_path                     # 输出文件路径
                        ]
                        subprocess.run(cmd, check=True)
                    
                    # 构建FFmpeg命令 - 使用快速切片
                    if audio_source and os.path.exists(audio_source):
                        # 如果有音频源，尽量复制视频流，仅编码音频，加速输出
                        if use_fast_seek:
                            cmd = [
                                'ffmpeg', '-y',
                                '-hide_banner', '-loglevel', 'error', '-nostdin',
                                '-ss', str(start_time),
                                '-i', str(video_path),
                                '-i', str(audio_source),
                                '-map', '0:v',
                                '-map', '1:a',
                                '-t', str(duration),
                                '-c:v', 'copy',              # 复制视频，避免重编码
                                '-c:a', 'aac',
                                '-preset', 'veryfast',
                                '-avoid_negative_ts', 'make_zero',
                                '-movflags', '+faststart',
                                '-threads', '0',
                                '-max_muxing_queue_size', '1024',
                                str(output_path)
                            ]
                        else:
                            cmd = [
                                'ffmpeg', '-y',
                                '-hide_banner', '-loglevel', 'error', '-nostdin',
                                '-i', str(video_path),
                                '-i', str(audio_source),
                                '-map', '0:v',
                                '-map', '1:a',
                                '-ss', str(start_time),
                                '-t', str(duration),
                                '-c:v', 'copy',              # 复制视频，避免重编码
                                '-c:a', 'aac',
                                '-preset', 'veryfast',
                                '-movflags', '+faststart',
                                '-threads', '0',
                                '-max_muxing_queue_size', '1024',
                                str(output_path)
                            ]
                    else:
                        # 没有音频源，使用快速切片；若输出异常（0秒/无视频流），回退到编码模式
                        try:
                            cut_video_ffmpeg_fast(str(video_path), str(output_path), start_time, duration)
                            # 先不返回，做一次完整性检查
                            try:
                                probe_cmd = [
                                    'ffprobe', '-v', 'quiet', '-print_format', 'json',
                                    '-show_format', '-show_streams', str(output_path)
                                ]
                                probe_result_fast = subprocess.run(
                                    probe_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=15
                                )
                                need_fallback = True
                                if probe_result_fast.returncode == 0:
                                    import json as _json
                                    pdata = _json.loads(probe_result_fast.stdout or '{}')
                                    streams = pdata.get('streams', []) or []
                                    has_video_stream = any(s.get('codec_type') == 'video' for s in streams)
                                    duration_val = 0.0
                                    try:
                                        duration_val = float((pdata.get('format') or {}).get('duration') or 0.0)
                                    except Exception:
                                        duration_val = 0.0
                                    need_fallback = (not has_video_stream) or (duration_val <= 0.5)
                                if need_fallback:
                                    # 构建回退编码命令
                                    if use_fast_seek:
                                        cmd = [
                                            'ffmpeg', '-y',
                                            '-hide_banner', '-loglevel', 'error', '-nostdin',
                                            '-ss', str(start_time),
                                            '-i', str(video_path),
                                            '-t', str(duration),
                                            '-c:v', 'libx264',
                                            '-c:a', 'aac',
                                            '-preset', 'veryfast',
                                            '-crf', '23',
                                            '-avoid_negative_ts', 'make_zero',
                                            '-movflags', '+faststart',
                                            '-threads', '0',
                                            '-max_muxing_queue_size', '1024',
                                            str(output_path)
                                        ]
                                    else:
                                        cmd = [
                                            'ffmpeg', '-y',
                                            '-hide_banner', '-loglevel', 'error', '-nostdin',
                                            '-i', str(video_path),
                                            '-ss', str(start_time),
                                            '-t', str(duration),
                                            '-c:v', 'libx264',
                                            '-c:a', 'aac',
                                            '-preset', 'veryfast',
                                            '-crf', '23',
                                            '-threads', '0',
                                            '-max_muxing_queue_size', '1024',
                                            str(output_path)
                                        ]
                                # 如果 need_fallback 为 False，则不定义 cmd，让后续验证直接通过
                            except Exception:
                                # 探测失败时保持现状，由后续大小/探测检查兜底
                                pass
                        except subprocess.CalledProcessError as e:
                            log_warning(f"[pipeline] 快速切片失败，回退到编码模式: {e}")
                            # 回退到编码模式
                            if use_fast_seek:
                                cmd = [
                                    'ffmpeg', '-y',
                                    '-hide_banner', '-loglevel', 'error', '-nostdin',
                                    '-ss', str(start_time),
                                    '-i', str(video_path),
                                    '-t', str(duration),
                                    '-c:v', 'libx264',
                                    '-c:a', 'aac',
                                    '-preset', 'veryfast',
                                    '-crf', '23',
                                    '-avoid_negative_ts', 'make_zero',
                                    '-movflags', '+faststart',
                                    '-threads', '0',
                                    '-max_muxing_queue_size', '1024',
                                    str(output_path)
                                ]
                            else:
                                cmd = [
                                    'ffmpeg', '-y',
                                    '-hide_banner', '-loglevel', 'error', '-nostdin',
                                    '-i', str(video_path),
                                    '-ss', str(start_time),
                                    '-t', str(duration),
                                    '-c:v', 'libx264',
                                    '-c:a', 'aac',
                                    '-preset', 'veryfast',
                                    '-crf', '23',
                                    '-threads', '0',
                                    '-max_muxing_queue_size', '1024',
                                    str(output_path)
                                ]
                    
                    # 动态超时时间 - 基于切片时长和位置
                    base_timeout = 1800  # 增加到30分钟
                    safe_duration = max(float(duration), 1.0)
                    duration_factor = min(safe_duration / 10.0, 3.0)  # 基于切片时长，最大3倍
                    position_factor = 1.0
                    if start_time > video_duration * 0.8:
                        position_factor = 2.0  # 视频末尾需要更多时间
                    elif start_time > video_duration * 0.6:
                        position_factor = 1.5
                    
                    timeout = int(base_timeout * duration_factor * position_factor)
                    log_info(f"[pipeline] 切片 {index+1} 超时设置: {timeout}s (时长:{duration:.1f}s, 位置:{start_time:.1f}s)")
                    
                    # 执行FFmpeg命令（只有在需要编码时才执行）
                    if 'cmd' in locals():
                        result = subprocess.run(
                            cmd, 
                            capture_output=True, 
                            text=True, 
                            encoding='utf-8',
                            errors='ignore',
                            timeout=timeout
                        )
                    
                    # 检查输出文件是否存在且有效
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        if file_size > 1024 * 1024:  # 至少1MB
                            # 验证文件完整性 - 改进检查逻辑
                            try:
                                probe_cmd = [
                                    'ffprobe', '-v', 'quiet', '-print_format', 'json',
                                    '-show_format', '-show_streams', output_path
                                ]
                                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=30)
                                
                                if probe_result.returncode == 0:
                                    # 检查是否有视频流
                                    import json
                                    probe_data = json.loads(probe_result.stdout)
                                    streams = probe_data.get('streams', [])
                                    has_video_stream = any(stream.get('codec_type') == 'video' for stream in streams)
                                    has_audio_stream = any(stream.get('codec_type') == 'audio' for stream in streams)
                                    
                                    if has_video_stream:
                                        if not has_audio_stream:
                                            log_warning(f"[pipeline] 切片 {index+1} 缺少音频流: {output_path}")
                                        log_info(f"[pipeline] 切片 {index+1} 生成成功: {output_path} ({file_size} bytes)")
                                        # 更新切片阶段进度（基于累计输出秒数）
                                        try:
                                            nonlocal processed_output_seconds
                                            processed_output_seconds += max(0.0, float(end_time) - float(start_time))
                                            if 'smart_predictor' in locals() and smart_predictor and total_output_seconds > 0:
                                                progress_ratio = min(max(processed_output_seconds / total_output_seconds, 0.0), 1.0)
                                                smart_predictor.update_stage_progress("切片生成", progress_ratio)
                                        except Exception:
                                            pass
                                        return output_path
                                    else:
                                        log_error(f"[pipeline] 切片 {index+1} 缺少视频流")
                                        if os.path.exists(output_path):
                                            os.remove(output_path)
                                        return None
                                else:
                                    log_error(f"[pipeline] 切片 {index+1} 文件完整性检查失败: {probe_result.stderr}")
                                    if os.path.exists(output_path):
                                        os.remove(output_path)
                                    return None
                            except Exception as e:
                                log_error(f"[pipeline] 切片 {index+1} 文件检查异常: {e}")
                                # 如果文件足够大，可能是检查工具问题，保留文件
                                if file_size > 1024 * 1024:  # 大于1MB
                                    log_info(f"[pipeline] 切片 {index+1} 文件较大，保留: {output_path} ({file_size} bytes)")
                                    return output_path
                                else:
                                    if os.path.exists(output_path):
                                        os.remove(output_path)
                                    return None
                        else:
                            log_error(f"[pipeline] 切片 {index+1} 文件太小: {file_size} bytes (需要至少1MB)")
                            if os.path.exists(output_path):
                                os.remove(output_path)
                            return None
                    else:
                        log_error(f"[pipeline] 切片 {index+1} 输出文件不存在")
                        return None

                        
                except Exception as e:
                    log_error(f"[pipeline] 切片 {index+1} 异常: {e}")
                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                        except:
                            pass
                    return None
            
            # 串行执行切片生成
            successful_clips = []
            
            for i, segment in enumerate(segments):
                try:
                    clip_path = generate_single_clip(segment, i)
                    if clip_path:
                        successful_clips.append(clip_path)
                        log_info(f"[pipeline] 切片 {i+1} 完成，当前成功: {len(successful_clips)}/{len(segments)}")
                    
                    if progress_callback:
                        progress_callback(i + 1, len(segments))
                        
                except Exception as e:
                    log_error(f"[pipeline] 切片 {i+1} 任务异常: {e}")
                    if progress_callback:
                        progress_callback(i + 1, len(segments))
            
            log_info(f"[pipeline] 串行切片生成完成，成功生成 {len(successful_clips)} 个切片")
            return successful_clips
        
        def clip_progress_callback(current, total):
            emit_progress("串行视频切片", current_step, total_steps, f"正在生成第{current}/{total}个切片...")
        
        try:
            # 使用串行切片生成
            clip_files = sequential_clip_generation(
                segments_data, video, output_clips_dir, 
                audio_source=host_audio_path, 
                progress_callback=clip_progress_callback
            )
        except Exception as e:
            log_error(f"[pipeline] 串行切片失败: {e}")
            # 降级到clip_video函数
            try:
                import inspect
                clip_sig = inspect.signature(clip_video)
                if 'progress_callback' in clip_sig.parameters:
                    clip_video(video_path=video, analysis_file=analysis_output, output_dir=output_clips_dir, 
                              progress_callback=clip_progress_callback, audio_source=host_audio_path)
                else:
                    clip_video(video_path=video, analysis_file=analysis_output, output_dir=output_clips_dir, 
                              audio_source=host_audio_path)
            except Exception as e2:
                log_error(f"[pipeline] 降级切片也失败: {e2}")
        
        # 检查最终目录中的切片文件
        final_clips = []
        for file in os.listdir(output_clips_dir):
            if file.lower().endswith('.mp4'):
                clip_path = os.path.join(output_clips_dir, file)
                if os.path.isfile(clip_path) and os.path.getsize(clip_path) > 1024:  # 至少1KB
                    final_clips.append(clip_path)
        
        log_info(f"[pipeline] 最终切片统计: 成功生成 {len(final_clips)} 个有效切片")
        if len(final_clips) != len(segments_data):
            log_warning(f"[pipeline] 切片数量不匹配: 期望 {len(segments_data)} 个，实际 {len(final_clips)} 个")
        
        # 将最终切片添加到clip_files列表
        for clip_path in final_clips:
            if clip_path not in clip_files:
                clip_files.append(clip_path)
                log_info(f"[pipeline] Found clip: {clip_path}")
        
        log_info(f"[pipeline] Successfully generated {len(clip_files)} clip files")
        
        # 更新智能进度预测
        if smart_predictor:
            smart_predictor.finish_stage("切片生成")
            
    else:
        log_error("[pipeline] No segments to clip")

    emit_progress("完成", total_steps, total_steps, f"处理完成！生成了{len(clip_files)}个切片")
    
    # 生成每个切片的语义字幕（SRT）
    try:
        from acfv.processing.subtitle_generator import generate_semantic_subtitles_for_clips
        transcription_output = os.path.join(os.path.dirname(analysis_output), "transcription.json")
        if os.path.exists(transcription_output) and clip_files:
            count = generate_semantic_subtitles_for_clips(output_clips_dir, transcription_output, cfg_manager, clip_files)
            log_info(f"[pipeline] 已为 {count} 个切片生成语义字幕")
        else:
            log_info("[pipeline] 跳过字幕生成（无转录或无切片）")
    except Exception as e:
        log_error(f"[pipeline] 语义字幕生成失败: {e}")

    # 结束智能会话记录
    try:
        if 'smart_predictor' in locals() and smart_predictor:
            smart_predictor.end_session(success=True)
    except Exception:
        pass

    return output_clips_dir, clip_files, has_chat


def generate_content_indexes(cfg_manager):
    """Generate semantic indexes for rated clips.
    使用切片文本与评分构建RAG索引，优先使用最近一次运行（runs/latest）。
    """
    log_info("[generate_content_indexes] Starting to generate content indexes")

    clips_base_dir = cfg_manager.get("CLIPS_BASE_DIR")
    if not os.path.exists(clips_base_dir):
        log_info("[generate_content_indexes] Clips base dir doesn't exist")
        return "索引生成完成（无需处理）"

    processed_count = 0
    for video_dir in os.listdir(clips_base_dir):
        video_path = os.path.join(clips_base_dir, video_dir)
        if not os.path.isdir(video_path):
            continue

        # 支持新结构：runs/<run_xxx>/ratings.json 优先最新一次
        ratings_path = os.path.join(video_path, "ratings.json")
        runs_dir = os.path.join(video_path, "runs")
        latest_run_dir = None
        if os.path.isdir(runs_dir):
            run_names = sorted([d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d))])
            if run_names:
                latest_run_dir = os.path.join(runs_dir, run_names[-1])
                candidate = os.path.join(latest_run_dir, "ratings.json")
                if os.path.exists(candidate):
                    ratings_path = candidate

        if not os.path.exists(ratings_path):
            continue

        # 如果索引已存在则跳过（视频目录级别或最新run级别任一存在即可）
        index_dir = os.path.join(video_path, "index")
        index_file = os.path.join(index_dir, "content_index.faiss")
        run_index_dir = os.path.join(latest_run_dir, "index") if latest_run_dir else None
        run_index_file = os.path.join(run_index_dir, "content_index.faiss") if run_index_dir else None
        if (index_file and os.path.exists(index_file)) or (run_index_file and os.path.exists(run_index_file)):
            continue

        try:
            with open(ratings_path, "r", encoding="utf-8") as f:
                ratings = json.load(f)
            if not ratings:
                continue

            log_info(f"[generate_content_indexes] Generating index for {video_dir}")

            # 读取转录文件（legacy 或 mapping），但我们只需要每个切片的文本
            # 从 ratings.json 里优先取 'text' 字段
            segments = []
            weights = []
            for clip_filename, data in ratings.items():
                text = data.get("text", "")
                rating = float(data.get("rating", 0.0))
                if text and text.strip():
                    segments.append({"text": text})
                    weights.append(rating)

            if not segments:
                log_info(f"[generate_content_indexes] No clip texts in ratings for {video_dir}")
                continue

            if not FAISS_AVAILABLE:
                log_info(f"[generate_content_indexes] Skipping index generation for {video_dir} (faiss not available)")
                continue

            index, vectorizer, _ = build_content_index(segments, weights=weights)
            if index and vectorizer:
                # 保存到视频目录级别
                os.makedirs(index_dir, exist_ok=True)
                faiss.write_index(index, index_file)
                with open(os.path.join(index_dir, "vectorizer.pkl"), "wb") as f:
                    pickle.dump(vectorizer, f)
                # 同时保存到最新run目录，便于按run调试
                if latest_run_dir:
                    os.makedirs(run_index_dir, exist_ok=True)
                    faiss.write_index(index, run_index_file)
                    with open(os.path.join(run_index_dir, "vectorizer.pkl"), "wb") as f:
                        pickle.dump(vectorizer, f)
                log_info(f"[generate_content_indexes] Successfully generated index for {video_dir}")
                processed_count += 1
        except Exception as e:
            log_error(f"[generate_content_indexes] Error processing {video_dir}: {e}")

    log_info("[generate_content_indexes] Finished generating content indexes")
    return f"索引生成完成，处理了 {processed_count} 个视频目录"
