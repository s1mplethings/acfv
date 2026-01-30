# main_window.py - 主窗口模块

import os
import sys
import json
import logging
import time

# 可选依赖
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    
try:
    import pickle
    PICKLE_AVAILABLE = True
except ImportError:
    PICKLE_AVAILABLE = False
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QProgressBar, QLabel, QTabWidget,
    QMessageBox, QDialog, QTextEdit
)

# 导入自定义模块
from acfv.config.config import ConfigManager
from acfv.features.modules.ui_components import SettingsDialog, Worker
from acfv.features.modules.progress_manager import ProgressManager
from acfv.features.modules.progress_widget import ProgressWidget, ProgressUpdateWorker
from acfv.features.modules.beautiful_progress_widget import SimpleBeautifulProgressBar
from acfv.ui.tabs import create_clips_tab, create_local_tab, create_twitch_tab, create_rag_pref_tab
from acfv.ui.stream_monitor_editor import StreamMonitorEditorWidget
from acfv.lifecycle.tray_manager import TrayManager
from acfv.runtime.storage import processing_path

logger = logging.getLogger(__name__)


# 简化的工作线程
class SimpleWorker(QThread):
    """简单的工作线程基类"""
    status_updated = pyqtSignal(str)  # 状态消息
    finished_task = pyqtSignal()      # 任务完成
    error_occurred = pyqtSignal(str)  # 错误消息
    
    def __init__(self, task_name: str):
        super().__init__()
        self.task_name = task_name
        self.should_stop = False
        
    def update_status(self, status: str):
        """更新状态"""
        if not self.should_stop:
            self.status_updated.emit(f"{self.task_name}: {status}")
            logger.info(f"[ui] {self.task_name}: {status}")
        
    def log_error(self, error: str):
        """记录错误"""
        logger.error(f"[{self.task_name}] {error}")
        if not self.should_stop:
            self.error_occurred.emit(error)
        
    def stop(self):
        """停止任务"""
        self.should_stop = True
        if self.isRunning():
            self.quit()
            if not self.wait(2000):  # 等待2秒
                self.terminate()
                self.wait(1000)

# 简化的具体任务线程
class VideoProcessWorker(SimpleWorker):
    """简化的视频处理线程"""
    def __init__(self, video_path: str):
        super().__init__("视频处理")
        self.video_path = video_path
        
    def run(self):
        try:
            if self.should_stop:
                return
            self.update_status("开始处理...")
            
            # 模拟处理过程，定期检查停止标志
            for i in range(10):  # 将原来的sleep(1)分成10个100ms
                if self.should_stop:
                    self.update_status("处理已停止")
                    return
                self.msleep(100)
            
            if not self.should_stop:
                self.update_status("处理完成")
                self.finished_task.emit()
        except Exception as e:
            if not self.should_stop:
                self.log_error(f"视频处理失败: {str(e)}")

class DownloadWorker(SimpleWorker):
    """简化的下载线程"""
    def __init__(self, url: str, save_path: str):
        super().__init__("下载任务")
        self.url = url
        self.save_path = save_path
        
    def run(self):  # pragma: no cover - threading / UI
        try:
            if self.should_stop:
                return
            self.update_status("开始下载...")
            for _ in range(10):
                if self.should_stop:
                    self.update_status("下载已停止")
                    if os.path.exists(self.save_path):
                        os.remove(self.save_path)
                    return
                self.msleep(100)
            if not self.should_stop:
                self.update_status("下载完成")
                self.finished_task.emit()
        except Exception as e:  # single handler
            if not self.should_stop:
                self.log_error(f"下载失败: {e}")
                if os.path.exists(self.save_path):
                    try:
                        os.remove(self.save_path)
                    except OSError:
                        pass
            self.update_status("下载完成")
            self.finished_task.emit()
    
    def _calculate_remaining_time(self, percentage):
        """改进的时间计算"""
        if percentage <= 0:
            return "计算中..."
        elif percentage >= 100:
            return "已完成"
        
        elapsed = time.time() - self.start_time
        
        if percentage < 5:  # 进度太少，使用预估
            total_estimated = sum(stage["estimated_time"] for stage in self.stages.values())
            return self._format_time(total_estimated)
        
        # 基于当前进度的预估
        estimated_total = elapsed / (percentage / 100)
        remaining = max(0, estimated_total - elapsed)
        
        # 根据阶段调整预估
        if percentage < 30:  # 早期阶段，时间可能更长
            remaining *= 1.2
        elif percentage > 80:  # 后期阶段，通常更快完成
            remaining *= 0.8
        
        return self._format_time(remaining)
    
    def _format_time(self, seconds):
        """格式化时间"""
        if seconds < 60:
            return f"{seconds:.0f}秒"
        elif seconds < 3600:
            return f"{seconds/60:.1f}分钟" 
        else:
            return f"{seconds/3600:.1f}小时"
    
    def stop(self):
        """停止线程"""
        logging.info("正在停止ProgressWorker...")
        
        # 设置停止标志
        self.is_running = False
        self._stop_requested = True
        
        # 优雅停止
        self.quit()
        
        # 等待线程停止
        if not self.wait(3000):  # 等待3秒
            logging.warning("ProgressWorker未能在3秒内停止，强制终止")
            self.terminate()
            if not self.wait(2000):  # 再等待2秒
                logging.error("ProgressWorker强制终止失败")
            else:
                logging.info("ProgressWorker强制终止成功")
        else:
            logging.info("ProgressWorker优雅停止成功")
        
        logging.info("ProgressWorker已停止")


# 删除了智能进度预测相关的导入和变量

def log_info(message):
    logger.info(message)

def log_error(message):
    logger.error(message)

# 辅助函数
def filter_meaningless_content(data, is_chat=False):
    """过滤无意义内容的简单实现"""
    if not data:
        return []
    
    filtered = []
    for item in data:
        if is_chat:
            # 弹幕过滤：过滤太短的消息
            message = item.get('message', '')
            if len(message.strip()) >= 2:
                filtered.append(item)
        else:
            # 转录过滤：过滤太短的文本
            text = item.get('text', '')
            if len(text.strip()) >= 3:
                filtered.append(item)
    
    return filtered

def build_content_index(segments):
    """构建内容索引的简单实现"""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        import numpy as np
        
        if not segments:
            return None, None, []
        
        # 提取文本
        texts = [seg.get('text', '') for seg in segments]
        texts = [text for text in texts if text.strip()]
        
        if not texts:
            return None, None, []
        
        # 创建TF-IDF向量器
        vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2)
        )
        
        # 向量化
        tfidf_matrix = vectorizer.fit_transform(texts)
        
        # 创建FAISS索引
        if tfidf_matrix.shape[0] > 0:
            # 转换为dense numpy数组
            dense_matrix = tfidf_matrix.toarray().astype('float32')
            
            # 创建FAISS索引
            dimension = dense_matrix.shape[1]
            index = faiss.IndexFlatIP(dimension)  # 内积索引
            index.add(dense_matrix)
            
            return index, vectorizer, texts
        else:
            return None, None, []
            
    except Exception as e:
        logging.error(f"构建内容索引失败: {e}")
        return None, None, []


class MainWindow(QMainWindow):
    """主窗口类"""
    
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        
        # 初始化各个管理器
        self.twitch_tab = None
        self.local_manager = None
        self.clips_manager = None
        self.index_worker = None
        self.tray_manager = None
        self._force_exit = False
        self._monitor_autostarted = False
        
        # 初始化新的进度系统
        self.progress_manager = ProgressManager()
        self.progress_widget = None
        self.progress_worker = None
        # 当前进度用于时间预测
        self._current_progress_percent = 0.0
        
        # 初始化智能进度预测器
        self.smart_predictor = None
        try:
            from acfv.features.modules.smart_progress_predictor import SmartProgressPredictor
            self.smart_predictor = SmartProgressPredictor()
            log_info("[GUI] 智能进度预测器初始化成功")
            
            # 🆕 显示历史预测统计信息
            if hasattr(self.smart_predictor, 'get_prediction_stats'):
                stats = self.smart_predictor.get_prediction_stats()
                if stats.get('total_sessions', 0) > 0:
                    log_info(f"📊 历史预测统计: {stats['total_sessions']}次处理, 平均{stats['average_rate']}, 总计{stats['total_processing_time']}")
                else:
                    log_info("📊 首次使用智能预测器，将开始记录处理历史")
                    
        except ImportError:
            try:
                from acfv.features.modules.smart_progress_predictor import SimplePredictor
                self.smart_predictor = SimplePredictor()
                log_info("[GUI] 使用简化进度预测器")
            except ImportError:
                # 创建最基础的预测器
                class BasicPredictor:
                    def predict_video_processing_time(self, duration, size_mb):
                        minutes = duration / 60 if duration > 60 else 1
                        return f"{int(minutes * 0.5)}-{int(minutes * 1.0)}分钟"
                self.smart_predictor = BasicPredictor()
                log_info("[GUI] 使用基础进度预测器")
        except Exception as e:
            log_error(f"[GUI] 智能进度预测器初始化失败: {e}")
            # 创建最基础的预测器
            class BasicPredictor:
                def predict_video_processing_time(self, duration, size_mb):
                    return "预估计算中..."
            self.smart_predictor = BasicPredictor()
        
        # 添加兼容性的老版本进度条
        self.progress = None
        
        # 初始化断点续传管理器
        self.checkpoint_manager = None
        try:
            # 修正导入路径: 原 modules.analyze_data 实际位于 processing 包
            from acfv.processing.analyze_data import CheckpointManager
            self.checkpoint_manager = CheckpointManager()
            log_info("[GUI] 断点续传模块加载成功")
        except ImportError as e:
            log_error(f"[GUI] 断点续传模块导入失败: {e}")

        self.setWindowTitle("视频处理工具 - 模块化版本")
        self.resize(1000, 600)
        
        # 设置窗口图标
        self.set_window_icon()
        
        # 设置窗口置顶
        self.set_window_topmost()

        self.init_ui()
        self.init_managers()
        self._init_tray_icon()

    def init_ui(self):
        """初始化用户界面"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        # 顶部按钮
        self.init_top_buttons(layout)
        # 进度条和状态标签
        self.init_progress_display(layout)
        # 默认标签页（不做自定义样式）
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        layout.addWidget(self.tabs)

    def init_top_buttons(self, layout):
        """初始化顶部按钮 (设置/处理视频)"""
        hb = QHBoxLayout()
        hb.setContentsMargins(8, 4, 8, 0)
        hb.setSpacing(6)

        # 基础按钮
        btn_set = QPushButton("设置")
        btn_set.clicked.connect(self.open_settings)
        btn_all = QPushButton("处理视频")
        btn_all.clicked.connect(self.process_selected_video)

        # 添加到布局
        hb.addWidget(btn_set)
        hb.addWidget(btn_all)
        layout.addLayout(hb)

    def init_progress_display(self, layout):
        """初始化进度显示系统 - 修复重复进度条问题"""
        # 🎨 只使用一个主要进度条 - SimpleBeautifulProgressBar
        self.simple_progress = SimpleBeautifulProgressBar(self)
        self.simple_progress.set_progress_manager(self.progress_manager)
        layout.addWidget(self.simple_progress)
        # 用户要求：暂时只显示进度条，不做时间预测
        self.enable_time_prediction = True
        
        # 完全禁用其他进度组件，避免重复显示
        self.progress_widget = None  # 禁用原版进度组件
        self.progress = None  # 禁用兼容性进度条
        
        # 详细进度标签（文字说明）
        self.detailed_progress = QLabel("")
        self.detailed_progress.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #666;
                padding: 5px;
                border: 1px solid #ddd;
                border-radius: 3px;
                background-color: #f9f9f9;
            }
        """)
        self.detailed_progress.setVisible(False)
        layout.addWidget(self.detailed_progress)
        
        # 时间预测标签 - 已集成到 SimpleBeautifulProgressBar 中，不再需要独立标签
        
        # 状态标签
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2b6cb0;
                padding: 10px;
                border: 1px solid #e2e8f0;
                border-radius: 5px;
                background-color: #f7fafc;
            }
        """)
        layout.addWidget(self.status_label)
        self.time_prediction_label = QLabel("预计剩余时间：--")
        self.time_prediction_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #2d3748;
                padding: 6px;
                border: 1px dashed #cbd5f5;
                border-radius: 4px;
                background-color: #f0f4ff;
            }
        """)
        self.time_prediction_label.setVisible(False)
        layout.addWidget(self.time_prediction_label)
        self.predicted_total_time_str = None

    def init_managers(self):
        """初始化各个功能管理器"""
        twitch_handle = create_twitch_tab(self, self.config_manager)
        self.tab_twitch = twitch_handle.widget
        self.twitch_tab = twitch_handle.controller
        self.tabs.addTab(twitch_handle.widget, twitch_handle.title)

        local_handle = create_local_tab(self, self.config_manager)
        self.tab_local = local_handle.widget
        self.local_manager = local_handle.controller
        self.tabs.addTab(local_handle.widget, local_handle.title)
        try:
            self.local_manager.refresh_local_videos()
        except Exception as e:
            logging.debug(f"自动加载本地回放失败: {e}")

        clips_handle = create_clips_tab(self, self.config_manager)
        self.tab_clips = clips_handle.widget
        self.clips_manager = clips_handle.controller
        self.tabs.addTab(clips_handle.widget, clips_handle.title)

        rag_pref_handle = create_rag_pref_tab(self, self.config_manager)
        self.tab_rag_pref = rag_pref_handle.widget
        self.rag_pref_widget = rag_pref_handle.controller
        self.tabs.addTab(rag_pref_handle.widget, rag_pref_handle.title)

        # Stream monitor tab
        self.stream_monitor_widget = StreamMonitorEditorWidget()
        self.tabs.addTab(self.stream_monitor_widget, "直播监控")
        QTimer.singleShot(0, self._auto_launch_stream_monitor)

    def _init_tray_icon(self):
        try:
            tray = TrayManager(self)
            if tray.start():
                self.tray_manager = tray
            else:
                self.tray_manager = None
        except Exception as exc:
            logging.debug(f"系统托盘不可用: {exc}")
            self.tray_manager = None

    def _auto_launch_stream_monitor(self):
        if self._monitor_autostarted:
            return
        self._monitor_autostarted = True
        if hasattr(self, "stream_monitor_widget"):
            self.stream_monitor_widget.refresh_from_disk()
            if self.stream_monitor_widget.has_enabled_targets():
                self.tabs.setCurrentWidget(self.stream_monitor_widget)
                self.stream_monitor_widget.start_monitor()

    def set_window_icon(self):
        """设置窗口图标"""
        try:
            # 从配置中读取图标路径
            icon_path = self.config_manager.get("APP_ICON_PATH", "")
            if icon_path:
                candidate = icon_path
                if not os.path.isabs(candidate):
                    module_dir = os.path.dirname(os.path.abspath(__file__))
                    candidate = os.path.join(module_dir, candidate)
                    if not os.path.exists(candidate):
                        candidate = icon_path
                if os.path.exists(candidate):
                    from PyQt5.QtGui import QIcon
                    self.setWindowIcon(QIcon(candidate))
                    logging.info(f"已设置窗口图标: {candidate}")
                    return
            # 尝试默认图标路径
            module_dir = os.path.dirname(os.path.abspath(__file__))
            default_icons = [
                os.path.join(module_dir, "acfv.png"),
                "./config/icon.png",
                "./assets/acfv-logo.ico",
                "./assets/acfv-logo.png",
                "./icon.png",
                "./icons/app.png",
                "./icons/app.ico"
            ]
            for icon_path in default_icons:
                if os.path.exists(icon_path):
                    from PyQt5.QtGui import QIcon
                    self.setWindowIcon(QIcon(icon_path))
                    logging.info(f"已设置默认窗口图标: {icon_path}")
                    break
        except Exception as e:
            logging.warning(f"设置窗口图标失败: {e}")

    def set_window_topmost(self):
        """设置窗口置顶"""
        try:
            # 从配置中读取是否置顶
            stays_on_top = self.config_manager.get("WINDOW_STAYS_ON_TOP", False)
            if stays_on_top:
                # 初始置顶: 仅在启动后短暂置顶，然后自动恢复
                self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
                logging.info("窗口已设置为初始置顶 (将于短暂延时后自动恢复正常)")
                try:
                    # 启动后 1.5 秒自动取消置顶，避免一直在最前
                    QTimer.singleShot(1500, self.unset_window_topmost)
                except Exception as e:
                    logging.warning(f"计划取消初始置顶失败: {e}")
            else:
                logging.info("窗口未设置为置顶")
        except Exception as e:
            logging.warning(f"设置窗口置顶失败: {e}")

    def unset_window_topmost(self):
        """取消窗口置顶 (初始置顶后自动调用)"""
        try:
            if self.windowFlags() & Qt.WindowStaysOnTopHint:
                # 清除置顶标志
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
                # 重新显示以应用新 flags
                self.show()
                logging.info("已自动取消初始置顶, 窗口恢复正常层级")
        except Exception as e:
            logging.warning(f"取消窗口置顶失败: {e}")

    def closeEvent(self, event):
        """窗口关闭事件处理 - 默认最小化到托盘，选择“退出”才真正关闭。"""
        if not getattr(self, "_force_exit", False) and self.tray_manager:
            event.ignore()
            self.hide()
            self.tray_manager.show_hidden_tip()
            return

        self._shutdown_cleanup()
        if self.tray_manager:
            self.tray_manager.shutdown()
        super().closeEvent(event)

    def restore_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def exit_from_tray(self):
        self._force_exit = True
        self.restore_from_tray()
        self.close()

    def _shutdown_cleanup(self):
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        try:
            import traceback
            logging.info("窗口关闭事件被触发")
            logging.info("调用栈:")
            for line in traceback.format_stack()[-5:]:
                logging.info(f"  {line.strip()}")

            logging.info("开始清理应用程序资源...")
            self.is_shutting_down = True
            self._cleanup_timers()
            self.stop_progress_display()
            self.stop_smart_progress()
            if self.progress_worker:
                logging.info("正在停止智能进度更新线程...")
                self.progress_worker.stop()
            self._stop_all_processing()

            if self.local_manager:
                try:
                    logging.info("正在清理本地视频管理器...")
                    if hasattr(self.local_manager, 'stop_all_processing'):
                        self.local_manager.stop_all_processing()
                    self.local_manager.cleanup()
                except (RuntimeError, AttributeError) as err:
                    logging.debug(f"清理本地视频管理器时忽略错误: {err}")

            for manager in (self.twitch_tab, self.clips_manager):
                try:
                    if manager and hasattr(manager, 'cleanup'):
                        logging.info(f"正在清理管理器: {manager.__class__.__name__}")
                        if hasattr(manager, 'stop_all_processing'):
                            manager.stop_all_processing()
                        manager.cleanup()
                except (RuntimeError, AttributeError) as err:
                    logging.debug(f"清理管理器时忽略错误: {err}")

            self._cleanup_direct_threads()
        except Exception as exc:
            logging.error(f"清理资源时发生错误: {exc}")
        logging.info("应用程序资源清理完成")

    def _cleanup_timers(self):
        """清理所有定时器"""
        try:
            logging.info("正在清理定时器...")
            
            # 清理其他可能的定时器
            timers = []
            if hasattr(self, 'progress_update_timer'):
                timers.append(('progress_update_timer', self.progress_update_timer))
            if hasattr(self, 'auto_save_timer'):
                timers.append(('auto_save_timer', self.auto_save_timer))
            if hasattr(self, 'status_update_timer'):
                timers.append(('status_update_timer', self.status_update_timer))
            
            for timer_name, timer in timers:
                if timer and hasattr(timer, 'isActive'):
                    try:
                        if timer.isActive():
                            timer.stop()
                        timer.deleteLater()
                        setattr(self, timer_name, None)
                        logging.info(f"已停止定时器: {timer_name}")
                    except Exception as e:
                        logging.debug(f"清理定时器 {timer_name} 时忽略错误: {e}")
            
            # 🆕 清理进度组件
            if hasattr(self, 'progress_widget') and self.progress_widget:
                try:
                    logging.info("清理进度组件...")
                    if hasattr(self.progress_widget, 'cleanup'):
                        self.progress_widget.cleanup()
                    else:
                        self.progress_widget.stop_monitoring()
                    self.progress_widget = None
                    logging.info("进度组件已清理")
                except Exception as e:
                    logging.debug(f"清理进度组件时忽略错误: {e}")
            
            # 🆕 清理进度工作线程
            if hasattr(self, 'progress_worker') and self.progress_worker:
                try:
                    logging.info("清理进度工作线程...")
                    self.progress_worker.stop()
                    if hasattr(self.progress_worker, 'deleteLater'):
                        self.progress_worker.deleteLater()
                    self.progress_worker = None
                    logging.info("进度工作线程已清理")
                except Exception as e:
                    logging.debug(f"清理进度工作线程时忽略错误: {e}")
            
        except Exception as e:
            logging.debug(f"清理定时器时发生错误: {e}")
    
    def _stop_all_processing(self):
        """停止所有后台处理进程"""
        try:
            logging.info("正在停止所有后台处理进程...")
            
            # 停止本地回放处理任务
            try:
                if getattr(self, "local_manager", None) and hasattr(self.local_manager, "cleanup_workers"):
                    logging.info("停止本地回放处理任务")
                    self.local_manager.cleanup_workers()
            except Exception as e:
                logging.debug(f"停止本地处理任务时忽略错误: {e}")
            
            # 停止任何可能正在运行的分析进程
            try:
                # 通过创建停止标志文件来通知处理进程停止
                stop_flag_file = processing_path("stop_flag.txt")
                stop_flag_file.parent.mkdir(parents=True, exist_ok=True)
                with stop_flag_file.open('w', encoding='utf-8') as f:
                    f.write("STOP")
                logging.info("已创建停止标志文件")
            except Exception as e:
                logging.debug(f"创建停止标志文件时忽略错误: {e}")
            
            # 强制终止Python子进程
            try:
                import psutil
                current_process = psutil.Process()
                children = current_process.children(recursive=True)
                
                for child in children:
                    try:
                        # 只终止Python进程
                        if 'python' in child.name().lower():
                            logging.info(f"终止Python子进程: {child.pid} - {child.name()}")
                            child.terminate()
                            child.wait(timeout=3)
                    except psutil.NoSuchProcess:
                        pass
                    except Exception as e:
                        logging.debug(f"终止子进程时忽略错误: {e}")
                        try:
                            child.kill()
                        except:
                            pass
                            
            except ImportError:
                logging.info("psutil不可用，跳过子进程终止")
            except Exception as e:
                logging.debug(f"终止子进程时忽略错误: {e}")
            
            logging.info("已停止所有后台处理进程")
            
        except Exception as e:
            logging.error(f"停止后台处理进程时发生错误: {e}")
    
    def _final_cleanup(self):
        """最终清理 - 强制终止所有剩余线程"""
        import gc
        import os
        import signal
        
        logging.info("执行最终清理...")
        
        # 查找所有QThread对象并强制终止
        for obj in gc.get_objects():
            try:
                if isinstance(obj, QThread) and obj != QThread.currentThread():
                    if obj.isRunning():
                        logging.warning(f"最终清理：强制终止线程: {obj.__class__.__name__}")
                        obj.terminate()
                        obj.wait(500)  # 等待500ms
            except (RuntimeError, AttributeError, Exception) as e:
                logging.debug(f"最终清理时忽略错误: {e}")
                continue
        
        # 尝试终止所有Python子进程
        try:
            import psutil
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            
            for child in children:
                try:
                    logging.info(f"终止子进程: {child.pid} - {child.name()}")
                    child.terminate()
                    child.wait(timeout=1)  # 等待1秒
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    logging.debug(f"终止子进程时忽略错误: {e}")
        except ImportError:
            logging.info("psutil不可用，跳过子进程清理")
        except Exception as e:
            logging.debug(f"清理子进程时忽略错误: {e}")
        
        logging.info("最终清理完成")

    def _cleanup_direct_threads(self):
        """只清理主窗口直接管理的线程，避免与全局清理冲突"""
        try:
            logging.info("开始清理主窗口直接管理的线程...")
            
            # 清理索引工作线程
            if (hasattr(self, 'index_worker') and 
                self.index_worker and 
                hasattr(self.index_worker, 'isRunning') and
                self.index_worker.isRunning()):
                logging.info("正在停止索引工作线程...")
                if hasattr(self.index_worker, 'stop'):
                    self.index_worker.stop()
                else:
                    self.index_worker.quit()
                    if not self.index_worker.wait(2000):  # 等待2秒
                        logging.warning("索引工作线程未能在2秒内停止，强制终止")
                        self.index_worker.terminate()
                        self.index_worker.wait(1000)
                self.index_worker = None
            
            # 清理进度更新线程
            if hasattr(self, 'progress_worker') and self.progress_worker:
                try:
                    logging.info("正在停止进度更新线程...")
                    if self.progress_worker.isRunning():
                        self.progress_worker.stop()
                        if not self.progress_worker.wait(2000):
                            self.progress_worker.terminate()
                            self.progress_worker.wait(500)
                    self.progress_worker = None
                except (RuntimeError, AttributeError):
                    pass
            
            # 清理所有可能的SimpleWorker、VideoProcessWorker、DownloadWorker实例
            import gc
            from PyQt5.QtCore import QThread
            
            worker_classes = ['SimpleWorker', 'VideoProcessWorker', 'DownloadWorker', 'ThreadSafeWorker', 'Worker']
            for obj in gc.get_objects():
                try:
                    if (isinstance(obj, QThread) and 
                        hasattr(obj, '__class__') and 
                        obj.__class__.__name__ in worker_classes and
                        obj != QThread.currentThread()):
                        
                        thread_name = obj.__class__.__name__
                        if obj.isRunning():
                            logging.info(f"正在停止 {thread_name} 线程...")
                            if hasattr(obj, 'stop'):
                                obj.stop()
                            else:
                                obj.quit()
                                if not obj.wait(2000):
                                    obj.terminate()
                                    obj.wait(1000)
                        else:
                            logging.debug(f"{thread_name} 线程已停止")
                        
                        if hasattr(obj, 'deleteLater'):
                            obj.deleteLater()
                            
                except (RuntimeError, AttributeError) as e:
                    logging.debug(f"清理线程时忽略错误: {e}")
                    continue
                    
            logging.info("主窗口直接管理的线程清理完成")
                    
        except Exception as e:
            logging.debug(f"清理直接管理的线程时忽略错误: {e}")

    def _cleanup_all_threads(self):
        """清理所有线程对象"""
        import gc
        
        logging.info("🧹 开始清理所有线程...")
        
        # 🆕 清理ui_components中的线程
        try:
            from acfv.features.modules.ui_components import SimpleThumbnailLoader, SimpleClipThumbnailLoader, Worker
            
            for obj in gc.get_objects():
                try:
                    if isinstance(obj, (SimpleThumbnailLoader, SimpleClipThumbnailLoader, Worker)):
                        if obj.isRunning():
                            logging.info(f"🧹 停止ui_components线程: {obj.__class__.__name__}")
                            if hasattr(obj, 'stop'):
                                obj.stop()
                            else:
                                obj.quit()
                                if not obj.wait(2000):
                                    obj.terminate()
                                    obj.wait(1000)
                        obj.deleteLater()
                        
                except (RuntimeError, AttributeError) as e:
                    logging.debug(f"清理ui_components线程时忽略错误: {e}")
                    continue
                    
        except Exception as e:
            logging.debug(f"导入ui_components时忽略错误: {e}")
        
        # 查找所有QThread对象
        for obj in gc.get_objects():
            try:
                if isinstance(obj, QThread) and obj != QThread.currentThread():
                    if obj.isRunning():
                        logging.info(f"🧹 发现运行中的线程: {obj.__class__.__name__}")
                        
                        # 🆕 先尝试使用stop方法
                        if hasattr(obj, 'stop'):
                            obj.stop()
                        else:
                            obj.quit()
                        
                        if not obj.wait(2000):  # 等待2秒
                            logging.warning(f"⚠️ 强制终止线程: {obj.__class__.__name__}")
                            obj.terminate()
                            obj.wait(1000)
                    
                    # 确保线程被删除
                    if hasattr(obj, 'deleteLater'):
                        obj.deleteLater()
                        
            except (RuntimeError, AttributeError, Exception) as e:
                # 忽略清理过程中的错误
                logging.debug(f"清理线程时忽略错误: {e}")
                continue
        
        # 特别清理本地视频管理器的线程
        if hasattr(self, 'local_manager') and self.local_manager:
            try:
                if hasattr(self.local_manager, 'cleanup_workers'):
                    self.local_manager.cleanup_workers()
                logging.info("✅ 已清理本地视频管理器线程")
            except Exception as e:
                logging.debug(f"清理本地视频管理器时忽略错误: {e}")
                
        logging.info("✅ 线程清理完成")
    
    def _force_terminate_all_threads(self):
        """强制终止所有剩余线程"""
        import gc
        import os
        import signal
        
        logging.info("开始强制终止所有剩余线程...")
        
        # 查找所有QThread对象并强制终止
        for obj in gc.get_objects():
            try:
                if isinstance(obj, QThread) and obj != QThread.currentThread():
                    if obj.isRunning():
                        logging.warning(f"强制终止剩余线程: {obj.__class__.__name__}")
                        obj.terminate()
                        obj.wait(500)  # 等待500ms
            except (RuntimeError, AttributeError, Exception) as e:
                logging.debug(f"强制终止线程时忽略错误: {e}")
                continue
        
        # 尝试终止所有Python子进程
        try:
            import psutil
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            
            for child in children:
                try:
                    logging.info(f"终止子进程: {child.pid} - {child.name()}")
                    child.terminate()
                    child.wait(timeout=2)  # 等待2秒
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    logging.debug(f"终止子进程时忽略错误: {e}")
        except ImportError:
            logging.info("psutil不可用，跳过子进程清理")
        except Exception as e:
            logging.debug(f"清理子进程时忽略错误: {e}")
        
        logging.info("强制终止线程完成")

    def open_settings(self):
        """打开设置对话框"""
        dlg = SettingsDialog(self.config_manager, self)
        result = dlg.exec_()
        if result == dlg.Accepted and hasattr(self, "stream_monitor_widget"):
            self.stream_monitor_widget.stop_monitor()
            self.stream_monitor_widget.refresh_from_disk()

    # ============================================================================
    # 智能进度预测系统方法
    # ============================================================================

    def start_smart_progress(self, video_path=None):
        """启动改进的进度显示"""
        try:
            # 显示主要进度组件
            if hasattr(self, 'simple_progress') and self.simple_progress:
                self.simple_progress.setVisible(True)
            
            if hasattr(self, 'stage_label'):
                self.stage_label.setVisible(True)
                self.stage_label.setText("🎯 准备开始...")
            
            # 显示进度条和状态信息 - 使用主要进度条
            if hasattr(self, 'simple_progress'):
                self.simple_progress.setVisible(True)  # 显示主要进度条
                self.simple_progress.start_progress("初始化处理...")
            if self.enable_time_prediction and hasattr(self, 'time_prediction_label'):
                self.time_prediction_label.setVisible(False)
                self.time_prediction_label.setText("预计剩余时间：--")
                self.predicted_total_time_str = None
            
            if hasattr(self, 'detailed_progress'):
                self.detailed_progress.setVisible(False)  # 隐藏详细进度避免重复
                # self.detailed_progress.setText("📋 初始化处理流程...")
            
            # 时间预估显示通过 simple_progress 处理，无需独立标签
            
            # 隐藏兼容性进度条避免重复显示
            if hasattr(self, 'progress') and self.progress:
                pass  # progress已设为None，跳过
                # self.simple_progress.setValue(0)  # 重置到0%
            
            # 如果有视频路径，计算预估时间
            if video_path and self.smart_predictor:
                try:
                    import os
                    # 获取视频文件信息
                    if os.path.exists(video_path):
                        file_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
                        
                        # 尝试获取实际视频时长
                        estimated_duration = file_size * 0.1  # 默认估算
                        try:
                            import subprocess
                            cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video_path]
                            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10)
                            if result.returncode == 0 and result.stdout.strip():
                                estimated_duration = float(result.stdout.strip()) / 60.0  # 转换为分钟
                        except Exception as e:
                            logging.debug(f"获取视频时长失败，使用文件大小估算: {e}")
                        
                        # 🆕 开始智能预测会话
                        if hasattr(self.smart_predictor, 'start_session'):
                            self.smart_predictor.start_session(estimated_duration * 60, file_size, video_path)
                            log_info("📊 开始基于历史记录的智能预测会话")
                        
                        if self.enable_time_prediction and self.smart_predictor:
                            try:
                                predicted_time = self.smart_predictor.predict_video_processing_time(
                                    estimated_duration * 60, file_size
                                )
                                self.predicted_total_time_str = predicted_time
                                if hasattr(self.smart_predictor, "start_time"):
                                    self.smart_predictor.start_time = time.time()
                                if predicted_time and hasattr(self, "time_prediction_label"):
                                    self.time_prediction_label.setText(f"预计处理耗时：{predicted_time}")
                                    self.time_prediction_label.setVisible(True)
                            except Exception as predict_err:
                                logging.debug(f"时间预测失败，继续处理: {predict_err}")
                        
                        log_info(f"📊 开始视频处理 (文件大小: {file_size:.1f}MB, 时长: {estimated_duration:.1f}分钟)")
                        
                except Exception as e:
                    log_error(f"计算预估时间失败: {e}")
            
            # 简化的状态显示 - 不再使用复杂的进度工作线程
            self.status_label.setText("正在处理...")
            self.status_label.setVisible(True)

            # 启动时间预测定时器（每秒刷新）
            if self.enable_time_prediction:
                if not hasattr(self, 'time_update_timer') or self.time_update_timer is None:
                    self.time_update_timer = QTimer()
                    self.time_update_timer.timeout.connect(self.update_time_prediction)
                self.processing_start_time = time.time()
                self.time_update_timer.start(1000)
            
            logging.info("✅ 进度系统已启动")
            
        except Exception as e:
            logging.error(f"❌ 启动进度系统失败: {e}")
            self.show_error_message("进度系统启动失败", str(e))
            
    def on_progress_updated(self, task_id: str, progress: int, eta: str):
        """处理进度更新 - 使用简洁进度条"""
        if hasattr(self, 'simple_progress') and self.simple_progress:
            self.simple_progress.set_progress(progress)
        # ETA 现在通过 simple_progress 自动显示，无需独立更新
        
    def on_status_updated(self, task_id: str, status: str):
        """处理状态更新 - 使用属性检查"""
        if hasattr(self, 'stage_label'):
            self.stage_label.setText(status)
        
    def on_message_updated(self, message: str):
        """处理消息更新 - 使用属性检查"""
        if hasattr(self, 'detailed_progress'):
            self.detailed_progress.setText(message)
        
    def on_error_occurred(self, error: str):
        """处理错误"""
        # 🆕 结束智能预测会话（标记为失败）
        if hasattr(self, 'smart_predictor') and self.smart_predictor:
            if hasattr(self.smart_predictor, 'end_session'):
                self.smart_predictor.end_session(success=False)
                log_info("📊 智能预测会话已结束（处理失败）")
        
        self.show_error_message("处理错误", error)
        self.stop_processing(success=False)
        
    def on_task_completed(self, task_id: str):
        """处理任务完成"""
        self.stop_processing()

    def on_time_updated(self, time_str: str):
        """处理预计剩余时间更新 - 通过 simple_progress 显示"""
        # 时间显示现在集成在 simple_progress 中，无需独立更新
        pass

    def update_time_prediction(self):
        """更新时间预测 - 根据智能预测器显示剩余时间"""
        if not self.enable_time_prediction:
            return
        if not hasattr(self, "smart_predictor") or not self.smart_predictor:
            return
        if not hasattr(self, "time_prediction_label"):
            return

        remaining = None
        try:
            if hasattr(self.smart_predictor, "get_estimated_remaining_time"):
                remaining = self.smart_predictor.get_estimated_remaining_time()
        except Exception as err:
            logging.debug(f"更新时间预测失败: {err}")
            remaining = None

        if remaining:
            self.time_prediction_label.setText(f"预计剩余时间：{remaining}")
            self.time_prediction_label.setVisible(True)
        elif getattr(self, "predicted_total_time_str", None):
            self.time_prediction_label.setText(f"预计处理耗时：{self.predicted_total_time_str}")
            self.time_prediction_label.setVisible(True)
        else:
            self.time_prediction_label.setVisible(False)

    # ...existing code...
    def start_processing_progress(self, video_duration: float = 0, file_size: float = 0):
        """开始处理进度显示"""
        try:
            # 初始化进度管理器
            self.progress_manager.start_processing(video_duration, file_size)
            
            # 创建进度更新工作线程
            self.progress_worker = ProgressUpdateWorker(self.progress_manager)
            self.progress_worker.progress_updated.connect(self.on_pipeline_progress_updated)
            self.progress_worker.stage_finished.connect(self.on_stage_finished)
            self.progress_worker.start()
            
            # 开始进度显示 - 只使用主要进度条
            if hasattr(self, 'simple_progress'):
                self.simple_progress.setVisible(True)
                self.simple_progress.start_progress("开始处理...")
            self.status_label.setVisible(False)  # 隐藏简单状态标签
            
            # 时间预测禁用：不创建 time_update_timer
            # 记录开始时间用于时间预测
            self.processing_start_time = time.time()
            
            # 不启动任何时间预测定时器
            
            log_info("进度显示系统已启动")
            
        except Exception as e:
            log_error(f"启动进度显示失败: {e}")

    def on_pipeline_progress_updated(self, stage_name: str, substage_index: int, progress: float):
        """处理进度更新信号"""
        self.progress_manager.update_substage(stage_name, substage_index, progress)

    def on_stage_finished(self, stage_name: str):
        """处理阶段完成信号"""
        self.progress_manager.finish_stage(stage_name)
        self.progress_manager.next_stage()

    def update_processing_progress(self, stage_name: str, substage_index: int, progress: float = 0.0):
        """外部调用更新进度"""
        if self.progress_worker:
            self.progress_worker.update_progress(stage_name, substage_index, progress)

    def finish_processing_stage(self, stage_name: str):
        """外部调用完成阶段"""
        if self.progress_worker:
            self.progress_worker.finish_stage(stage_name)

    def stop_processing_progress(self, success: bool = True):
        """停止进度显示"""
        try:
            # 停止主要进度条
            if hasattr(self, 'simple_progress'):
                self.simple_progress.setVisible(False)
                
            # 停止其他进度条（如果启用的话）
            # if self.progress_widget:
            #     self.progress_widget.stop_monitoring()
                
            # if self.beautiful_progress:
            #     self.beautiful_progress.stop_monitoring()
                
            # 🆕 停止时间预测定时器
            if hasattr(self, 'time_update_timer') and self.time_update_timer:
                self.time_update_timer.stop()
            if hasattr(self, 'time_prediction_label'):
                self.time_prediction_label.setVisible(False)
                self.predicted_total_time_str = None

            # 标记进度完成/停止，避免 UI 悬挂
            if hasattr(self, "progress_manager") and self.progress_manager:
                if success:
                    self.progress_manager.finish_processing()
                else:
                    self.progress_manager.stop_processing()
                
            if self.progress_worker:
                self.progress_worker.stop()
                self.progress_worker.wait(3000)  # 等待最多3秒
                self.progress_worker = None
                
            self.status_label.setVisible(True)  # 显示简单状态标签
            self.status_label.setText("就绪")
            
            log_info("进度显示系统已停止")
            
        except Exception as e:
            log_error(f"停止进度显示失败: {e}")

    def update_smart_stage_progress(self, stage: str, progress: float, processed_items: int = None):
        """简化的阶段进度更新"""
        pass  # 移除智能预测逻辑

    def finish_smart_stage(self, stage: str):
        """简化的阶段完成"""
        log_info(f"✅ 完成阶段: {stage}")

    def stop_processing(self, success: bool = True):
        """停止处理"""
        try:
            # 🆕 结束智能预测会话
            if hasattr(self, 'smart_predictor') and self.smart_predictor:
                if hasattr(self.smart_predictor, 'end_session'):
                    self.smart_predictor.end_session(success=True)
                    log_info("📊 智能预测会话已结束并记录到历史数据")
            
            # 停止进度显示系统
            self.stop_processing_progress(success=success)
            
            logging.info("✅ 处理已停止")
            
        except Exception as e:
            logging.error(f"❌ 停止处理时出错: {e}")
            
    def show_error_message(self, title: str, message: str):
        """显示错误消息"""
        QMessageBox.critical(self, title, message)
        
    def stop_smart_progress(self):
        """停止进度显示"""
        if self.progress_worker:
            self.progress_worker.stop()
            self.progress_worker.wait(3000)
            self.progress_worker = None
        
        # 隐藏所有进度组件 - 使用属性检查避免错误
        if hasattr(self, 'simple_progress') and self.simple_progress:
            self.simple_progress.setVisible(False)
        
        if hasattr(self, 'stage_label'):
            self.stage_label.setVisible(False)
        
        if hasattr(self, 'detailed_progress'):
            self.detailed_progress.setVisible(False)
        
        # 时间预测标签已移除，无需隐藏
        
        self.update_status("处理完成")
        log_info("🛑 进度系统已停止")

    # ============================================================================
    # 传统进度管理方法（兼容性）
    # ============================================================================

    def update_status(self, message):
        """更新状态标签"""
        self.status_label.setText(message)
        QApplication.processEvents()

    def update_progress_percent(self, percent):
        """更新进度条百分比 - 只使用主要进度条"""
        # 使用简洁版进度条
        if hasattr(self, 'simple_progress'):
            self.simple_progress.update_progress(percent)
        # 记录当前进度用于ETA定时刷新
        try:
            self._current_progress_percent = float(percent)
        except Exception:
            self._current_progress_percent = 0.0
        
        # ETA 自动更新已集成在 simple_progress 中
        
        # 兼容性：旧版进度条保持隐藏
        # if not self.progress.isVisible():
        #     self.progress.setVisible(True)
        # self.progress.setValue(percent)

    def update_detailed_progress(self, message):
        """更新详细进度信息 - 统一使用主要进度条"""
        # 预测时间信息现在通过 simple_progress 自动处理
        
        # 使用简洁版进度条显示详细信息
        if hasattr(self, 'simple_progress'):
            # 从消息中提取状态和详细信息
            if ":" in message:
                parts = message.split(":", 1)
                status = parts[0].strip()
                detail = parts[1].strip() if len(parts) > 1 else ""
                self.simple_progress.update_status(status, detail)
            else:
                self.simple_progress.update_status("处理中", message)
        
        # 兼容性：不再更新传统详细进度标签以避免重复
        # if hasattr(self, 'detailed_progress'):
        #     if not self.detailed_progress.isVisible():
        #         self.detailed_progress.setVisible(True)
        #     self.detailed_progress.setText(message)

    def start_progress_display(self, title="处理中..."):
        """开始显示进度 - 使用统一的主要进度条"""
        # 使用简洁版进度条
        if hasattr(self, 'simple_progress'):
            self.simple_progress.start_progress(title)
            self.simple_progress.setVisible(True)
        
        # 兼容性：隐藏旧版组件避免重复 - 无需操作，progress已设为None
        if hasattr(self, 'detailed_progress'):
            self.detailed_progress.setVisible(False)
        
        # self.progress.setValue(0)
        self.update_status(title)

    def start_detailed_progress_display(self, title="处理中...", show_progress=True, show_cancel=True):
        """开始显示详细进度对话框"""
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt
        import time
        
        if hasattr(self, 'detailed_progress_dialog') and self.detailed_progress_dialog:
            self.detailed_progress_dialog.close()
            
        self.detailed_progress_dialog = QProgressDialog(title, "取消" if show_cancel else "", 0, 100, self)
        self.detailed_progress_dialog.setWindowTitle("请稍候")
        self.detailed_progress_dialog.setWindowModality(Qt.WindowModal)
        self.detailed_progress_dialog.setMinimumDuration(0)
        self.detailed_progress_dialog.setValue(0)
        
        if not show_cancel:
            self.detailed_progress_dialog.setCancelButton(None)
            
        if not show_progress:
            self.detailed_progress_dialog.setRange(0, 0)  # 不确定进度模式
            
        # 添加时间估计标签
        self.progress_start_time = time.time()
        self.progress_last_update = time.time()
        
        self.detailed_progress_dialog.show()
        self.update_status(title)
        
        return self.detailed_progress_dialog

    def update_detailed_progress_display(self, message, current=None, total=None, show_eta=True):
        """更新详细进度显示"""
        if not hasattr(self, 'detailed_progress_dialog') or not self.detailed_progress_dialog:
            return
            
        import time
        
        # 更新消息
        full_message = message
        
        # 如果提供了进度信息
        if current is not None and total is not None and total > 0:
            progress_percent = int((current / total) * 100)
            self.detailed_progress_dialog.setValue(progress_percent)
            
            # 计算剩余时间
            if show_eta and current > 0:
                elapsed = time.time() - self.progress_start_time
                estimated_total = (elapsed / current) * total
                remaining = estimated_total - elapsed
                
                if remaining > 60:
                    eta_text = f"剩余约 {int(remaining // 60)} 分 {int(remaining % 60)} 秒"
                elif remaining > 0:
                    eta_text = f"剩余约 {int(remaining)} 秒"
                else:
                    eta_text = "即将完成"
                    
                full_message += f"\n{eta_text} ({current}/{total})"
        
        self.detailed_progress_dialog.setLabelText(full_message)
        self.update_status(message)
        
        # 处理事件以保持界面响应
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()

    def stop_detailed_progress_display(self):
        """停止详细进度显示"""
        if hasattr(self, 'detailed_progress_dialog') and self.detailed_progress_dialog:
            self.detailed_progress_dialog.close()
            self.detailed_progress_dialog = None

    def stop_progress_display(self):
        """停止显示进度 - 隐藏所有进度组件"""
        # 隐藏简洁版进度条
        if hasattr(self, 'simple_progress'):
            self.simple_progress.hide_progress()
        
        # 兼容性：隐藏旧版组件 - progress已设为None，无需操作
        if hasattr(self, 'detailed_progress'):
            self.detailed_progress.setVisible(False)
        
        # 时间预测标签已移除，无需隐藏

    # ============================================================================
    # 断点续传相关方法
    # ============================================================================

    def check_checkpoint_status(self):
        """检查检查点状态并显示信息"""
        if not self.checkpoint_manager or not self.checkpoint_manager.has_checkpoint():
            return None
        
        checkpoint_info = self.checkpoint_manager.get_checkpoint_info()
        if not checkpoint_info:
            return None
        
        return checkpoint_info

    def show_checkpoint_dialog(self, checkpoint_info):
        """显示检查点恢复对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("发现未完成的分析任务")
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(350)
        
        from PyQt5.QtWidgets import QTextEdit
        layout = QVBoxLayout(dialog)
        
        # 标题
        title_label = QLabel("🔍 发现未完成的分析任务")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #2E86AB; padding: 15px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 信息显示
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(180)
        info_text.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 5px; padding: 10px;")
        
        progress_percent = checkpoint_info['processed_count']/checkpoint_info['total_count']*100 if checkpoint_info['total_count'] > 0 else 0
        
        info_content = f"""📹 视频文件: {os.path.basename(checkpoint_info['video_path'])}
📊 分析进度: {checkpoint_info['processed_count']}/{checkpoint_info['total_count']} 片段
💾 完成度: {progress_percent:.1f}%
⏰ 上次保存: {checkpoint_info['last_save_time']}

💡 提示: 继续之前的分析可以节省大量时间！
   预计剩余时间: {(checkpoint_info['total_count'] - checkpoint_info['processed_count']) * 3 / 60:.1f} 分钟"""
        
        info_text.setText(info_content)
        layout.addWidget(info_text)
        
        # 选项说明
        option_label = QLabel("请选择要执行的操作:")
        option_label.setStyleSheet("font-weight: bold; margin-top: 15px; margin-bottom: 10px;")
        layout.addWidget(option_label)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        btn_continue = QPushButton("✅ 继续之前的分析")
        btn_continue.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        btn_continue.clicked.connect(lambda: dialog.done(1))
        
        btn_restart = QPushButton("🆕 重新开始分析")
        btn_restart.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: black;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e0a800;
            }
        """)
        btn_restart.clicked.connect(lambda: dialog.done(2))
        
        btn_cancel = QPushButton("❌ 取消")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        btn_cancel.clicked.connect(lambda: dialog.done(0))
        
        button_layout.addWidget(btn_continue)
        button_layout.addWidget(btn_restart)
        button_layout.addWidget(btn_cancel)
        layout.addLayout(button_layout)
        
        return dialog.exec_()

    def clear_checkpoint_files(self):
        """清理检查点文件"""
        if self.checkpoint_manager:
            self.checkpoint_manager.clear_checkpoint()
            log_info("[GUI] 检查点文件已清理")

    # ============================================================================
    # 视频处理相关方法
    # ============================================================================

    def process_selected_video(self):
        """处理选中的视频 - 后台线程版本"""
        if self.local_manager:
            # 获取选中的视频路径
            video_path = self._get_selected_video_path()
            
            # 启动智能进度预测
            self.start_smart_progress(video_path)
            # 在后台线程中处理视频
            self.local_manager.process_selected_video_background()
        else:
            QMessageBox.warning(self, "错误", "本地视频管理器未初始化")

    def _get_selected_video_path(self):
        """获取选中的视频路径"""
        try:
            if self.local_manager and hasattr(self.local_manager, 'list_local'):
                idx = self.local_manager.list_local.currentRow()
                if idx >= 0:
                    video_name = self.local_manager.list_local.item(idx).text()
                    twitch_folder = self.config_manager.get("twitch_download_folder", "./data/twitch")
                    video_path = os.path.join(twitch_folder, video_name)
                    if os.path.exists(video_path):
                        return video_path
        except Exception as e:
            log_error(f"获取选中视频路径失败: {e}")
        return None

    def generate_content_indexes_for_rated_clips(self):
        """为所有已评分但未生成索引的切片生成内容索引（后台线程版本）"""
        from acfv.features.modules.pipeline_backend import generate_content_indexes as backend_generate_content_indexes

        def do_generate_indexes():
            # 直接复用后端实现，支持 runs/latest 与评分权重
            try:
                return backend_generate_content_indexes(self.config_manager)
            except Exception as e:
                log_error(f"[generate_content_indexes_for_rated_clips] 调用后端失败: {e}")
                return f"索引生成失败: {e}"

        # 创建后台线程执行索引生成
        self.index_worker = Worker(do_generate_indexes, parent=self)
        self.index_worker.finished.connect(lambda result: self.update_status(result))
        self.index_worker.error.connect(lambda msg: self.update_status(f"索引生成失败: {msg}"))
        self.index_worker.finished.connect(self.index_worker.deleteLater)
        
        self.update_status("正在生成内容索引...")
        self.index_worker.start()
        
        return self.index_worker  # 返回worker以便主流程等待
