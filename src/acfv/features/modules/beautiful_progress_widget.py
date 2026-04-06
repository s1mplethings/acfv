#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
美化版进度显示组件 - 支持多种样式切换
"""

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import logging
from acfv.config.progress_styles import *


class BeautifulProgressWidget(QWidget):
    """美化版进度显示组件"""
    
    def __init__(self, parent=None, style_theme="modern"):
        super().__init__(parent)
        self.progress_manager = None
        self.current_theme = style_theme
        self.animation_group = QParallelAnimationGroup()
        self.setup_ui()
        self.apply_theme()
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        
    def setup_ui(self):
        """设置UI界面"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(12)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        
        # 样式切换器（调试用）
        self.create_style_selector()
        
        # 主进度条容器
        self.progress_container = QFrame()
        self.progress_container.setFrameStyle(QFrame.NoFrame)
        progress_layout = QVBoxLayout(self.progress_container)
        progress_layout.setSpacing(8)
        
        # 主进度条
        self.main_progress = QProgressBar()
        self.main_progress.setRange(0, 100)
        self.main_progress.setTextVisible(True)
        self.main_progress.setFixedHeight(35)
        progress_layout.addWidget(self.main_progress)
        
        # 进度动画效果
        self.progress_effect = QGraphicsOpacityEffect()
        self.main_progress.setGraphicsEffect(self.progress_effect)
        
        self.main_layout.addWidget(self.progress_container)
        
        # 当前阶段信息容器
        self.stage_container = QFrame()
        stage_layout = QHBoxLayout(self.stage_container)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        
        # 阶段标签
        self.stage_label = QLabel("🚀 准备中...")
        self.stage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        stage_layout.addWidget(self.stage_label, 2)
        
        # 剩余时间标签
        self.eta_label = QLabel("⏱️ 计算中...")
        self.eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        stage_layout.addWidget(self.eta_label, 1)
        
        self.main_layout.addWidget(self.stage_container)
        
        # 子阶段进度显示容器
        self.substage_container = QScrollArea()
        self.substage_container.setFixedHeight(60)
        self.substage_container.setWidgetResizable(True)
        self.substage_container.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.substage_container.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.substage_widget = QWidget()
        self.substage_layout = QHBoxLayout(self.substage_widget)
        self.substage_layout.setSpacing(6)
        self.substage_layout.setContentsMargins(5, 5, 5, 5)
        
        self.substage_container.setWidget(self.substage_widget)
        self.main_layout.addWidget(self.substage_container)
        
        # 详细信息标签
        self.detail_label = QLabel("📋 等待开始...")
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.main_layout.addWidget(self.detail_label)
        
        # 统计信息
        self.stats_label = QLabel("")
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.stats_label)
        
        # 初始状态隐藏
        self.setVisible(False)
        
    def create_style_selector(self):
        """创建样式选择器（开发/调试用）"""
        selector_layout = QHBoxLayout()
        
        # 样式选择下拉框
        self.style_combo = QComboBox()
        self.style_combo.addItems([
            "现代渐变", "苹果风格", "霓虹发光", 
            "Fluent设计", "游戏风格", "简约黑白", "彩虹渐变"
        ])
        self.style_combo.currentTextChanged.connect(self.on_style_changed)
        
        selector_layout.addWidget(QLabel("🎨 样式:"))
        selector_layout.addWidget(self.style_combo)
        selector_layout.addStretch()
        
        # 添加一些控制按钮
        self.animation_btn = QPushButton("✨ 动画效果")
        self.animation_btn.setCheckable(True)
        self.animation_btn.setChecked(True)
        self.animation_btn.clicked.connect(self.toggle_animations)
        selector_layout.addWidget(self.animation_btn)
        
        self.main_layout.addLayout(selector_layout)
        
    def on_style_changed(self, style_name):
        """样式切换"""
        style_map = {
            "现代渐变": "modern",
            "苹果风格": "apple", 
            "霓虹发光": "neon",
            "Fluent设计": "fluent",
            "游戏风格": "gaming",
            "简约黑白": "minimal",
            "彩虹渐变": "rainbow"
        }
        
        new_theme = style_map.get(style_name, "modern")
        if new_theme != self.current_theme:
            self.current_theme = new_theme
            self.apply_theme()
            self.animate_style_change()
    
    def apply_theme(self):
        """应用选定的主题样式"""
        # 进度条样式映射
        style_map = {
            "modern": MODERN_GRADIENT_STYLE,
            "apple": APPLE_STYLE,
            "neon": NEON_GLOW_STYLE,
            "fluent": FLUENT_DESIGN_STYLE,
            "gaming": GAMING_STYLE,
            "minimal": MINIMAL_BW_STYLE,
            "rainbow": RAINBOW_STYLE
        }
        
        # 应用进度条样式
        progress_style = style_map.get(self.current_theme, MODERN_GRADIENT_STYLE)
        self.main_progress.setStyleSheet(progress_style)
        
        # 应用标签样式
        self.stage_label.setStyleSheet(ADVANCED_STYLES["labels"]["stage_label"])
        self.eta_label.setStyleSheet(ADVANCED_STYLES["labels"]["eta_label"])  
        self.detail_label.setStyleSheet(ADVANCED_STYLES["labels"]["detail_label"])
        
        # 应用容器样式
        container_style = self.get_container_style()
        self.progress_container.setStyleSheet(container_style)
        self.substage_container.setStyleSheet("""
            QScrollArea {
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                background-color: #f8fafc;
            }
        """)
        
        # 统计信息样式
        self.stats_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #6b7280;
                background-color: #f9fafb;
                border-radius: 4px;
                padding: 4px 8px;
                margin: 2px 0;
            }
        """)
    
    def get_container_style(self):
        """根据主题返回容器样式"""
        if self.current_theme == "neon":
            return """
                QFrame {
                    background-color: #1a1a2e;
                    border: 1px solid #00d4aa;
                    border-radius: 12px;
                    padding: 8px;
                }
            """
        elif self.current_theme == "gaming":
            return """
                QFrame {
                    background-color: #2c1810;
                    border: 2px solid #8b4513;
                    border-radius: 10px;
                    padding: 8px;
                }
            """
        else:
            return """
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #e2e8f0;
                    border-radius: 8px;
                    padding: 8px;
                }
            """
    
    def animate_style_change(self):
        """样式切换动画"""
        if hasattr(self, 'animation_btn') and self.animation_btn.isChecked():
            # 淡出效果
            self.fade_out_animation = QPropertyAnimation(self.progress_effect, b"opacity")
            self.fade_out_animation.setDuration(200)
            self.fade_out_animation.setStartValue(1.0)
            self.fade_out_animation.setEndValue(0.3)
            
            # 淡入效果
            self.fade_in_animation = QPropertyAnimation(self.progress_effect, b"opacity")
            self.fade_in_animation.setDuration(200)
            self.fade_in_animation.setStartValue(0.3)
            self.fade_in_animation.setEndValue(1.0)
            
            # 链接动画
            self.fade_out_animation.finished.connect(self.fade_in_animation.start)
            self.fade_out_animation.start()
    
    def toggle_animations(self):
        """切换动画效果"""
        enabled = self.animation_btn.isChecked()
        self.animation_btn.setText("✨ 动画效果" if enabled else "🚫 动画关闭")
    
    def set_progress_manager(self, progress_manager):
        """设置进度管理器"""
        self.progress_manager = progress_manager
        
    def start_monitoring(self):
        """开始监控进度"""
        if self.progress_manager:
            self.setVisible(True)
            self.update_timer.start(300)  # 更频繁的更新
            self.animate_show()
            
    def stop_monitoring(self):
        """停止监控进度"""
        try:
            if hasattr(self, 'update_timer') and self.update_timer:
                if self.update_timer.isActive():
                    self.update_timer.stop()
                self.update_timer.deleteLater()
                self.update_timer = None
            
            self.animate_hide()
            
        except Exception as e:
            logging.debug(f"停止进度监控时忽略错误: {e}")
    
    def animate_show(self):
        """显示动画"""
        if hasattr(self, 'animation_btn') and self.animation_btn.isChecked():
            self.show_animation = QPropertyAnimation(self, b"geometry")
            self.show_animation.setDuration(300)
            
            current_geo = self.geometry()
            start_geo = QRect(current_geo.x(), current_geo.y() - 50, current_geo.width(), 0)
            
            self.show_animation.setStartValue(start_geo)
            self.show_animation.setEndValue(current_geo)
            self.show_animation.setEasingCurve(QEasingCurve.OutBounce)
            self.show_animation.start()
    
    def animate_hide(self):
        """隐藏动画"""
        if hasattr(self, 'animation_btn') and self.animation_btn.isChecked():
            def hide_widget():
                self.setVisible(False)
                
            self.hide_animation = QPropertyAnimation(self.progress_effect, b"opacity")
            self.hide_animation.setDuration(200)
            self.hide_animation.setStartValue(1.0)
            self.hide_animation.setEndValue(0.0)
            self.hide_animation.finished.connect(hide_widget)
            self.hide_animation.start()
        else:
            self.setVisible(False)
    
    def update_display(self):
        """更新显示内容"""
        if not self.progress_manager:
            return
            
        try:
            # 获取总体进度
            total_progress, status_text, eta = self.progress_manager.get_overall_progress()
            
            # 更新主进度条（带动画）
            current_value = self.main_progress.value()
            target_value = int(total_progress * 100)
            
            if target_value != current_value:
                self.animate_progress_update(current_value, target_value)
            
            # 更新格式文本
            self.main_progress.setFormat(f"{target_value}% - {status_text}")
            
            # 更新阶段标签
            stage_icon = self.get_stage_icon(status_text)
            self.stage_label.setText(f"{stage_icon} {status_text}")
            
            # 更新时间预测
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
            
            # 更新统计信息
            self.update_stats_display(total_progress, stage_details)
                
        except Exception as e:
            logging.error(f"更新进度显示失败: {e}")
    
    def get_stage_icon(self, stage_name):
        """根据阶段名称返回对应图标"""
        icon_map = {
            "音频提取": "🎵",
            "说话人分离": "👥", 
            "语音转录": "📝",
            "情感分析": "😊",
            "切片生成": "✂️",
            "内容分析": "🔍",
            "数据处理": "⚙️"
        }
        
        for key, icon in icon_map.items():
            if key in stage_name:
                return icon
        return "🚀"
    
    def animate_progress_update(self, start_value, end_value):
        """进度条数值更新动画"""
        if hasattr(self, 'animation_btn') and self.animation_btn.isChecked():
            self.progress_animation = QPropertyAnimation(self.main_progress, b"value")
            self.progress_animation.setDuration(500)
            self.progress_animation.setStartValue(start_value)
            self.progress_animation.setEndValue(end_value)
            self.progress_animation.setEasingCurve(QEasingCurve.OutCubic)
            self.progress_animation.start()
        else:
            self.main_progress.setValue(end_value)
    
    def update_substage_display(self, stage_details):
        """更新子阶段显示"""
        # 清空现有显示
        for i in reversed(range(self.substage_layout.count())):
            child = self.substage_layout.itemAt(i).widget()
            if child:
                child.setParent(None)
        
        substages = stage_details.get("substages", [])
        current_substage_index = stage_details.get("current_substage_index", 0)
        
        # 创建子阶段指示器
        for i, substage_name in enumerate(substages):
            if i < current_substage_index:
                status = "completed"
            elif i == current_substage_index:
                status = "current"
            else:
                status = "pending"
                
            indicator = self.create_substage_indicator(substage_name, status)
            self.substage_layout.addWidget(indicator)
    
    def create_substage_indicator(self, name: str, status: str):
        """创建子阶段指示器"""
        indicator = QPushButton(name)
        indicator.setFixedSize(80, 35)
        indicator.setCursor(Qt.PointingHandCursor)
        
        # 应用状态样式
        style = SUBSTAGE_INDICATOR_STYLES.get(status, SUBSTAGE_INDICATOR_STYLES["pending"])
        indicator.setStyleSheet(style)
        
        # 添加工具提示
        tooltip_map = {
            "completed": f"✅ {name} - 已完成",
            "current": f"⚡ {name} - 正在处理",
            "pending": f"⏳ {name} - 等待中"
        }
        indicator.setToolTip(tooltip_map.get(status, name))
        
        return indicator
    
    def update_stats_display(self, progress, stage_details):
        """更新统计信息"""
        try:
            completed_stages = sum(1 for i in range(len(stage_details.get("substages", []))) 
                                 if i < stage_details.get("current_substage_index", 0))
            total_stages = len(stage_details.get("substages", []))
            
            if total_stages > 0:
                stage_progress = f"阶段进度: {completed_stages}/{total_stages}"
                overall_progress = f"总进度: {progress*100:.1f}%"
                stage_elapsed = stage_details.get("stage_elapsed_text", "0秒")
                total_elapsed = stage_details.get("total_elapsed_text", "0秒")
                self.stats_label.setText(
                    f"📊 {stage_progress} | {overall_progress} | 阶段用时: {stage_elapsed} | 总用时: {total_elapsed}"
                )
            else:
                self.stats_label.setText("📊 准备统计中...")
                
        except Exception as e:
            self.stats_label.setText("📊 统计信息暂不可用")
            logging.debug(f"统计更新失败: {e}")
    
    def cleanup(self):
        """清理资源"""
        try:
            self.stop_monitoring()
            if hasattr(self, 'animation_group'):
                self.animation_group.clear()
        except Exception as e:
            logging.debug(f"清理进度组件时忽略错误: {e}")


# 🎨 样式预览窗口
class ProgressStylePreview(QDialog):
    """进度条样式预览窗口"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 进度条样式预览")
        self.setFixedSize(600, 800)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 说明标签
        info_label = QLabel("选择你喜欢的进度条样式：")
        info_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(info_label)
        
        # 滚动区域
        scroll = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # 创建所有样式的预览
        styles = [
            ("现代渐变", "modern"),
            ("苹果风格", "apple"), 
            ("霓虹发光", "neon"),
            ("Fluent设计", "fluent"),
            ("游戏风格", "gaming"),
            ("简约黑白", "minimal"),
            ("彩虹渐变", "rainbow")
        ]
        
        for name, theme in styles:
            preview = self.create_style_preview(name, theme)
            scroll_layout.addWidget(preview)
        
        scroll.setWidget(scroll_widget)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        
        # 确定按钮
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn)
    
    def create_style_preview(self, name, theme):
        """创建样式预览组件"""
        container = QFrame()
        container.setFrameStyle(QFrame.Box)
        container.setStyleSheet("margin: 5px; padding: 10px;")
        
        layout = QVBoxLayout(container)
        
        # 样式名称
        title = QLabel(f"🎨 {name}")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        
        # 预览进度条
        preview_bar = QProgressBar()
        preview_bar.setRange(0, 100)
        preview_bar.setValue(65)
        preview_bar.setTextVisible(True)
        
        # 应用样式
        style_map = {
            "modern": MODERN_GRADIENT_STYLE,
            "apple": APPLE_STYLE,
            "neon": NEON_GLOW_STYLE,
            "fluent": FLUENT_DESIGN_STYLE,
            "gaming": GAMING_STYLE,
            "minimal": MINIMAL_BW_STYLE,
            "rainbow": RAINBOW_STYLE
        }
        
        preview_bar.setStyleSheet(style_map.get(theme, MODERN_GRADIENT_STYLE))
        layout.addWidget(preview_bar)
        
        return container


# 🚀 简化版进度条组件
class SimpleBeautifulProgressBar(QWidget):
    """简化版进度条组件，用于主窗口"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress_manager = None
        self.setup_ui()
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(100)  # 每100ms更新一次
        
    def setup_ui(self):
        """设置简化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 主进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(30)
        self.progress_bar.setStyleSheet(MODERN_GRADIENT_STYLE)
        layout.addWidget(self.progress_bar)
        
        # 状态标签
        self.status_label = QLabel("准备中...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #666;
                padding: 5px;
            }
        """)
        layout.addWidget(self.status_label)

        # 耗时标签
        self.timing_label = QLabel("阶段: 0秒 | 总计: 0秒")
        self.timing_label.setAlignment(Qt.AlignCenter)
        self.timing_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #888;
                padding: 2px;
            }
        """)
        layout.addWidget(self.timing_label)
        
        # 默认隐藏，只在有进度时显示
        self.setVisible(False)
        
    def set_progress_manager(self, progress_manager):
        """设置进度管理器"""
        self.progress_manager = progress_manager
        
    def update_display(self):
        """更新进度显示"""
        if not self.progress_manager:
            return
            
        try:
            # 获取当前进度
            # 使用统一的 get_progress_data 接口
            current_progress = self.progress_manager.get_progress_data()
            if not current_progress:
                return

            # 如果没有开始处理（total_start_time 为空），则保持隐藏
            if not current_progress.get('total_start_time'):
                # 只有在之前是可见状态时才重置，避免闪烁
                if self.isVisible():
                    try:
                        self.progress_bar.setValue(0)
                        self.status_label.setText("准备中...")
                    except Exception:
                        pass
                self.setVisible(False)
                return

            self.setVisible(True)
            percentage = current_progress.get('percentage', 0) * 100 if current_progress.get('percentage', 0) <= 1 else current_progress.get('percentage', 0)
            try:
                pct_float = float(percentage)
            except Exception:
                pct_float = 0.0
            self.progress_bar.setValue(int(pct_float))

            # 兼容字段名: current_stage / stage / status
            stage_text = (current_progress.get('current_stage')
                          or current_progress.get('stage')
                          or current_progress.get('status')
                          or '处理中...')
            self.status_label.setText(f"{stage_text} - {pct_float:.1f}%")

            stage_elapsed = current_progress.get("current_stage_elapsed_text", "0秒")
            total_elapsed = current_progress.get("total_elapsed_text", "0秒")
            self.timing_label.setText(f"阶段: {stage_elapsed} | 总计: {total_elapsed}")
            
        except Exception as e:
            logging.debug(f"更新进度显示时忽略错误: {e}")
            
    def setValue(self, value):
        """设置进度值"""
        self.progress_bar.setValue(value)
        
    def setRange(self, minimum, maximum):
        """设置进度范围"""
        self.progress_bar.setRange(minimum, maximum)
        
    def setStatus(self, text):
        """设置状态文本"""
        self.status_label.setText(text)
        
    def setProgress(self, value, status=None):
        """设置进度和状态"""
        self.setValue(value)
        if status:
            self.setStatus(status)
            
    def show_progress(self, show=True):
        """显示或隐藏进度条"""
        self.setVisible(show)

    def hide_progress(self):
        """隐藏进度条（与主窗口 stop_progress_display 调用保持兼容）"""
        try:
            # 不仅仅隐藏，也可重置显示文本，避免下次残留
            self.setVisible(False)
            if hasattr(self, 'progress_bar'):
                self.progress_bar.setValue(0)
            if hasattr(self, 'status_label'):
                self.status_label.setText("准备中...")
        except Exception as e:
            logging.debug(f"hide_progress 失败: {e}")

    # 兼容可能的 stop_progress 命名
    def stop_progress(self):  # noqa: D401
        """别名：隐藏进度条"""
        self.hide_progress()

    # === 补充与主窗口兼容的 API ===
    def start_progress(self, title: str = "处理中..."):
        """开始一次新的进度显示（与 main_window 兼容）"""
        try:
            self.progress_bar.setValue(0)
            self.status_label.setText(title)
            self.setVisible(True)
        except Exception as e:
            logging.debug(f"start_progress 失败: {e}")

    def update_status(self, status: str, detail: str | None = None):
        """更新状态文本（与 main_window 兼容）
        status: 主状态
        detail: 额外描述
        """
        try:
            if detail:
                self.status_label.setText(f"{status} - {detail}")
            else:
                self.status_label.setText(status)
        except Exception as e:
            logging.debug(f"update_status 失败: {e}")

    def update_progress(self, value: float | int, status: str | None = None, detail: str | None = None):
        """更新进度值以及可选状态（与 main_window 兼容）"""
        try:
            ivalue = int(value) if value is not None else 0
            if ivalue < 0:
                ivalue = 0
            if ivalue > 100:
                ivalue = 100
            self.progress_bar.setValue(ivalue)
            if status:
                self.update_status(status, detail)
        except Exception as e:
            logging.debug(f"update_progress 失败: {e}")


if __name__ == "__main__":
    # 测试代码
    import sys
    app = QApplication(sys.argv)
    
    preview = ProgressStylePreview()
    preview.show()
    
    sys.exit(app.exec_())
