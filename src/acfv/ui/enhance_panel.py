"""Enhance panel for clips tab - 成片增强功能配置面板"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class EnhancePanel(QWidget):
    """成片增强功能配置面板"""
    
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        
        # 标题
        title = QLabel("🎬 成片增强")
        title.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2c3e50;
                padding: 5px;
            }
        """)
        layout.addWidget(title)
        
        # 启用/禁用总开关
        self.enable_enhance = QCheckBox("启用自动成片增强")
        self.enable_enhance.setChecked(self.config_manager.get('ENABLE_ENHANCE', False))
        self.enable_enhance.toggled.connect(self._on_enhance_toggled)
        layout.addWidget(self.enable_enhance)
        
        # 功能模块组
        modules_group = QGroupBox("功能模块")
        modules_layout = QVBoxLayout(modules_group)
        
        # ASR字幕
        self.enable_asr = QCheckBox("✓ 自动字幕（ASR）")
        self.enable_asr.setChecked(self.config_manager.get('ENHANCE_ASR', True))
        self.enable_asr.setToolTip("使用WhisperX生成词级时间戳字幕")
        modules_layout.addWidget(self.enable_asr)

        # 语言识别模式
        self.auto_detect_language = QCheckBox("✓ 自动识别语言（否则强制英语）")
        lang_cfg = str(self.config_manager.get('TRANSCRIPTION_LANGUAGE', 'en') or 'en').strip().lower()
        self.auto_detect_language.setChecked(lang_cfg in {"auto", "detect", "default", ""})
        self.auto_detect_language.setToolTip("勾选=自动识别；取消=强制英语识别")
        modules_layout.addWidget(self.auto_detect_language)

        # 字幕特效
        self.enable_subtitle_fx = QCheckBox("✓ 字幕特效（花字/POP）")
        self.enable_subtitle_fx.setChecked(self.config_manager.get('ENHANCE_SUBTITLE_FX', True))
        self.enable_subtitle_fx.setToolTip("关键词自动添加POP/COLOR等特效")
        modules_layout.addWidget(self.enable_subtitle_fx)

        # 主播字幕导出
        self.enable_streamer_subtitles = QCheckBox("✓ 导出主播字幕（work/subtitles_streamer.*）")
        self.enable_streamer_subtitles.setChecked(self.config_manager.get('ENABLE_STREAMER_SUBTITLES', False))
        self.enable_streamer_subtitles.setToolTip("仅导出主播的SRT/ASS字幕文件")
        modules_layout.addWidget(self.enable_streamer_subtitles)
        
        # ROI视角切换
        self.enable_roi = QCheckBox("✓ 视角切换（PC/V区域）")
        self.enable_roi.setChecked(self.config_manager.get('ENHANCE_ROI', False))
        self.enable_roi.setToolTip("识别电脑区域与V区域，自动切换视角")
        modules_layout.addWidget(self.enable_roi)
        
        # 梗贴图
        self.enable_meme = QCheckBox("✓ 梗贴图/音效")
        self.enable_meme.setChecked(self.config_manager.get('ENHANCE_MEME', False))
        self.enable_meme.setToolTip("根据关键词自动添加梗贴图和音效")
        modules_layout.addWidget(self.enable_meme)
        
        # RAG推荐
        self.enable_rag = QCheckBox("✓ 智能推荐（RAG）")
        self.enable_rag.setChecked(self.config_manager.get('ENHANCE_RAG', False))
        self.enable_rag.setToolTip("根据用户偏好推荐梗素材和字幕风格")
        modules_layout.addWidget(self.enable_rag)
        
        layout.addWidget(modules_group)
        
        # 字幕风格选择
        style_group = QGroupBox("字幕风格")
        style_layout = QVBoxLayout(style_group)
        
        self.style_combo = QComboBox()
        self.style_combo.addItems(["简洁 (clean)", "粗体 (bold_outline)", "梗式 (meme_heavy)"])
        current_style = self.config_manager.get('SUBTITLE_STYLE_PROFILE', 'clean')
        style_map = {"clean": 0, "bold_outline": 1, "meme_heavy": 2}
        self.style_combo.setCurrentIndex(style_map.get(current_style, 0))
        style_layout.addWidget(self.style_combo)
        
        layout.addWidget(style_group)
        
        # 梗密度控制
        density_group = QGroupBox("梗密度")
        density_layout = QVBoxLayout(density_group)
        
        density_row = QHBoxLayout()
        density_row.addWidget(QLabel("稀疏"))
        
        self.density_slider = QSlider(Qt.Horizontal)
        self.density_slider.setRange(0, 100)
        self.density_slider.setValue(int(self.config_manager.get('MEME_DENSITY', 0.3) * 100))
        self.density_slider.setTickPosition(QSlider.TicksBelow)
        self.density_slider.setTickInterval(20)
        self.density_slider.valueChanged.connect(self._on_density_changed)
        density_row.addWidget(self.density_slider, 1)
        
        density_row.addWidget(QLabel("密集"))
        self.density_label = QLabel(f"{self.density_slider.value()}%")
        density_row.addWidget(self.density_label)
        
        density_layout.addLayout(density_row)
        layout.addWidget(density_group)
        
        # 应用按钮
        self.apply_button = QPushButton("应用增强设置")
        self.apply_button.clicked.connect(self._apply_settings)
        self.apply_button.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        layout.addWidget(self.apply_button)
        
        # AI测试按钮
        self.test_ai_button = QPushButton("🧠 测试AI推荐")
        self.test_ai_button.clicked.connect(self._test_ai_recommendation)
        self.test_ai_button.setStyleSheet("""
            QPushButton {
                background-color: #9b59b6;
                color: white;
                padding: 6px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #8e44ad;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        layout.addWidget(self.test_ai_button)
        
        # 说明文字
        info = QLabel("提示：勾选需要的功能后点击「应用」保存")
        info.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        layout.addStretch(1)
        
        # 初始状态
        self._on_enhance_toggled(self.enable_enhance.isChecked())
    
    def _on_enhance_toggled(self, checked):
        """总开关切换"""
        self.enable_asr.setEnabled(checked)
        self.auto_detect_language.setEnabled(checked)
        self.enable_subtitle_fx.setEnabled(checked)
        self.enable_streamer_subtitles.setEnabled(checked)
        self.enable_roi.setEnabled(checked)
        self.enable_meme.setEnabled(checked)
        self.enable_rag.setEnabled(checked)
        self.style_combo.setEnabled(checked)
        self.density_slider.setEnabled(checked)
        self.apply_button.setEnabled(checked)
    
    def _on_density_changed(self, value):
        """密度滑块变化"""
        self.density_label.setText(f"{value}%")
    
    def _apply_settings(self):
        """应用设置到配置"""
        self.config_manager.config['ENABLE_ENHANCE'] = self.enable_enhance.isChecked()
        self.config_manager.config['ENHANCE_ASR'] = self.enable_asr.isChecked()
        self.config_manager.config['TRANSCRIPTION_LANGUAGE'] = (
            "auto" if self.auto_detect_language.isChecked() else "en"
        )
        self.config_manager.config['ENHANCE_SUBTITLE_FX'] = self.enable_subtitle_fx.isChecked()
        self.config_manager.config['ENABLE_STREAMER_SUBTITLES'] = self.enable_streamer_subtitles.isChecked()
        self.config_manager.config['ENHANCE_ROI'] = self.enable_roi.isChecked()
        self.config_manager.config['ENHANCE_MEME'] = self.enable_meme.isChecked()
        self.config_manager.config['ENHANCE_RAG'] = self.enable_rag.isChecked()
        
        # 字幕风格
        style_texts = ["clean", "bold_outline", "meme_heavy"]
        self.config_manager.config['SUBTITLE_STYLE_PROFILE'] = style_texts[self.style_combo.currentIndex()]
        
        # 梗密度
        self.config_manager.config['MEME_DENSITY'] = self.density_slider.value() / 100.0
        
        # 保存配置
        self.config_manager.save_config()
        
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, "成功", "增强设置已保存！\n\n下次生成切片时将自动应用这些设置。")
    
    def _test_ai_recommendation(self):
        """测试AI推荐功能"""
        try:
            from ..enhance.rag import get_ai_recommendation
            
            # 模拟上下文
            context = {
                'video_title': '测试视频',
                'duration': 300,
                'user_preferences': ['梗图', '字幕特效']
            }
            
            recommendation = get_ai_recommendation(context)
            
            if recommendation:
                QMessageBox.information(self, "AI推荐结果", f"AI生成推荐：\n\n{recommendation}")
            else:
                QMessageBox.warning(self, "AI推荐失败", "AI功能未就绪或生成失败。\n请检查AI库是否正确安装。")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"AI测试失败：{str(e)}")
    
    def get_enhance_config(self):
        """获取当前增强配置（供pipeline调用）"""
        if not self.enable_enhance.isChecked():
            return None
        
        return {
            'enable_asr': self.enable_asr.isChecked(),
            'enable_subtitle_fx': self.enable_subtitle_fx.isChecked(),
            'enable_streamer_subtitles': self.enable_streamer_subtitles.isChecked(),
            'enable_roi': self.enable_roi.isChecked(),
            'enable_meme': self.enable_meme.isChecked(),
            'enable_rag': self.enable_rag.isChecked(),
            'subtitle_style': ["clean", "bold_outline", "meme_heavy"][self.style_combo.currentIndex()],
            'meme_density': self.density_slider.value() / 100.0,
        }
