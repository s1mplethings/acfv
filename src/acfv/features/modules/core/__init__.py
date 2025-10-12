# core/__init__.py - 核心功能模块合并文件

import os
import gc
import cv2
import time
import logging
import requests
import psutil
from typing import Dict, List, Any, Optional
from PyQt5.QtCore import QThread, QObject, pyqtSignal

# ==================== 线程管理 ====================

class SafeTerminateThread(QThread):
    """线程基类，提供安全的终止机制"""
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._should_stop = False
        self._progress = 0

    def stop(self):
        """安全停止线程"""
        self._should_stop = True
        self.quit()
        self.wait(2000)
        if self.isRunning():
            self.terminate()
            self.wait(1000)

    @property
    def should_stop(self):
        """检查是否应该停止"""
        return self._should_stop
    
    def update_progress(self, value):
        """更新进度"""
        self._progress = value
        self.progress_updated.emit(value)
    
    def update_status(self, status):
        """更新状态"""
        self.status_updated.emit(status)
    
    def report_error(self, error):
        """报告错误"""
        self.error_occurred.emit(error)

# ==================== 资源管理 ====================

class ResourceManager:
    """资源管理器 - 单例模式"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ResourceManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化资源管理器"""
        self.threads: List[QThread] = []
        self.processes: List[psutil.Process] = []
        self.temp_files: List[str] = []
        self.resources: List[Any] = []
    
    def register_thread(self, thread: QThread) -> None:
        """注册线程"""
        if isinstance(thread, QThread):
            self.threads.append(thread)
            logging.debug(f"已注册线程: {thread.__class__.__name__}")
    
    def register_temp_file(self, filepath: str) -> None:
        """注册临时文件"""
        if isinstance(filepath, str):
            self.temp_files.append(filepath)
            logging.debug(f"已注册临时文件: {filepath}")
    
    def cleanup(self) -> None:
        """清理所有资源"""
        logging.info("开始清理资源...")
        
        # 清理线程
        for thread in self.threads:
            try:
                if thread.isRunning():
                    if hasattr(thread, 'stop'):
                        thread.stop()
                    else:
                        thread.quit()
                        thread.wait(2000)
                        if thread.isRunning():
                            thread.terminate()
            except Exception as e:
                logging.error(f"清理线程时出错: {e}")
        
        # 清理临时文件
        for filepath in self.temp_files:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                logging.error(f"删除临时文件时出错: {e}")
        
        self.threads.clear()
        self.temp_files.clear()
        self.resources.clear()
        
        logging.info("资源清理完成")

# ==================== 进度管理 ====================

class ProgressManager(QObject):
    """进度管理器"""
    progress_updated = pyqtSignal(str, int, str)  # task_id, progress, eta
    status_updated = pyqtSignal(str, str)        # task_id, status
    task_completed = pyqtSignal(str)             # task_id
    
    def __init__(self):
        super().__init__()
        self._tasks: Dict[str, Dict] = {}
        self.logger = logging.getLogger("ProgressManager")
    
    def start_task(self, task_id: str, task_name: str, total_steps: int = 100) -> None:
        """开始一个新任务"""
        self._tasks[task_id] = {
            'name': task_name,
            'total_steps': total_steps,
            'current_step': 0,
            'start_time': time.time(),
            'progress_history': []
        }
        self.status_updated.emit(task_id, f"开始任务: {task_name}")
    
    def update_progress(self, task_id: str, current_step: int, status: Optional[str] = None) -> None:
        """更新任务进度"""
        if task_id not in self._tasks:
            return
            
        task = self._tasks[task_id]
        task['current_step'] = current_step
        
        # 记录进度历史
        task['progress_history'].append((time.time(), current_step))
        if len(task['progress_history']) > 10:
            task['progress_history'].pop(0)
        
        # 计算进度百分比
        progress = min(100, int((current_step / task['total_steps']) * 100))
        
        # 计算预计剩余时间
        eta = self._calculate_eta(task)
        eta_str = self._format_eta(eta) if eta else "计算中..."
        
        self.progress_updated.emit(task_id, progress, eta_str)
        
        if status:
            self.status_updated.emit(task_id, status)
        
        if progress >= 100:
            self.task_completed.emit(task_id)
    
    def _calculate_eta(self, task: Dict) -> Optional[float]:
        """计算预计剩余时间"""
        history = task['progress_history']
        if len(history) < 2:
            return None
        
        time_diff = history[-1][0] - history[0][0]
        progress_diff = history[-1][1] - history[0][1]
        
        if time_diff <= 0 or progress_diff <= 0:
            return None
        
        speed = progress_diff / time_diff
        remaining_progress = task['total_steps'] - task['current_step']
        
        if speed <= 0:
            return None
            
        return remaining_progress / speed
    
    def _format_eta(self, eta: Optional[float]) -> str:
        """格式化预计剩余时间"""
        if eta is None:
            return "计算中..."
            
        if eta < 60:
            return f"约 {int(eta)} 秒"
        elif eta < 3600:
            return f"约 {int(eta/60)} 分钟"
        else:
            hours = int(eta/3600)
            minutes = int((eta % 3600) / 60)
            return f"约 {hours} 小时 {minutes} 分钟"

# ==================== 视频处理 ====================

class VideoProcessor(SafeTerminateThread):
    """视频处理基类"""
    
    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.cap = None
        self.total_frames = 0
        self.current_frame = 0
    
    def initialize(self):
        """初始化视频捕获"""
        try:
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                raise Exception("无法打开视频文件")
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            return True
        except Exception as e:
            self.report_error(f"初始化视频失败: {e}")
            return False
    
    def cleanup(self):
        """清理资源"""
        if self.cap:
            self.cap.release()

# ==================== 聊天处理 ====================

class ChatProcessor(SafeTerminateThread):
    """聊天处理基类"""
    
    def __init__(self, chat_file: str):
        super().__init__()
        self.chat_file = chat_file
        self.chat_data: List[Dict[str, Any]] = []
    
    def load_chat(self) -> bool:
        """加载聊天数据"""
        try:
            import json
            with open(self.chat_file, 'r', encoding='utf-8') as f:
                self.chat_data = json.load(f)
            self.update_status(f"已加载 {len(self.chat_data)} 条聊天记录")
            return True
        except Exception as e:
            self.report_error(f"加载聊天数据失败: {e}")
            return False

# ==================== 下载管理 ====================

class DownloadManager(SafeTerminateThread):
    """下载管理器基类"""
    
    def __init__(self, output_dir: str):
        super().__init__()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
    def download_file(self, url: str, filename: str) -> bool:
        """下载文件的通用方法"""
        filepath = os.path.join(self.output_dir, filename)
        
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(8192):
                    if self.should_stop:
                        return False
                        
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            progress = int((downloaded / total_size) * 100)
                            self.update_progress(progress)
                            
            self.update_status(f"文件下载完成: {filename}")
            return True
            
        except Exception as e:
            self.report_error(f"下载失败 {url}: {e}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return False

# ==================== 日志管理 ====================

class LogManager:
    """日志管理器 - 单例模式"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LogManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
    def setup_logging(self, log_dir: str, app_name: str = "app") -> str:
        """设置日志系统"""
        import logging.handlers
        from datetime import datetime
        
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"{app_name}_{datetime.now().strftime('%Y%m%d')}.log")
        
        formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(name)s - %(message)s')
        
        # 文件处理器
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file, when='midnight', interval=1, backupCount=7, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        
        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        # 配置特定模块的日志级别
        logging.getLogger('PyQt5').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        
        return log_file

# 导出所有类和函数
__all__ = [
    'SafeTerminateThread', 'ResourceManager', 'ProgressManager', 
    'VideoProcessor', 'ChatProcessor', 'DownloadManager', 'LogManager'
]
