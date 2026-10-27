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
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QMessageBox, QTabWidget, QFileDialog, QLabel, QTextEdit, QDialog
)
from PyQt5.QtCore import QSize, Qt, QObject, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QIcon, QImage, QPixmap
from typing import List, Optional
from acfv.backend import service as backend_service
from acfv.app.gui_job_controller import GuiJobController
from acfv.features.modules.ui_components import VideoThumbnailLoader
from acfv.utils import safe_slug
from acfv import config
from acfv.runtime.storage import processing_path, resolve_clips_base_dir

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
            self._handle_legacy_percent_update
        )
        # 🆕 通过信号在主线程启动/停止进度显示，避免跨线程启动QTimer
        if hasattr(self.main_window, 'start_processing_progress'):
            self.progress_emitter.start_progress.connect(self.main_window.start_processing_progress)
        if hasattr(self.main_window, 'stop_processing_progress'):
            self.progress_emitter.stop_progress.connect(self.main_window.stop_processing_progress)
        if hasattr(self.main_window, 'update_processing_progress'):
            self.progress_emitter.stage_progress.connect(self._handle_legacy_stage_progress)
        if hasattr(self.main_window, 'finish_processing_stage'):
            self.progress_emitter.stage_finished.connect(self.main_window.finish_processing_stage)

        # 当前运行的剪辑元数据路径，用于刷新统计
        self.current_run_meta_path = None
        self.current_run_video_base = None
        self.current_job_id = None
        self.current_processing_dir = None
        self.current_job_view = None
        self.recent_job_views = []
        self.gui_controller = GuiJobController()
        self.status_timer = QTimer(self.main_window)
        self.status_timer.setInterval(750)
        self.status_timer.timeout.connect(self._poll_current_job)
        self.job_status_label = None
        self.job_summary_view = None
        self._progress_started = False
        
        # 该管理器本身不在 GUI 启动阶段使用说话人分离能力，避免冷启动时导入整条转录/分离依赖链。
        self.speaker_separation = None
    
    def cleanup_workers(self):
        """清理本地视频管理器中可能存在的后台线程/Worker"""
        try:
            logging.info("[LocalVideoManager] 开始清理工作线程和加载器…")
            try:
                if self.current_job_id:
                    backend_service.cancel_job(self.current_job_id)
                    logging.info(f"[LocalVideoManager] 已请求取消 job: {self.current_job_id}")
            except Exception as e:
                logging.debug(f"取消后端任务时忽略错误: {e}")
            finally:
                self.current_job_id = None
                self.current_processing_dir = None
                self.current_job_view = None
                if self.status_timer.isActive():
                    self.status_timer.stop()
                self._progress_started = False
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
            
            if total > 0:
                percent = int((current / total) * 100)
                detail_msg = f"{detail_msg} ({current}/{total}, stage {percent}%)"
                self.main_window.update_detailed_progress(detail_msg)
                
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
                self.main_window.update_detailed_progress(
                    f"{detail_msg} ({current}/{total}, stage {percent}%)"
                )
                
        except Exception as e:
            logging.error(f"[PROGRESS_SIGNAL] 处理进度信号失败: {e}")

    def _handle_legacy_percent_update(self, percent):
        """Keep legacy percent callbacks out of the main job progress bar."""
        logging.info(f"[LEGACY_PROGRESS] ignored stage-local percent for main progress: {percent}")

    def _handle_legacy_stage_progress(self, stage_name, substage_index, progress):
        """Legacy stage progress is text-only; backend job view owns the main bar."""
        try:
            percent = int(float(progress) * 100) if float(progress) <= 1.0 else int(float(progress))
        except Exception:
            percent = 0
        detail = f"{stage_name}: substage={substage_index} stage {percent}%"
        try:
            self.main_window.update_detailed_progress(detail)
        except Exception:
            pass
        logging.info(f"[LEGACY_STAGE_PROGRESS] {detail}")

    def _resolve_local_replay_output_base(self, replay_folder):
        """Store local replay outputs under the replay download folder."""
        try:
            replay_base = Path(str(replay_folder)).expanduser()
            if replay_base:
                replay_base.mkdir(parents=True, exist_ok=True)
                return replay_base.resolve()
        except Exception as err:
            logging.warning(f"[pipeline] 回放目录不可用，回退到切片基础目录: {err}")
        return resolve_clips_base_dir(self.config_manager, ensure=True)

    def _read_run_json(self, path: Path) -> dict:
        try:
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _list_video_run_dirs(self, video_clips_dir) -> List[Path]:
        runs_dir = Path(str(video_clips_dir)) / "runs"
        if not runs_dir.exists():
            return []
        indexed_runs: List[tuple[int, Path]] = []
        for child in runs_dir.iterdir():
            if not child.is_dir():
                continue
            match = re.match(r"^run_(\d{3})$", child.name)
            if not match:
                continue
            indexed_runs.append((int(match.group(1)), child))
        indexed_runs.sort(key=lambda item: item[0])
        return [path for _, path in indexed_runs]

    def _run_has_partial_state(self, run_dir: Path) -> bool:
        work_dir = run_dir / "work"
        candidate_files = [
            run_dir / "index.json",
            run_dir / "producer_index.json",
            run_dir / "run.json",
            work_dir / "stage_plan.json",
            work_dir / "audio_chunk_manifest.json",
            work_dir / "transcript_merged.json",
            work_dir / "selected_segments.json",
            work_dir / "clips_manifest.json",
            work_dir / "runtime" / "transcribe_runtime.json",
            work_dir / "runtime" / "render_runtime.json",
        ]
        for path in candidate_files:
            try:
                if path.exists() and path.stat().st_size > 0:
                    return True
            except Exception:
                continue
        candidate_dirs = [
            run_dir / "artifacts",
            work_dir / "audio",
            work_dir / "chunks",
            work_dir / "streaming",
        ]
        for path in candidate_dirs:
            try:
                if path.exists() and any(path.iterdir()):
                    return True
            except Exception:
                continue
        return False

    def _run_is_complete(self, run_dir: Path) -> bool:
        work_dir = run_dir / "work"
        render_runtime = self._read_run_json(work_dir / "runtime" / "render_runtime.json")
        if render_runtime.get("status") == "succeeded":
            return True
        final_markers = [
            work_dir / "export_results.json",
            work_dir / "clips_manifest.json",
        ]
        for path in final_markers:
            try:
                if path.exists() and path.stat().st_size > 10:
                    return True
            except Exception:
                continue
        return False

    def _find_resumable_run_dir(self, video_clips_dir) -> Optional[Path]:
        for run_dir in reversed(self._list_video_run_dirs(video_clips_dir)):
            if self._run_is_complete(run_dir):
                continue
            if self._run_has_partial_state(run_dir):
                return run_dir
        return None

    def _allocate_video_run_dir(self, video_clips_dir, resume_mode) -> tuple[str, bool]:
        runs_dir = Path(str(video_clips_dir)) / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        resumable_run = self._find_resumable_run_dir(video_clips_dir)
        if resume_mode is not False and resumable_run is not None:
            return str(resumable_run), True

        run_dirs = self._list_video_run_dirs(video_clips_dir)
        next_run_idx = 1
        if run_dirs:
            next_run_idx = max(int(path.name.split("_")[1]) for path in run_dirs) + 1
        current_run_dir = runs_dir / f"run_{next_run_idx:03d}"
        current_run_dir.mkdir(parents=True, exist_ok=True)
        return str(current_run_dir), False
    
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

        actions = QHBoxLayout()
        btn_cancel = QPushButton("取消当前任务")
        btn_cancel.clicked.connect(self.cancel_current_job)
        actions.addWidget(btn_cancel)
        btn_open = QPushButton("打开结果目录")
        btn_open.clicked.connect(self.open_current_result_dir)
        actions.addWidget(btn_open)
        btn_logs = QPushButton("查看日志")
        btn_logs.clicked.connect(self.show_current_job_logs)
        actions.addWidget(btn_logs)
        layout.addLayout(actions)

        self.job_status_label = QLabel("当前任务：无")
        self.job_status_label.setWordWrap(True)
        layout.addWidget(self.job_status_label)

        self.job_summary_view = QTextEdit()
        self.job_summary_view.setReadOnly(True)
        self.job_summary_view.setMinimumHeight(160)
        self.job_summary_view.setPlaceholderText("任务创建后，这里会显示当前 job、阶段、runtime 摘要、错误与结果目录。")
        layout.addWidget(self.job_summary_view)

    def _append_recent_job(self, job_view):
        if not job_view:
            return
        job_id = job_view.get("job", {}).get("job_id")
        self.recent_job_views = [
            existing for existing in self.recent_job_views
            if existing.get("job", {}).get("job_id") != job_id
        ]
        self.recent_job_views.insert(0, job_view)
        self.recent_job_views = self.recent_job_views[:5]

    def _format_runtime_summary(self, name, summary):
        if not summary or not summary.get("present"):
            return f"{name}: 未生成"
        active = "活跃" if summary.get("is_active") else "静止"
        return (
            f"{name}: status={summary.get('status')} "
            f"completed={summary.get('completed')}/{summary.get('total')} "
            f"failed={summary.get('failed')} running={summary.get('running')} "
            f"updated_at={summary.get('updated_at') or '-'} {active}"
        )

    def _render_job_summary(self, job_view):
        if not self.job_status_label or not self.job_summary_view:
            return
        if not job_view:
            self.job_status_label.setText("当前任务：无")
            self.job_summary_view.setPlainText("暂无运行中的任务。")
            return
        job = job_view.get("job", {})
        stage = job.get("current_stage") or "queued"
        status = job.get("status") or "unknown"
        progress = job.get("progress", {}) or {}
        percent = progress.get("percent")
        overall = job_view.get("overall_progress", {}) or {}
        overall_percent = overall.get("percent")
        message = progress.get("message") or ""
        percent_text = f"{percent:.1f}%" if isinstance(percent, (int, float)) else "--"
        overall_text = f"{overall_percent:.1f}%" if isinstance(overall_percent, (int, float)) else "--"
        self.job_status_label.setText(f"当前任务：{job.get('job_id')} | {status} | {stage} | overall {overall_text}")
        lines = [
            f"Job: {job.get('job_id')}",
            f"状态: {status}",
            f"阶段: {stage}",
            f"总体进度: {overall_text}",
            f"阶段进度: {progress.get('current', 0)}/{progress.get('total', 0)} ({percent_text})",
            f"消息: {message or '-'}",
            f"结果目录: {job_view.get('result_dir') or '-'}",
            self._format_runtime_summary("Transcribe", job_view.get("runtime", {}).get("transcribe")),
            self._format_runtime_summary("Render", job_view.get("runtime", {}).get("render")),
        ]
        error_display = job_view.get("error_display") or ""
        if error_display:
            lines.extend(["", "错误摘要:", error_display])
        if self.recent_job_views:
            lines.append("")
            lines.append("最近任务:")
            for recent in self.recent_job_views[:5]:
                recent_job = recent.get("job", {})
                lines.append(
                    f"- {recent_job.get('job_id')} | {recent_job.get('status')} | "
                    f"{recent_job.get('current_stage')} | {recent_job.get('run_dir') or '-'}"
                )
        self.job_summary_view.setPlainText("\n".join(lines))

    def apply_job_view_progress(self, job_view):
        overall = job_view.get("overall_progress", {}) or {}
        percent = overall.get("percent")
        if isinstance(percent, (int, float)):
            self.main_window.update_progress_percent(int(percent))

    def _update_main_window_from_job(self, job_view):
        job = job_view.get("job", {})
        progress = job.get("progress", {}) or {}
        stage = job.get("current_stage") or "queued"
        status = job.get("status") or "unknown"
        message = progress.get("message") or ""
        self.apply_job_view_progress(job_view)
        detail = f"{stage} | {status}"
        if message:
            detail = f"{detail} | {message}"
        current_runtime = job_view.get("current_runtime")
        if current_runtime and current_runtime.get("present"):
            detail = (
                f"{detail} | completed={current_runtime.get('completed')}/{current_runtime.get('total')} "
                f"failed={current_runtime.get('failed')} running={current_runtime.get('running')}"
            )
        self.main_window.update_detailed_progress(detail)
        self.main_window.update_status(f"{status}: {stage}")

    def _show_terminal_message(self, job_view):
        job = job_view.get("job", {})
        status = job.get("status")
        if status == "succeeded":
            return
        title = "任务已取消" if status == "cancelled" else "处理错误"
        details = job_view.get("error_display") or f"状态: {status}\n阶段: {job.get('current_stage')}"
        try:
            QMessageBox.warning(self.main_window, title, details)
        except Exception:
            pass

    def cancel_current_job(self):
        if not self.current_job_id:
            QMessageBox.information(self.main_window, "提示", "当前没有运行中的任务。")
            return
        try:
            self.gui_controller.cancel_job(self.current_job_id)
            self.main_window.update_status("已请求取消任务")
        except Exception as e:
            QMessageBox.warning(self.main_window, "取消失败", str(e))

    def open_current_result_dir(self):
        job_view = self.current_job_view or (self.recent_job_views[0] if self.recent_job_views else None)
        result_dir = job_view.get("result_dir") if job_view else None
        try:
            self.gui_controller.open_result_dir(result_dir)
        except Exception as e:
            QMessageBox.warning(self.main_window, "打开目录失败", str(e))

    def show_current_job_logs(self):
        job_view = self.current_job_view or (self.recent_job_views[0] if self.recent_job_views else None)
        job_id = job_view.get("job", {}).get("job_id") if job_view else None
        if not job_id:
            QMessageBox.information(self.main_window, "提示", "当前没有可查看日志的任务。")
            return
        logs = self.gui_controller.get_logs(job_id)
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle(f"任务日志 - {job_id}")
        dialog.resize(720, 420)
        dlg_layout = QVBoxLayout(dialog)
        text = QTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText("\n".join(logs) if logs else "暂无日志")
        dlg_layout.addWidget(text)
        dialog.exec_()

    def _poll_current_job(self):
        if not self.current_job_id:
            if self.status_timer.isActive():
                self.status_timer.stop()
            return
        try:
            job_view = self.gui_controller.get_job_view(self.current_job_id)
            self.current_job_view = job_view
            self._append_recent_job(job_view)
            self._render_job_summary(job_view)
            self._update_main_window_from_job(job_view)
            status = job_view.get("job", {}).get("status")
            if status in {"succeeded", "failed", "cancelled"}:
                if self.status_timer.isActive():
                    self.status_timer.stop()
                self._finalize_job(job_view)
        except Exception as e:
            logging.error(f"[LocalVideoManager] 轮询 job 状态失败: {e}")
    
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
                
                clips_base_dir_path = self._resolve_local_replay_output_base(twitch_folder)
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
                    self.current_processing_dir = video_clips_dir
                    logging.info(f"[pipeline] 已标记文件夹为正在处理: {video_clips_dir}")


                # === 默认复用同视频最新未完成 run，只有显式重新开始才创建新 run ===
                try:
                    current_run_dir, reused_existing_run = self._allocate_video_run_dir(
                        video_clips_dir,
                        resume_mode,
                    )
                    logging.info(
                        "[pipeline] %s运行目录: %s",
                        "复用" if reused_existing_run else "创建新",
                        current_run_dir,
                    )
                except Exception as e:
                    logging.warning(f"[pipeline] 创建run目录失败，回退到根目录: {e}")
                    current_run_dir = video_clips_dir
                
                # 将本次切片输出写到当前run目录
                output_clips_dir = current_run_dir
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
                
                
                job = self.gui_controller.create_job(
                    video_path=video_path,
                    chat_path=chat_path,
                    config_manager=self.config_manager,
                    run_dir=Path(current_run_dir),
                    output_clips_dir=output_clips_dir,
                    metadata={"source": "gui", "entrypoint": "LocalVideoManager"},
                )
                return {
                    "job": job,
                    "run_dir": current_run_dir,
                    "video_base": safe_basename,
                    "meta_path": self.current_run_meta_path,
                }
            
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
                        job_payload = locals().get("job", {})
                        if not isinstance(job_payload, dict) or not job_payload.get("job_id"):
                            self.parent.remove_processing_folder(video_clips_dir)
                            logging.info(f"[pipeline] 已移除文件夹保护标记: {video_clips_dir}")
                except Exception as e:
                    logging.warning(f"移除文件夹保护标记失败: {e}")
                
                # 进度系统的停止改由主线程回调 on_pipeline_done/on_pipeline_err 处理
                # 避免在工作线程中触发Qt计时器/父子关系跨线程操作，导致
                # "QBasicTimer::start" 和 "QObject::setParent" 警告
        
        # 启动后台线程
        worker = ThreadSafeWorker(pipeline_worker)
        worker.finished.connect(lambda result: self.on_job_created(result, worker))
        worker.error.connect(lambda msg: self.on_pipeline_err(msg, worker))
        
        # 添加到当前工作线程列表
        self.current_workers.append(worker)
        
        # 启动线程
        worker.start()
        
        logging.info("[DEBUG] 后台处理线程已启动")

    def on_job_created(self, result, worker):
        """任务创建完成回调（主线程）。"""
        try:
            try:
                if worker in self.current_workers:
                    self.current_workers.remove(worker)
            except Exception:
                pass
            job = result.get("job", {}) if isinstance(result, dict) else {}
            job_id = job.get("job_id")
            if not job_id:
                raise RuntimeError("GUI job creation did not return job_id")
            self.current_job_id = job_id
            self.current_job_view = self.gui_controller.get_job_view(job_id)
            self._append_recent_job(self.current_job_view)
            self._render_job_summary(self.current_job_view)
            if not self._progress_started and hasattr(self.parent, 'start_processing_progress'):
                self.parent.start_processing_progress(0, 0)
                self._progress_started = True
            self._update_main_window_from_job(self.current_job_view)
            if not self.status_timer.isActive():
                self.status_timer.start()
            logging.info(f"[LocalVideoManager] job created: {job_id}")
        except Exception as e:
            logging.error(f"on_job_created 处理异常: {e}")
            self.on_pipeline_err(str(e), worker)

    def _finalize_job(self, job_view):
        job = job_view.get("job", {})
        status = job.get("status")
        success = status == "succeeded"
        try:
            if hasattr(self.parent, 'stop_processing_progress'):
                self.parent.stop_processing_progress(success=success)
        except Exception:
            pass
        try:
            if hasattr(self.parent, 'smart_predictor') and self.parent.smart_predictor:
                sp = self.parent.smart_predictor
                if hasattr(sp, 'end_session'):
                    sp.end_session(success=success)
        except Exception as e:
            logging.debug(f"结束智能预测会话失败: {e}")
        try:
            meta_path = getattr(self, "current_run_meta_path", None)
            if meta_path and hasattr(self.parent, "clips_manager") and self.parent.clips_manager:
                finalize_fn = getattr(self.parent.clips_manager, "finalize_run", None)
                if callable(finalize_fn):
                    clip_list: List[str] = []
                    result_payload = job.get("result", {}) if isinstance(job.get("result"), dict) else {}
                    for path in result_payload.get("clips", []) or []:
                        if path:
                            clip_list.append(str(Path(path)))
                    finalize_fn(meta_path, success=success, clip_paths=clip_list if success else None)
        except Exception as meta_err:
            logging.debug(f"运行元数据更新失败: {meta_err}")
        finally:
            self.current_run_meta_path = None
            self.current_run_video_base = None
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
        try:
            if self.current_processing_dir and hasattr(self.parent, 'remove_processing_folder'):
                self.parent.remove_processing_folder(self.current_processing_dir)
        except Exception as e:
            logging.debug(f"移除处理目录标记失败: {e}")
        finally:
            self.current_processing_dir = None
        if not success:
            self._show_terminal_message(job_view)
        self.current_job_id = None
        self._progress_started = False

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
                self.current_job_id = None
                self._progress_started = False
                try:
                    if self.current_processing_dir and hasattr(self.parent, 'remove_processing_folder'):
                        self.parent.remove_processing_folder(self.current_processing_dir)
                except Exception as e:
                    logging.debug(f"移除处理目录标记失败: {e}")
                finally:
                    self.current_processing_dir = None

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
                error_view = {
                    "job": {
                        "job_id": self.current_job_id or "setup_failed",
                        "status": "failed",
                        "current_stage": "gui_submit",
                        "progress": {},
                        "error_summary": str(msg),
                        "run_dir": None,
                    },
                    "runtime": {},
                    "current_runtime": None,
                    "active_runtime": False,
                    "result_dir": None,
                    "error_display": f"状态: failed\n阶段: gui_submit\n摘要: {msg}",
                }
                self.current_job_view = error_view
                self._append_recent_job(error_view)
                self._render_job_summary(error_view)
                QMessageBox.critical(self.main_window, "处理错误", error_view["error_display"])
            except Exception:
                pass
        except Exception as e:
            logging.error(f"on_pipeline_err 处理异常: {e}")
