# local_video_manager.py - 本地视频管理模块

import os
import gc
import re
import json
import time
import threading
import traceback
import subprocess
import logging
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QListWidget, 
    QListWidgetItem, QMessageBox, QTabWidget, QFileDialog
)
from PyQt5.QtCore import QSize, Qt, QObject, pyqtSignal, QThread
from PyQt5.QtGui import QIcon, QImage, QPixmap
from typing import List, Optional
from acfv.features.modules.ui_components import VideoThumbnailLoader
from acfv.utils import safe_slug
from acfv import config
from acfv.runtime.storage import processing_path, resolve_clips_base_dir

# 导入说话人分离集成模块
try:
    from acfv.steps.speaker_separation.impl import SpeakerSeparationIntegration
except ImportError as e:
    logging.warning(f"说话人分离模块导入失败: {e}")
    SpeakerSeparationIntegration = None

# 导入说话人识别模块（改为包内显式导入，兼容打包）
try:
    # 旧代码使用裸模块名，导致运行时在不同工作目录下失败
    from acfv.processing.speaker_diarization_module import SpeakerDiarizationProcessor  # type: ignore
    SPEAKER_DIARIZATION_AVAILABLE = True
except Exception as e:  # noqa: BLE001
    logging.warning(f"说话人识别模块导入失败: {e}")
    SPEAKER_DIARIZATION_AVAILABLE = False

class ProgressEmitter(QObject):
    """线程安全的进度信号发射器"""

    progress_updated = pyqtSignal(str, int, int, str)  # stage, current, total, message
    detailed_progress_updated = pyqtSignal(str)  # detailed message
    percent_updated = pyqtSignal(int)  # percent
    # 🆕 在主线程启动/停止进度显示的信号
    start_progress = pyqtSignal(float, float)  # video_duration, file_size
    stop_progress = pyqtSignal()  # 无参数停止
    stage_progress = pyqtSignal(str, int, float)  # stage_name, substage_index, progress
    stage_finished = pyqtSignal(str)

class ThreadSafeWorker(QThread):
    """线程安全的工作线程"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress_update = pyqtSignal(str, int, int, str)  # stage, current, total, message
    
    def __init__(self, func, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._should_stop = False
        
    def run(self):
        try:
            if self._should_stop:
                return
                
            # 创建线程安全的进度回调
            def thread_safe_progress_callback(stage, current, total, message=""):
                if not self._should_stop:
                    # 使用信号发射进度更新
                    self.progress_update.emit(stage, current, total, message)
            
            # 如果函数接受progress_callback参数，传入线程安全的回调
            import inspect
            sig = inspect.signature(self.func)
            if 'progress_callback' in sig.parameters:
                self.kwargs['progress_callback'] = thread_safe_progress_callback
            
            # 执行函数
            result = self.func(*self.args, **self.kwargs)
            
            if not self._should_stop:
                self.finished.emit(result)
                
        except Exception as e:
            if not self._should_stop:
                self.error.emit(str(e))
    
    def stop(self):
        """停止线程"""
        logging.info(f"正在停止ThreadSafeWorker: {self.__class__.__name__}")
        
        # 设置停止标志
        self._should_stop = True
        
        # 优雅停止
        if self.isRunning():
            self.quit()
            # 等待线程停止
            if not self.wait(3000):  # 等待3秒
                logging.warning(f"ThreadSafeWorker未能在3秒内停止，强制终止")
                self.terminate()
                if not self.wait(2000):  # 再等待2秒
                    logging.error(f"ThreadSafeWorker强制终止失败")
        
        logging.info(f"ThreadSafeWorker已停止: {self.__class__.__name__}")

class LocalVideoManager:
    """本地视频管理器"""
    
    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        # 🆕 兼容已有代码中对 self.parent 的使用
        self.parent = main_window
        self.config_manager = config_manager
        self.video_thumbnail_loader = None
        self.current_workers = []  # 添加这行：保存Worker引用
        
        # 创建进度信号发射器
        self.progress_emitter = ProgressEmitter()
        
        # 连接信号到主窗口的UI更新方法
        self.progress_emitter.progress_updated.connect(self._update_progress_ui)
        self.progress_emitter.detailed_progress_updated.connect(
            self.main_window.update_detailed_progress
        )
        self.progress_emitter.percent_updated.connect(
            self.main_window.update_progress_percent
        )
        # 🆕 通过信号在主线程启动/停止进度显示，避免跨线程启动QTimer
        if hasattr(self.main_window, 'start_processing_progress'):
            self.progress_emitter.start_progress.connect(self.main_window.start_processing_progress)
        if hasattr(self.main_window, 'stop_processing_progress'):
            self.progress_emitter.stop_progress.connect(self.main_window.stop_processing_progress)
        if hasattr(self.main_window, 'update_processing_progress'):
            self.progress_emitter.stage_progress.connect(self.main_window.update_processing_progress)
        if hasattr(self.main_window, 'finish_processing_stage'):
            self.progress_emitter.stage_finished.connect(self.main_window.finish_processing_stage)

        # 当前运行的剪辑元数据路径，用于刷新统计
        self.current_run_meta_path = None
        self.current_run_video_base = None
        
        # 初始化说话人分离集成
        if SpeakerSeparationIntegration:
            self.speaker_separation = SpeakerSeparationIntegration(config_manager)
        else:
            self.speaker_separation = None
    
    def cleanup_workers(self):
        """清理本地视频管理器中可能存在的后台线程/Worker"""
        try:
            logging.info("[LocalVideoManager] 开始清理工作线程和加载器…")
            # 停止视频缩略图加载线程
            try:
                if getattr(self, 'video_thumbnail_loader', None):
                    loader = self.video_thumbnail_loader
                    self.video_thumbnail_loader = None
                    try:
                        if hasattr(loader, 'stop'):
                            loader.stop()
                        else:
                            if loader.isRunning():
                                loader.quit()
                                if not loader.wait(2000):
                                    loader.terminate()
                                    loader.wait(1000)
                    except Exception as e:
                        logging.debug(f"停止缩略图加载线程时忽略错误: {e}")
                    try:
                        if hasattr(loader, 'deleteLater'):
                            loader.deleteLater()
                    except Exception:
                        pass
            except Exception as e:
                logging.debug(f"清理缩略图加载器时忽略错误: {e}")
            
            # 停止当前的后台处理Worker
            try:
                if getattr(self, 'current_workers', None):
                    for worker in list(self.current_workers):
                        try:
                            if hasattr(worker, 'stop'):
                                worker.stop()
                            else:
                                if hasattr(worker, 'isRunning') and worker.isRunning():
                                    worker.quit()
                                    if not worker.wait(3000):
                                        worker.terminate()
                                        worker.wait(1000)
                        except Exception as e:
                            logging.debug(f"停止Worker时忽略错误: {e}")
                    self.current_workers.clear()
            except Exception as e:
                logging.debug(f"清理Worker集合时忽略错误: {e}")
            
            logging.info("[LocalVideoManager] 清理完成")
        except Exception as e:
            logging.debug(f"[LocalVideoManager] cleanup_workers 出错但已忽略: {e}")
    
    def _update_progress_ui(self, stage, current, total, message):
        """在主线程中更新进度UI"""
        try:
            logging.info(f"[PROGRESS_UI] {stage}: {current}/{total} - {message}")
            
            # 更新详细进度
            detail_msg = f"{stage}: {message}" if message else stage
            self.main_window.update_detailed_progress(detail_msg)
            
            # 更新百分比
            if total > 0:
                percent = int((current / total) * 100)
                self.main_window.update_progress_percent(percent)
                
        except Exception as e:
            logging.error(f"[PROGRESS_UI] UI更新失败: {e}")
    
    def update_progress(self, stage, current, total, message=""):
        """线程安全的进度更新方法"""
        logging.info(f"[PROGRESS] {stage}: {current}/{total} - {message}")
        
        # 使用信号机制在主线程中更新UI
        try:
            # 发射信号，让主线程处理UI更新
            self.progress_emitter.progress_updated.emit(stage, current, total, message)
        except Exception as e:
            logging.error(f"[PROGRESS] 信号发射失败: {e}")
    
    def _handle_progress_update(self, stage, current, total, message):
        """处理进度更新信号"""
        try:
            logging.info(f"[PROGRESS_SIGNAL] {stage}: {current}/{total} - {message}")
            
            # 更新UI（现在在主线程中）
            detail_msg = f"{stage}: {message}" if message else stage
            self.main_window.update_detailed_progress(detail_msg)
            
            if total > 0:
                percent = int((current / total) * 100)
                self.main_window.update_progress_percent(percent)
                
        except Exception as e:
            logging.error(f"[PROGRESS_SIGNAL] 处理进度信号失败: {e}")
    
    def init_ui(self, tab_widget):
        """初始化本地回放标签页UI"""
        layout = QVBoxLayout(tab_widget)
        
        btn_refresh = QPushButton("刷新本地回放")
        btn_refresh.clicked.connect(self.refresh_local_videos)
        layout.addWidget(btn_refresh)

        self.list_local = QListWidget()
        self.list_local.setIconSize(QSize(240, 135))
        layout.addWidget(self.list_local)

        btn_process = QPushButton("处理选中回放")
        btn_process.clicked.connect(self.process_selected_video)
        layout.addWidget(btn_process)
    
    def refresh_local_videos(self):
        """刷新本地视频列表（使用后台线程）"""
        # 优先使用新的回放下载目录配置，如果没有则使用旧的配置
        folder = self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder")
        # 可选：根据配置禁用缩略图加载，避免部分环境下QImage/QPixmap导致的潜在崩溃
        disable_thumbs = False
        try:
            disable_thumbs = bool(self.config_manager.get("DISABLE_VIDEO_THUMBNAILS", False))
        except Exception:
            disable_thumbs = False
        # 停止上一次缩略图加载，避免线程占用导致UI不更新
        try:
            if getattr(self, 'video_thumbnail_loader', None):
                loader = self.video_thumbnail_loader
                self.video_thumbnail_loader = None
                if hasattr(loader, 'stop'):
                    loader.stop()
                elif hasattr(loader, 'isRunning') and loader.isRunning():
                    loader.quit()
                    loader.wait(2000)
                if hasattr(loader, 'deleteLater'):
                    loader.deleteLater()
        except Exception as e:
            logging.debug(f"刷新前清理旧缩略图加载器时忽略错误: {e}")

        if not folder or not os.path.isdir(folder):
            # 尝试回退到默认目录
            fallback = "./data/twitch"
            if os.path.isdir(fallback):
                # 自动设置回退目录，但不强制保存
                folder = os.path.abspath(fallback)
                self.main_window.update_status(f"使用默认目录: {folder}")
            else:
                # 目录不存在时，显示友好提示，不强制要求用户选择
                self.list_local.clear()
                self.main_window.update_status("本地回放目录不存在。请在设置中配置回放下载目录，或先下载一些回放。")
                return

        # 先清空列表并显示加载状态
        self.list_local.clear()
        self.main_window.update_status("正在扫描本地视频文件...")
        
        # 获取所有MP4文件
        video_files = []
        try:
            for fn in sorted(os.listdir(folder)):
                if fn.lower().endswith(".mp4"):
                    path = os.path.join(folder, fn)
                    video_files.append((fn, path))
        except Exception as e:
            logging.error(f"扫描视频文件失败: {e}")
            self.main_window.update_status("扫描失败")
            return

        if not video_files:
            self.main_window.update_status("未找到视频文件")
            # 清空列表，留空界面
            self.list_local.clear()
            return

        # 先添加空项目到列表
        for filename, _ in video_files:
            item = QListWidgetItem(filename)
            self.list_local.addItem(item)

        if not disable_thumbs:
            # 使用后台线程加载缩略图
            # 重要：避免把线程的 parent 设为 main_window，防止窗口销毁时线程仍在运行导致QtFatal
            self.video_thumbnail_loader = VideoThumbnailLoader(video_files, parent=None, max_workers=2)
            self.video_thumbnail_loader.thumbnail_loaded.connect(self.on_video_thumbnail_loaded)
            # 进度更新尽量轻量，避免频繁UI更新造成卡顿
            self.video_thumbnail_loader.progress_update.connect(lambda msg: None)
            self.video_thumbnail_loader.finished.connect(lambda: self.main_window.update_status("本地视频加载完成"))
            # 使用安全的deleteLater绑定
            def _cleanup_loader():
                try:
                    if self.video_thumbnail_loader:
                        self.video_thumbnail_loader.deleteLater()
                except Exception:
                    pass
                self.video_thumbnail_loader = None
            self.video_thumbnail_loader.finished.connect(_cleanup_loader)
            self.video_thumbnail_loader.start()
        else:
            # 直接提示完成，跳过缩略图加载
            try:
                self.main_window.update_status("本地视频加载完成（已禁用缩略图）")
            except Exception:
                pass

    def on_video_thumbnail_loaded(self, index, image, filename):
        """视频缩略图加载完成的回调（线程安全：QImage->QPixmap）"""
        try:
            item = self.list_local.item(index)
            if not item:
                return
            pm = None
            try:
                if isinstance(image, QImage):
                    pm = QPixmap.fromImage(image)
                elif isinstance(image, QPixmap):
                    pm = image
                else:
                    pm = QPixmap()
            except Exception as _e:
                logging.debug(f"缩略图转换失败: {filename} - {_e}")
                pm = QPixmap()
            if pm and not pm.isNull():
                item.setIcon(QIcon(pm))
        except Exception as e:
            # 兜底：任何UI更新异常不再向外抛出，避免触发全局异常钩子导致应用退出
            try:
                logging.error(f"[LocalVideoManager] on_video_thumbnail_loaded 异常: {e}")
            except Exception:
                pass

    def process_selected_video(self):
        """处理选中的视频 - 主线程版本（用于检查点对话框）"""
        import logging
        
        logging.info("=" * 80)
        logging.info("[DEBUG] process_selected_video 被调用")
        logging.info("=" * 80)
        
        try:
            # 清理之前的Worker
            self.cleanup_workers()
            
            # 检查选中的视频
            idx = self.list_local.currentRow()
            if idx < 0:
                logging.error("[DEBUG] 没有选中的视频项")
                QMessageBox.warning(self.main_window, "错误", "请先选择本地回放")
                return
            
            logging.info(f"[DEBUG] 选中的视频索引: {idx}")
            
            # 检查检查点状态
            checkpoint_info = self.main_window.check_checkpoint_status()
            resume_mode = None  # None=自动检测, True=继续, False=重新开始
            
            if checkpoint_info:
                logging.info("[DEBUG] 发现检查点，显示对话框")
                # 显示检查点对话框
                result = self.main_window.show_checkpoint_dialog(checkpoint_info)
                
                if result == 0:  # 用户取消
                    logging.info("[DEBUG] 用户取消操作")
                    return
                elif result == 1:  # 继续分析
                    resume_mode = True
                    logging.info("[DEBUG] 用户选择继续")
                elif result == 2:  # 重新开始
                    resume_mode = False
                    logging.info("[DEBUG] 用户选择重新开始")
                    # 清除检查点文件
                    self.main_window.clear_checkpoint_files()
            else:
                logging.info("[DEBUG] 没有发现检查点")
            
            # 启动后台处理
            self._start_video_processing_pipeline(idx, resume_mode)
            
        except Exception as e:
            logging.error(f"[DEBUG] process_selected_video 异常: {e}")
            QMessageBox.critical(self.main_window, "错误", f"处理视频时发生错误: {e}")

    def process_selected_video_background(self):
        """处理选中的视频 - 后台线程版本"""
        import logging
        
        logging.info("=" * 80)
        logging.info("[DEBUG] process_selected_video_background 被调用")
        logging.info("=" * 80)
        
        try:
            # 清理之前的Worker
            self.cleanup_workers()
            
            # 检查选中的视频
            idx = self.list_local.currentRow()
            if idx < 0:
                logging.error("[DEBUG] 没有选中的视频项")
                QMessageBox.warning(self.main_window, "错误", "请先选择本地回放")
                return
            
            logging.info(f"[DEBUG] 选中的视频索引: {idx}")
            
            # 检查检查点状态
            checkpoint_info = self.main_window.check_checkpoint_status()
            resume_mode = None  # None=自动检测, True=继续, False=重新开始
            
            if checkpoint_info:
                logging.info("[DEBUG] 发现检查点，显示对话框")
                # 显示检查点对话框
                result = self.main_window.show_checkpoint_dialog(checkpoint_info)
                
                if result == 0:  # 用户取消
                    logging.info("[DEBUG] 用户取消操作")
                    return
                elif result == 1:  # 继续分析
                    resume_mode = True
                    logging.info("[DEBUG] 用户选择继续")
                elif result == 2:  # 重新开始
                    resume_mode = False
                    logging.info("[DEBUG] 用户选择重新开始")
                    # 清除检查点文件
                    self.main_window.clear_checkpoint_files()
            else:
                logging.info("[DEBUG] 没有发现检查点")
            
            # 启动后台处理
            self._start_video_processing_pipeline(idx, resume_mode)
            
        except Exception as e:
            logging.error(f"[DEBUG] process_selected_video_background 异常: {e}")
            QMessageBox.critical(self.main_window, "错误", f"处理视频时发生错误: {e}")

    def _start_video_processing_pipeline(self, video_index, resume_mode):
        """启动视频处理流水线 - 后台线程版本"""
        import logging
        logging.info("=" * 80)
        logging.info("[DEBUG] _start_video_processing_pipeline 被调用")
        logging.info(f"[DEBUG] 参数: video_index={video_index}, resume_mode={resume_mode}")
        logging.info("=" * 80)
        
        # 创建后台工作线程
        self.current_run_meta_path = None
        self.current_run_video_base = None

        def pipeline_worker():
            """后台处理工作函数"""
            import time
            video_clips_dir = None  # 初始化为None，确保finally块可以访问
            try:
                # 🆕 启动进度系统
                # 改为通过信号在主线程启动，避免在工作线程中创建/启动QTimer
                try:
                    self.progress_emitter.start_progress.emit(1800, 500*1024*1024)
                    logging.info("🎯 进度系统启动信号已发出")
                except Exception as e:
                    logging.warning(f"启动进度系统失败: {e}")
                
                # 获取选中的视频信息
                idx = self.list_local.currentRow()
                if idx < 0:
                    logging.error("[pipeline] 没有选中的视频")
                    return None
                
                # 获取视频文件名
                video_name = self.list_local.item(idx).text()
                logging.info(f"[pipeline] 选中的视频: {video_name}")
                
                # 构建视频文件路径
                twitch_folder = self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder", "./data/twitch")
                video_path = os.path.join(twitch_folder, video_name)
                chat_path = os.path.splitext(video_path)[0] + "_chat.html"
                
                logging.info(f"[pipeline] 视频路径: {video_path}")
                logging.info(f"[pipeline] 聊天路径: {chat_path}")
                
                # 检查文件是否存在
                if not os.path.exists(video_path):
                    logging.error(f"[pipeline] 视频文件不存在: {video_path}")
                    return None

                # 写出给 analyze_data 使用的视频路径文件
                try:
                    selected_path = processing_path('selected_video.txt')
                    selected_path.parent.mkdir(parents=True, exist_ok=True)
                    selected_path.write_text(video_path, encoding='utf-8')
                    logging.info(f'[pipeline] 已写入视频路径指示文件: {selected_path} -> {video_path}')
                except Exception as w_err:
                    logging.warning(f"[pipeline] 写入 selected_video.txt 失败: {w_err}")
                
                # 🆕 更新进度系统的实际视频信息
                if hasattr(self, 'parent') and hasattr(self.parent, 'progress_manager'):
                    try:
                        # 获取实际视频信息
                        file_size = os.path.getsize(video_path)
                        
                        # 尝试获取视频时长（可选，如果失败使用默认值）
                        try:
                            result = subprocess.run([
                                'ffprobe', '-v', 'quiet', '-show_entries', 
                                'format=duration', '-of', 'csv=p=0', video_path
                            ], capture_output=True, text=True, timeout=10)
                            
                            if result.returncode == 0 and result.stdout.strip():
                                duration = float(result.stdout.strip())
                                self.parent.progress_manager.start_processing(duration, file_size)
                                logging.info(f"🎯 更新进度系统 - 时长: {duration:.1f}s, 大小: {file_size/1024/1024:.1f}MB")
                        except Exception as e:
                            logging.info(f"获取视频时长失败，使用默认值: {e}")
                            
                    except Exception as e:
                        logging.warning(f"更新进度系统信息失败: {e}")
                
                # 设置配置参数
                self.config_manager.set("VIDEO_FILE", video_path)
                self.config_manager.set("CHAT_FILE", chat_path if os.path.exists(chat_path) else "")
                
                # 创建输出目录
                video_basename = os.path.splitext(os.path.basename(video_path))[0]
                
                # 清理文件名中的非法字符
                safe_basename = safe_slug(video_basename, max_length=80)

                # Backward compatibility: fall back to legacy naming if directory already exists.
                legacy_basename = re.sub(r'[<>:"/\\|?*]', '_', video_basename)
                legacy_basename = re.sub(r'\.{2,}', '_', legacy_basename).strip('.')
                if not legacy_basename:
                    legacy_basename = "video"
                
                logging.info(f"[pipeline] 原始文件名: {video_basename}")
                logging.info(f"[pipeline] 清理后文件名: {safe_basename}")
                
                clips_base_dir_path = resolve_clips_base_dir(self.config_manager, ensure=True)
                clips_base_dir = str(clips_base_dir_path)
                try:
                    self.config_manager.set("CLIPS_BASE_DIR", clips_base_dir)
                except Exception:
                    pass

                # Use existing legacy directory when present to avoid duplicating runs.
                legacy_dir = os.path.join(clips_base_dir, legacy_basename)
                safe_dir = os.path.join(clips_base_dir, safe_basename)
                if (
                    safe_basename != legacy_basename
                    and os.path.isdir(legacy_dir)
                    and not os.path.isdir(safe_dir)
                ):
                    safe_basename = legacy_basename

                video_clips_dir = os.path.join(clips_base_dir, safe_basename)
                video_data_dir = os.path.join(video_clips_dir, "data")
                
                # 确保目录存在
                try:
                    os.makedirs(video_clips_dir, exist_ok=True)
                    os.makedirs(video_data_dir, exist_ok=True)
                    logging.info(f"[pipeline] 目录创建成功: {video_data_dir}")
                except Exception as e:
                    logging.error(f"[pipeline] 目录创建失败: {e}")
                    safe_basename = f"video_{int(time.time())}"
                    video_clips_dir = os.path.join(clips_base_dir, safe_basename)
                    video_data_dir = os.path.join(video_clips_dir, "data")
                    os.makedirs(video_clips_dir, exist_ok=True)
                    os.makedirs(video_data_dir, exist_ok=True)
                    logging.info(f"[pipeline] 使用备用目录: {video_data_dir}")
                
                # 🆕 标记文件夹为正在处理，防止被空文件夹清理功能误删
                if hasattr(self, 'parent') and hasattr(self.parent, 'add_processing_folder'):
                    self.parent.add_processing_folder(video_clips_dir)
                    logging.info(f"[pipeline] 已标记文件夹为正在处理: {video_clips_dir}")


                # === 每次运行独立run目录，保存ratings与clips ===
                try:
                    runs_dir = os.path.join(video_clips_dir, "runs")
                    os.makedirs(runs_dir, exist_ok=True)
                    # 找到现有 run_XXX 目录的最大编号
                    existing_runs = []
                    for d in os.listdir(runs_dir):
                        if re.match(r"^run_\d{3}$", d):
                            try:
                                existing_runs.append(int(d.split("_")[1]))
                            except Exception:
                                pass
                    next_run_idx = (max(existing_runs) + 1) if existing_runs else 1
                    current_run_dir = os.path.join(runs_dir, f"run_{next_run_idx:03d}")
                    os.makedirs(current_run_dir, exist_ok=True)
                except Exception as e:
                    logging.warning(f"[pipeline] 创建run目录失败，回退到根目录: {e}")
                    current_run_dir = video_clips_dir
                
                # 将本次切片输出写到当前run目录
                output_clips_dir = os.path.join(current_run_dir, "output_clips")
                os.makedirs(output_clips_dir, exist_ok=True)
                # 记录运行元数据（供剪辑管理器统计）
                try:
                    if hasattr(self.parent, 'clips_manager') and self.parent.clips_manager:
                        record_fn = getattr(self.parent.clips_manager, "record_run_start", None)
                        if callable(record_fn):
                            meta_path = record_fn(safe_basename, Path(current_run_dir))
                            self.current_run_meta_path = meta_path
                            self.current_run_video_base = safe_basename
                except Exception as meta_err:
                    logging.debug(f"[pipeline] 记录运行元数据失败: {meta_err}")
                
                # 保持data目录用于共享的中间文件（chat/transcription/emotion 等）
                
                # 设置配置
                self.config_manager.set("OUTPUT_CLIPS_DIR", output_clips_dir)
                
                # 保存配置
                self.config_manager.save()
                
                logging.info(f"[pipeline] 配置设置完成")
                logging.info(f"  - 视频文件: {video_path}")
                logging.info(f"  - 聊天文件: {chat_path}")
                logging.info(f"  - 输出目录: {video_clips_dir}")
                logging.info(f"  - 当前运行目录: {current_run_dir}")
                
                
                # 🆕 创建新进度回调函数
                def new_progress_callback(stage, current, total, message=None):
                    try:
                        # 🆕 与新的进度管理器联动 (修正总进度显示不正确)
                        raw_stage_name = stage if isinstance(stage, str) else str(stage)
                        # 将流水线阶段名映射到 ProgressManager 预定义阶段
                        stage_name_map = {
                            "并行数据准备": "音频提取",      # 前期准备归到音频提取阶段权重
                            "音频提取": "音频提取",
                            "说话人分离": "说话人分离",
                            "音频转录": "语音转录",
                            "语音转录": "语音转录",
                            "数据准备": "语音转录",        # 数据准备更多与转录/加载相关
                            "视频情绪分析": "情感分析",
                            "情感分析": "情感分析",
                            "智能分析": "内容分析",
                            "内容分析": "内容分析",
                            "并行视频切片": "切片生成",
                            "串行视频切片": "切片生成",
                            "切片生成": "切片生成",
                            "完成": "切片生成",  # 结束阶段也归入切片生成最终推进到100%
                            "chat_extract": "音频提取",
                            "audio_extract": "音频提取",
                            "speaker_separation": "说话人分离",
                            "transcribe": "语音转录",
                            "video_emotion": "情感分析",
                            "analysis": "内容分析",
                            "clip": "切片生成",
                            "run": "切片生成",
                        }
                        stage_name = stage_name_map.get(raw_stage_name, raw_stage_name)

                        pm = getattr(self.parent, 'progress_manager', None)
                        if not pm:
                            return

                        # 如果阶段名不在预定义列表，尝试使用当前阶段名称兜底
                        if not any(s.name == stage_name for s in pm.stages):
                            try:
                                stage_name = pm.stages[pm.current_stage_index].name
                            except Exception:
                                stage_name = "音频提取"

                        # 确保阶段只启动一次
                        started_flag = f'_stage_{stage_name}_started'
                        if not hasattr(pm, started_flag):
                            pm.start_stage(stage_name)
                            setattr(pm, started_flag, True)

                        # —— 进度换算逻辑 ——
                        # 来自流水线的 progress = current/total (阶段整体百分比 0~1)
                        overall_progress = (current / total) if (isinstance(total, (int, float)) and total > 0) else 0.0
                        overall_progress = max(0.0, min(1.0, overall_progress))

                        # 将整体阶段进度拆分为 (completed_substages + substage_progress)/len(substages)
                        try:
                            stage_obj = next(s for s in pm.stages if s.name == stage_name)
                            substages_cnt = max(1, len(stage_obj.substages))
                        except StopIteration:
                            substages_cnt = 1
                        virtual_progress_units = overall_progress * substages_cnt
                        completed_substages = int(virtual_progress_units)
                        fractional = virtual_progress_units - completed_substages

                        # 修正边界：如果整体进度达到1，强制定位最后一个子阶段
                        if overall_progress >= 0.999:
                            completed_substages = substages_cnt - 1
                            fractional = 1.0

                        # 应用更新
                        pm.update_substage(stage_name, completed_substages, fractional)
                        # 触发 UI 刷新（通过信号回到主线程）
                        try:
                            self.progress_emitter.stage_progress.emit(
                                stage_name,
                                completed_substages,
                                float(fractional),
                            )
                        except Exception:
                            pass

                        # 阶段完成：推进到下一个阶段
                        if overall_progress >= 0.999:
                            try:
                                self.progress_emitter.stage_finished.emit(stage_name)
                            except Exception:
                                pass

                        # 🆕 同步到 SmartProgressPredictor：启动/更新/完成阶段
                        if hasattr(self.parent, 'smart_predictor') and self.parent.smart_predictor:
                            sp = self.parent.smart_predictor
                            # 阶段启动（仅一次）
                            smart_started_flag = f'_smart_stage_{stage_name}_started'
                            if not getattr(self.parent, smart_started_flag, False):
                                try:
                                    estimated_items = int(total) if isinstance(total, (int, float)) and total else 1
                                    if hasattr(sp, 'start_stage'):
                                        sp.start_stage(stage_name, estimated_items)
                                    setattr(self.parent, smart_started_flag, True)
                                except Exception:
                                    pass
                            
                            # 进度更新（0-1）
                            try:
                                if hasattr(sp, 'update_stage_progress'):
                                    sp.update_stage_progress(stage_name, float(overall_progress))
                            except Exception:
                                pass
                            
                            # 阶段完成
                            if overall_progress >= 0.999:
                                try:
                                    if hasattr(sp, 'finish_stage'):
                                        sp.finish_stage(stage_name)
                                except Exception:
                                    pass
                        
                        # 也调用旧的回调（如果存在）
                        if hasattr(self, 'update_progress'):
                            self.update_progress(raw_stage_name, current, total, message)
                        
                    except Exception as e:
                        logging.warning(f"新进度回调失败: {e}")
                
                # 调用模块化 pipeline
                from acfv.modular.pipeline import run_pipeline
                result = run_pipeline(
                    video_path=video_path,
                    chat_path=chat_path,
                    config_manager=self.config_manager,
                    run_dir=Path(current_run_dir),
                    output_clips_dir=output_clips_dir,
                    progress_callback=new_progress_callback,
                )
                
                return result
            
            except Exception as e:
                logging.error(f"[DEBUG] pipeline_worker 执行异常: {e}")
                logging.error(f"[DEBUG] 异常详情:\n{traceback.format_exc()}\n")
                # 🆕 标记预测会话失败（便于历史学习）
                try:
                    if hasattr(self.parent, 'smart_predictor') and self.parent.smart_predictor:
                        sp = self.parent.smart_predictor
                        if hasattr(sp, 'end_session'):
                            sp.end_session(success=False)
                except Exception:
                    pass
                raise
            
            finally:
                # 🆕 移除文件夹保护标记
                try:
                    if video_clips_dir and hasattr(self, 'parent') and hasattr(self.parent, 'remove_processing_folder'):
                        self.parent.remove_processing_folder(video_clips_dir)
                        logging.info(f"[pipeline] 已移除文件夹保护标记: {video_clips_dir}")
                except Exception as e:
                    logging.warning(f"移除文件夹保护标记失败: {e}")
                
                # 进度系统的停止改由主线程回调 on_pipeline_done/on_pipeline_err 处理
                # 避免在工作线程中触发Qt计时器/父子关系跨线程操作，导致
                # "QBasicTimer::start" 和 "QObject::setParent" 警告
        
        # 启动后台线程
        worker = ThreadSafeWorker(pipeline_worker)
        worker.finished.connect(lambda result: self.on_pipeline_done(result, worker))
        worker.error.connect(lambda msg: self.on_pipeline_err(msg, worker))
        worker.progress_update.connect(self._handle_progress_update)
        
        # 添加到当前工作线程列表
        self.current_workers.append(worker)
        
        # 启动线程
        worker.start()
        
        logging.info("[DEBUG] 后台处理线程已启动")

    def on_pipeline_done(self, result, worker):
        """流水线完成回调（成功）"""
        try:
            logging.info("[pipeline] 处理完成，进入完成回调")
            # 从当前工作集合移除
            try:
                if worker in self.current_workers:
                    self.current_workers.remove(worker)
            except Exception:
                pass

            # 成功结束智能预测会话，写入历史
            try:
                if hasattr(self.parent, 'smart_predictor') and self.parent.smart_predictor:
                    sp = self.parent.smart_predictor
                    if hasattr(sp, 'end_session'):
                        sp.end_session(success=True)
                        logging.info("📊 已记录成功会话到历史")
            except Exception as e:
                logging.debug(f"结束智能预测会话失败: {e}")

            # 停止进度显示（在主线程执行，避免跨线程Qt警告）
            try:
                if hasattr(self.parent, 'stop_processing_progress'):
                    self.parent.stop_processing_progress(success=True)
                    logging.info("🏁 进度系统已停止")
            except Exception:
                pass

            # 更新运行元数据状态
            try:
                meta_path = getattr(self, "current_run_meta_path", None)
                if meta_path and hasattr(self.parent, "clips_manager") and self.parent.clips_manager:
                    finalize_fn = getattr(self.parent.clips_manager, "finalize_run", None)
                    if callable(finalize_fn):
                        clip_list: List[str] = []
                        if isinstance(result, dict):
                            clip_list = [str(Path(p)) for p in result.get("clips", []) if p]
                        elif isinstance(result, (list, tuple)) and len(result) >= 2:
                            clip_list = [str(Path(p)) for p in result[1] if p]
                        finalize_fn(meta_path, success=True, clip_paths=clip_list)
            except Exception as meta_err:
                logging.debug(f"完成运行元数据失败: {meta_err}")
            finally:
                self.current_run_meta_path = None
                self.current_run_video_base = None

            # 刷新剪辑页（若主窗体提供方法）
            try:
                refreshed = False
                if hasattr(self.parent, 'clips_manager') and self.parent.clips_manager:
                    refresh_fn = getattr(self.parent.clips_manager, "refresh_clips", None)
                    if callable(refresh_fn):
                        refresh_fn()
                        refreshed = True
                if not refreshed and hasattr(self.parent, 'optimized_clips_manager') and self.parent.optimized_clips_manager:
                    refresh_fn = getattr(self.parent.optimized_clips_manager, "refresh_clips", None)
                    if callable(refresh_fn):
                        refresh_fn()
            except Exception as refresh_err:
                logging.debug(f"刷新剪辑列表失败: {refresh_err}")

        except Exception as e:
            logging.error(f"on_pipeline_done 处理异常: {e}")

    def on_pipeline_err(self, msg, worker):
        """流水线异常回调（失败）"""
        try:
            logging.error(f"[pipeline] 处理失败: {msg}")
            # 从当前工作集合移除
            try:
                if worker in self.current_workers:
                    self.current_workers.remove(worker)
            except Exception:
                pass

            # 结束智能预测会话（失败），写入历史
            try:
                if hasattr(self.parent, 'smart_predictor') and self.parent.smart_predictor:
                    sp = self.parent.smart_predictor
                    if hasattr(sp, 'end_session'):
                        sp.end_session(success=False)
                        logging.info("📊 已记录失败会话到历史")
            except Exception as e:
                logging.debug(f"结束失败会话记录时忽略错误: {e}")

            # 停止进度显示（在主线程执行，避免跨线程Qt警告）
            try:
                if hasattr(self.parent, 'stop_processing_progress'):
                    self.parent.stop_processing_progress(success=False)
                    logging.info("🏁 进度系统已停止")
            except Exception:
                pass

            # 更新运行元数据状态
            try:
                meta_path = getattr(self, 'current_run_meta_path', None)
                if meta_path and hasattr(self.parent, 'clips_manager') and self.parent.clips_manager:
                    finalize_fn = getattr(self.parent.clips_manager, "finalize_run", None)
                    if callable(finalize_fn):
                        finalize_fn(meta_path, success=False)
            except Exception as meta_err:
                logging.debug(f"失败运行元数据记录时忽略错误: {meta_err}")
            finally:
                self.current_run_meta_path = None
                self.current_run_video_base = None

            # 刷新剪辑页，确保失败后仍能看到已有结果
            try:
                refreshed = False
                if hasattr(self.parent, 'clips_manager') and self.parent.clips_manager:
                    refresh_fn = getattr(self.parent.clips_manager, "refresh_clips", None)
                    if callable(refresh_fn):
                        refresh_fn()
                        refreshed = True
                if not refreshed and hasattr(self.parent, 'optimized_clips_manager') and self.parent.optimized_clips_manager:
                    refresh_fn = getattr(self.parent.optimized_clips_manager, "refresh_clips", None)
                    if callable(refresh_fn):
                        refresh_fn()
            except Exception as refresh_err:
                logging.debug(f"刷新剪辑列表失败: {refresh_err}")

            # 弹窗提示
            try:
                QMessageBox.critical(self.main_window, "处理错误", str(msg))
            except Exception:
                pass
        except Exception as e:
            logging.error(f"on_pipeline_err 处理异常: {e}")
