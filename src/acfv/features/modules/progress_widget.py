#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
进度显示UI组件 - 美观且功能完整的进度条
"""

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import logging


class ProgressWidget(QWidget):
    """自定义进度显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress_manager = None
        self.setup_ui()
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        
    def setup_ui(self):
        """设置UI界面"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # 主进度条
        self.main_progress = QProgressBar()
        self.main_progress.setRange(0, 100)
        self.main_progress.setTextVisible(True)
        self.main_progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #3498db;
                border-radius: 10px;
                text-align: center;
                font-weight: bold;
                font-size: 14px;
                background-color: #ecf0f1;
                color: #2c3e50;
                min-height: 30px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:0.5 #5dade2, stop:1 #85c1e9);
                border-radius: 8px;
                margin: 1px;
            }
        """)
        layout.addWidget(self.main_progress)
        
        # 当前阶段信息
        stage_layout = QHBoxLayout()
        
        # 阶段标签
        self.stage_label = QLabel("准备中...")
        self.stage_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #2980b9;
                padding: 5px;
            }
        """)
        stage_layout.addWidget(self.stage_label)
        
        # 剩余时间
        self.eta_label = QLabel("计算中...")
        self.eta_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #7f8c8d;
                padding: 5px;
            }
        """)
        stage_layout.addWidget(self.eta_label)
        
        layout.addLayout(stage_layout)
        
        # 子阶段进度显示
        self.substage_widget = QWidget()
        self.substage_layout = QHBoxLayout(self.substage_widget)
        self.substage_layout.setSpacing(4)
        self.substage_layout.setContentsMargins(0, 5, 0, 5)
        
        layout.addWidget(self.substage_widget)
        
        # 详细信息标签
        self.detail_label = QLabel("等待开始...")
        self.detail_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #95a5a6;
                padding: 2px 5px;
                background-color: #f8f9fa;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.detail_label)
        
        # 初始状态隐藏
        self.setVisible(False)
        
    def set_progress_manager(self, progress_manager):
        """设置进度管理器"""
        self.progress_manager = progress_manager
        
    def start_monitoring(self):
        """开始监控进度"""
        if self.progress_manager:
            self.setVisible(True)
            self.update_timer.start(500)  # 每500ms更新一次
            
    def stop_monitoring(self):
        """停止监控进度"""
        try:
            if hasattr(self, 'update_timer') and self.update_timer:
                if self.update_timer.isActive():
                    self.update_timer.stop()
                # 🆕 正确清理定时器
                self.update_timer.deleteLater()
                self.update_timer = None
            
            self.setVisible(False)
            
        except Exception as e:
            import logging
            logging.debug(f"停止进度监控时忽略错误: {e}")
    
    def cleanup(self):
        """清理资源"""
        try:
            self.stop_monitoring()
            # 确保定时器被清理
            if hasattr(self, 'update_timer') and self.update_timer:
                self.update_timer.deleteLater()
                self.update_timer = None
        except Exception as e:
            import logging
            logging.debug(f"清理ProgressWidget时忽略错误: {e}")
        
    def update_display(self):
        """更新显示内容"""
        if not self.progress_manager:
            return
            
        try:
            # 获取总体进度
            total_progress, status_text, eta = self.progress_manager.get_overall_progress()
            
            # 更新主进度条
            progress_percent = int(total_progress * 100)
            self.main_progress.setValue(progress_percent)
            self.main_progress.setFormat(f"{progress_percent}% - {status_text}")
            
            # 更新阶段标签
            self.stage_label.setText(f"🎯 {status_text}")
            
            # 更新剩余时间
            self.eta_label.setText(f"⏱️ 剩余: {eta}")
            
            # 获取详细阶段信息
            stage_details = self.progress_manager.get_stage_details()
            self.update_substage_display(stage_details)
            
            # 更新详细信息
            substage_name = stage_details.get("substage_name", "")
            if substage_name:
                self.detail_label.setText(f"📋 正在执行: {substage_name}")
            else:
                self.detail_label.setText("📋 准备中...")
                
        except Exception as e:
            logging.error(f"更新进度显示失败: {e}")
            
    def update_substage_display(self, stage_details):
        """更新子阶段显示"""
        # 清空现有的子阶段显示
        for i in reversed(range(self.substage_layout.count())):
            child = self.substage_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        substages = stage_details.get("substages", [])
        current_substage_index = stage_details.get("current_substage_index", 0)
        
        # 创建子阶段指示器
        for i, substage_name in enumerate(substages):
            indicator = self.create_substage_indicator(
                substage_name, 
                i < current_substage_index,  # 已完成
                i == current_substage_index  # 当前
            )
            self.substage_layout.addWidget(indicator)
            
    def create_substage_indicator(self, name: str, completed: bool, current: bool):
        """创建子阶段指示器"""
        widget = QWidget()
        widget.setFixedSize(80, 25)
        
        if completed:
            # 已完成 - 绿色
            style = """
                QWidget {
                    background-color: #27ae60;
                    border-radius: 12px;
                    border: 2px solid #229954;
                }
            """
            icon = "✓"
            text_color = "white"
        elif current:
            # 当前进行 - 蓝色
            style = """
                QWidget {
                    background-color: #3498db;
                    border-radius: 12px;
                    border: 2px solid #2980b9;
                }
            """
            icon = "⚡"
            text_color = "white"
        else:
            # 等待中 - 灰色
            style = """
                QWidget {
                    background-color: #bdc3c7;
                    border-radius: 12px;
                    border: 2px solid #95a5a6;
                }
            """
            icon = "○"
            text_color = "#7f8c8d"
        
        widget.setStyleSheet(style)
        
        # 添加文本标签
        label = QLabel(f"{icon}", widget)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-weight: bold;
                font-size: 12px;
                background: transparent;
                border: none;
            }}
        """)
        label.setGeometry(0, 0, 80, 25)
        
        # 设置工具提示
        widget.setToolTip(name)
        
        return widget


class ProgressUpdateWorker(QThread):
    """进度更新工作线程"""
    
    progress_updated = pyqtSignal(str, int, float)  # stage_name, substage_index, progress
    stage_finished = pyqtSignal(str)  # stage_name
    
    def __init__(self, progress_manager):
        super().__init__()
        self.progress_manager = progress_manager
        self.should_stop = False
        
    def update_progress(self, stage_name: str, substage_index: int, progress: float = 0.0):
        """外部调用更新进度"""
        self.progress_updated.emit(stage_name, substage_index, progress)
        
    def finish_stage(self, stage_name: str):
        """外部调用完成阶段"""
        self.stage_finished.emit(stage_name)
        
    def stop(self):
        """停止线程"""
        self.should_stop = True
        # 🆕 等待线程完成
        if self.isRunning():
            self.quit()
            if not self.wait(2000):  # 等待2秒
                self.terminate()
                self.wait(1000)  # 再等1秒
        
    def run(self):
        """线程主循环 - 这里可以监听外部进度更新"""
        while not self.should_stop:
            self.msleep(100)  # 避免过度占用CPU
