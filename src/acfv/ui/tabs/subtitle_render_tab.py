"""Subtitle preview/render tab."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from acfv.features.modules.ui_components import Worker
from acfv.processing.subtitle_render import apply_style_preset, burn_in, make_preview_ass, render_preview
from acfv.runtime.storage import processing_path, resolve_clips_base_dir, runs_out_path
from acfv.ui import build_section_header, wrap_in_card
from acfv.ui.enhance_panel import EnhancePanel

from .base import TabHandle


class SubtitleRenderWidget(QWidget):
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self._worker: Optional[Worker] = None
        self._preview_path: Optional[Path] = None
        self._presets: Dict[str, dict] = {}
        self._player = None
        self._video_widget = None
        self._multimedia_available = False
        self._text_color = None
        self._outline_color = None
        self._build_ui()
        self._load_presets()
        self._guess_defaults()

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        left_widget = QWidget()
        layout = QVBoxLayout(left_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(build_section_header("字幕预览/渲染 + 切片设置", "烧录字幕到视频并管理切片参数"))

        form = QFormLayout()

        self.video_path_edit = QLineEdit()
        video_row = QHBoxLayout()
        video_row.addWidget(self.video_path_edit, 1)
        btn_video = QPushButton("选择")
        btn_video.clicked.connect(self._select_video)
        video_row.addWidget(btn_video)
        btn_clip = QPushButton("选切片")
        btn_clip.clicked.connect(self._select_clip)
        video_row.addWidget(btn_clip)
        video_widget = QWidget()
        video_widget.setLayout(video_row)
        form.addRow("视频文件:", video_widget)

        self.sub_path_edit = QLineEdit()
        sub_row = QHBoxLayout()
        sub_row.addWidget(self.sub_path_edit, 1)
        btn_sub = QPushButton("选择")
        btn_sub.clicked.connect(self._select_subtitle)
        sub_row.addWidget(btn_sub)
        sub_widget = QWidget()
        sub_widget.setLayout(sub_row)
        form.addRow("字幕文件:", sub_widget)

        self.style_combo = QComboBox()
        form.addRow("样式预设:", self.style_combo)

        self.font_combo = QFontComboBox()
        form.addRow("字体:", self.font_combo)

        color_row = QHBoxLayout()
        self.text_color_btn = QPushButton("文字颜色")
        self.text_color_btn.clicked.connect(self._pick_text_color)
        self.outline_color_btn = QPushButton("描边颜色")
        self.outline_color_btn.clicked.connect(self._pick_outline_color)
        color_row.addWidget(self.text_color_btn)
        color_row.addWidget(self.outline_color_btn)
        color_widget = QWidget()
        color_widget.setLayout(color_row)
        form.addRow("颜色:", color_widget)

        self.preview_start = QDoubleSpinBox()
        self.preview_start.setRange(0, 24 * 3600)
        self.preview_start.setDecimals(1)
        self.preview_start.setValue(0.0)
        form.addRow("预览起始(秒):", self.preview_start)

        self.preview_duration = QDoubleSpinBox()
        self.preview_duration.setRange(3, 60)
        self.preview_duration.setDecimals(1)
        self.preview_duration.setValue(10.0)
        form.addRow("预览时长(秒):", self.preview_duration)

        form_widget = QWidget()
        form_widget.setLayout(form)
        layout.addWidget(wrap_in_card(form_widget))

        editor_card = QWidget()
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(6)
        editor_header = QLabel("字幕编辑器（简单版）")
        editor_header.setStyleSheet("font-weight: bold;")
        editor_layout.addWidget(editor_header)
        self.subtitle_editor = QTextEdit()
        self.subtitle_editor.setPlaceholderText("在这里直接修改字幕内容（SRT/ASS）。")
        editor_layout.addWidget(self.subtitle_editor, 1)
        editor_btns = QHBoxLayout()
        btn_load_subs = QPushButton("加载当前字幕")
        btn_load_subs.clicked.connect(self._load_subtitle_into_editor)
        btn_save_subs = QPushButton("保存编辑内容")
        btn_save_subs.clicked.connect(self._save_editor_to_subtitle)
        btn_save_as = QPushButton("另存为")
        btn_save_as.clicked.connect(self._save_editor_as_subtitle)
        editor_btns.addWidget(btn_load_subs)
        editor_btns.addWidget(btn_save_subs)
        editor_btns.addWidget(btn_save_as)
        editor_btns.addStretch(1)
        editor_layout.addLayout(editor_btns)
        layout.addWidget(wrap_in_card(editor_card))

        clip_card = QWidget()
        clip_layout = QFormLayout(clip_card)
        clip_layout.setLabelAlignment(Qt.AlignLeft)

        self.edit_max_clips = QLineEdit(str(self.config_manager.get("MAX_CLIP_COUNT", 10)))
        clip_layout.addRow("最大切片个数:", self.edit_max_clips)

        self.edit_candidate_multiplier = QLineEdit(
            str(self.config_manager.get("LLM_HIGHLIGHT_CANDIDATE_MULTIPLIER", 5))
        )
        self.edit_candidate_multiplier.setToolTip("粗召回先放大几倍候选池，再交给本地 Ollama/API 精排。")
        clip_layout.addRow("候选放大倍数:", self.edit_candidate_multiplier)

        self.edit_clips_base_dir = QLineEdit(self.config_manager.get("CLIPS_BASE_DIR", "clips"))
        clips_dir_row = QWidget()
        clips_dir_layout = QHBoxLayout(clips_dir_row)
        clips_dir_layout.setContentsMargins(0, 0, 0, 0)
        clips_dir_layout.addWidget(self.edit_clips_base_dir, 1)
        btn_choose_dir = QPushButton("选择")
        btn_choose_dir.clicked.connect(self._choose_clips_dir)
        clips_dir_layout.addWidget(btn_choose_dir)
        clip_layout.addRow("切片基础目录:", clips_dir_row)

        self.edit_min_clip_duration = QLineEdit(str(self.config_manager.get("MIN_CLIP_DURATION", 60.0)))
        clip_layout.addRow("最小切片时长(秒):", self.edit_min_clip_duration)

        self.edit_clip_context_extend = QLineEdit(str(self.config_manager.get("CLIP_CONTEXT_EXTEND", 15.0)))
        clip_layout.addRow("前后文扩展时长(秒):", self.edit_clip_context_extend)

        self.edit_clip_merge_threshold = QLineEdit(str(self.config_manager.get("CLIP_MERGE_THRESHOLD", 10.0)))
        clip_layout.addRow("切片合并阈值(秒):", self.edit_clip_merge_threshold)

        self.checkbox_merge_nearby_clips = QCheckBox()
        self.checkbox_merge_nearby_clips.setChecked(self.config_manager.get("MERGE_NEARBY_CLIPS", True))
        clip_layout.addRow("合并相邻切片:", self.checkbox_merge_nearby_clips)

        self.checkbox_enable_local_distill = QCheckBox()
        self.checkbox_enable_local_distill.setChecked(self.config_manager.get("ENABLE_LLM_LOCAL_DISTILL", True))
        clip_layout.addRow("启用本地Ollama蒸馏:", self.checkbox_enable_local_distill)

        self.edit_local_llm_model = QLineEdit(self.config_manager.get("LLM_LOCAL_MODEL", "qwen2.5:7b-instruct"))
        self.edit_local_llm_model.setToolTip("本地 Ollama/OpenAI-compatible 模型名。")
        clip_layout.addRow("本地Ollama模型:", self.edit_local_llm_model)

        self.edit_remote_llm_model = QLineEdit(
            self.config_manager.get("LLM_HIGHLIGHT_MODEL", self.config_manager.get("LLM_MODEL", ""))
        )
        self.edit_remote_llm_model.setToolTip("最终高光精排使用的远端 API 文本模型。")
        clip_layout.addRow("远端API模型:", self.edit_remote_llm_model)

        self.edit_remote_vision_model = QLineEdit(
            self.config_manager.get("LLM_VISION_MODEL", self.config_manager.get("SCREEN_UNDERSTANDING_MODEL", ""))
        )
        self.edit_remote_vision_model.setToolTip("电脑画面理解使用的远端视觉模型。")
        clip_layout.addRow("视觉模型:", self.edit_remote_vision_model)

        self.edit_user_preference_prompt = QTextEdit()
        self.edit_user_preference_prompt.setPlaceholderText("例如：优先代码修改、问题定位、软件操作、创作过程。")
        self.edit_user_preference_prompt.setPlainText(
            self.config_manager.get("LLM_HIGHLIGHT_USER_PREFERENCE_PROMPT", "")
        )
        self.edit_user_preference_prompt.setMaximumHeight(96)
        clip_layout.addRow("用户兴趣偏好:", self.edit_user_preference_prompt)

        layout.addWidget(wrap_in_card(clip_card))

        btn_row = QHBoxLayout()
        self.btn_preview = QPushButton("生成预览")
        self.btn_preview.clicked.connect(self._on_generate_preview)
        btn_row.addWidget(self.btn_preview)

        self.btn_play = QPushButton("播放预览")
        self.btn_play.clicked.connect(self._on_play_preview)
        btn_row.addWidget(self.btn_play)

        self.btn_render = QPushButton("渲染全片")
        self.btn_render.clicked.connect(self._on_render_full)
        btn_row.addWidget(self.btn_render)

        self.btn_save_clips = QPushButton("保存切片设置")
        self.btn_save_clips.clicked.connect(self._save_clip_settings)
        btn_row.addWidget(self.btn_save_clips)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #555;")
        layout.addWidget(self.status_label)

        self._init_player(layout)
        layout.addStretch(1)

        main_layout.addWidget(left_widget, 3)

        self.enhance_panel = EnhancePanel(self.config_manager)
        self.enhance_panel.setMaximumWidth(300)
        self.enhance_panel.setStyleSheet("""
            QWidget {
                background-color: #f8f9fa;
                border-radius: 6px;
            }
        """)
        main_layout.addWidget(self.enhance_panel, 1)

    def _presets_path(self) -> Path:
        root = Path(__file__).resolve().parents[4]
        return root / "assets" / "subtitle_styles" / "presets.json"

    def _init_player(self, layout: QVBoxLayout) -> None:
        try:
            from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
            from PyQt5.QtMultimediaWidgets import QVideoWidget
        except Exception:
            return
        self._video_widget = QVideoWidget()
        self._player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self._player.setVideoOutput(self._video_widget)
        self._multimedia_available = True
        layout.addWidget(self._video_widget, 1)

    def _load_presets(self) -> None:
        path = self._presets_path()
        if path.exists():
            import json

            self._presets = json.loads(path.read_text(encoding="utf-8"))
        else:
            self._presets = {}
        keys = list(self._presets.keys()) or ["clean", "bold", "anime_pop", "minimal", "top_caption"]
        self.style_combo.clear()
        self.style_combo.addItems(keys)

    def _guess_defaults(self) -> None:
        if not self.sub_path_edit.text().strip():
            subtitle = self._find_latest_subtitle()
            if subtitle:
                self.sub_path_edit.setText(str(subtitle))

    def _find_latest_subtitle(self) -> Optional[Path]:
        base = resolve_clips_base_dir(self.config_manager, ensure=False)
        latest = None
        latest_mtime = 0.0
        for path in base.glob("**/runs/run_*/work/subtitles_streamer.ass"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest = path
                latest_mtime = mtime
        if latest:
            return latest
        for path in base.glob("**/runs/run_*/work/subtitles_streamer.srt"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest = path
                latest_mtime = mtime
        return latest

    def _select_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", "Video Files (*.mp4 *.mkv *.mov *.avi)")
        if path:
            self.video_path_edit.setText(path)

    def _select_clip(self) -> None:
        base_dir = resolve_clips_base_dir(self.config_manager, ensure=False)
        start_dir = str(base_dir) if base_dir else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择切片",
            start_dir,
            "Clip Files (*.mp4 *.mkv *.mov *.avi *.webm)",
        )
        if not path:
            return
        self.video_path_edit.setText(path)
        if self.sub_path_edit.text().strip():
            return
        work_dir = self._infer_work_dir(Path(path), Path(path))
        candidate_ass = work_dir / "subtitles_streamer.ass"
        candidate_srt = work_dir / "subtitles_streamer.srt"
        if candidate_ass.exists():
            self.sub_path_edit.setText(str(candidate_ass))
        elif candidate_srt.exists():
            self.sub_path_edit.setText(str(candidate_srt))

    def _select_subtitle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择字幕", "", "Subtitle Files (*.ass *.srt)")
        if path:
            self.sub_path_edit.setText(path)

    def _choose_clips_dir(self) -> None:
        current = self.edit_clips_base_dir.text().strip() or "."
        directory = QFileDialog.getExistingDirectory(self, "选择切片基础目录", current)
        if directory:
            self.edit_clips_base_dir.setText(directory)

    def _infer_work_dir(self, video_path: Path, subtitle_path: Path) -> Path:
        for candidate in (subtitle_path, video_path):
            if candidate.name == "work" and candidate.is_dir():
                return candidate
            for parent in candidate.parents:
                if parent.name == "work":
                    return parent
                if parent.parent and parent.parent.name == "runs" and parent.name.startswith("run_"):
                    return parent / "work"
        return processing_path("working")

    def _prepare_paths(self) -> Optional[dict]:
        video_path = Path(self.video_path_edit.text().strip())
        subtitle_path = Path(self.sub_path_edit.text().strip())
        if not video_path.exists():
            self.status_label.setText("视频路径不存在")
            return None
        if not subtitle_path.exists():
            self.status_label.setText("字幕路径不存在")
            return None
        style = self.style_combo.currentText().strip() or "clean"
        work_dir = self._infer_work_dir(video_path, subtitle_path)
        work_dir.mkdir(parents=True, exist_ok=True)
        styled_ass = work_dir / f"subtitles_streamer__{style}.ass"
        preview_ass = work_dir / "tmp_preview.ass"
        preview_mp4 = work_dir / f"preview_subtitle_{style}.mp4"
        out_mp4 = runs_out_path(f"{video_path.stem}__sub_{style}.mp4")
        return {
            "video": video_path,
            "subtitle": subtitle_path,
            "style": style,
            "styled_ass": styled_ass,
            "preview_ass": preview_ass,
            "preview_mp4": preview_mp4,
            "out_mp4": Path(out_mp4),
            "work_dir": work_dir,
        }

    def _on_generate_preview(self) -> None:
        payload = self._prepare_paths()
        if not payload:
            return
        self._run_worker(self._generate_preview_task, payload)

    def _on_render_full(self) -> None:
        payload = self._prepare_paths()
        if not payload:
            return
        self._run_worker(self._render_full_task, payload)

    def _run_worker(self, func, payload) -> None:
        if self._worker and self._worker.isRunning():
            self.status_label.setText("正在处理中，请稍后")
            return
        self.status_label.setText("处理中...")
        self._worker = Worker(func, payload)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _generate_preview_task(self, payload: dict) -> str:
        styled = apply_style_preset(
            payload["subtitle"],
            payload["style"],
            payload["styled_ass"],
            self._presets_path(),
            overrides=self._style_overrides(),
        )
        preview_ass = make_preview_ass(
            styled,
            float(self.preview_start.value()),
            float(self.preview_duration.value()),
            payload["preview_ass"],
        )
        preview_mp4 = render_preview(
            payload["video"],
            float(self.preview_start.value()),
            float(self.preview_duration.value()),
            preview_ass,
            payload["preview_mp4"],
        )
        self._preview_path = Path(preview_mp4)
        return f"预览已生成: {preview_mp4}"

    def _render_full_task(self, payload: dict) -> str:
        styled = apply_style_preset(
            payload["subtitle"],
            payload["style"],
            payload["styled_ass"],
            self._presets_path(),
            overrides=self._style_overrides(),
        )
        out_mp4 = burn_in(payload["video"], styled, payload["out_mp4"])
        return f"全片已渲染: {out_mp4}"

    def _on_worker_finished(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_worker_error(self, message: str) -> None:
        self.status_label.setText(f"失败: {message}")

    def _on_play_preview(self) -> None:
        if not self._preview_path or not self._preview_path.exists():
            self.status_label.setText("请先生成预览")
            return
        if self._multimedia_available and self._player:
            from PyQt5.QtMultimedia import QMediaContent

            url = QUrl.fromLocalFile(str(self._preview_path))
            self._player.setMedia(QMediaContent(url))
            self._player.play()
            return
        try:
            if os.name == "nt":
                os.startfile(str(self._preview_path))
            elif os.name == "posix":
                import subprocess

                subprocess.run(["xdg-open", str(self._preview_path)], check=False)
            else:
                self.status_label.setText("无法打开预览")
        except Exception as exc:
            self.status_label.setText(f"播放失败: {exc}")

    def _save_clip_settings(self) -> None:
        self.config_manager.set("MAX_CLIP_COUNT", int(self.edit_max_clips.text().strip() or 0))
        self.config_manager.set(
            "LLM_HIGHLIGHT_CANDIDATE_MULTIPLIER",
            int(self.edit_candidate_multiplier.text().strip() or 5),
        )
        self.config_manager.set("CLIPS_BASE_DIR", self.edit_clips_base_dir.text().strip())
        self.config_manager.set("MIN_CLIP_DURATION", float(self.edit_min_clip_duration.text().strip() or 60.0))
        self.config_manager.set("CLIP_CONTEXT_EXTEND", float(self.edit_clip_context_extend.text().strip() or 15.0))
        self.config_manager.set("CLIP_MERGE_THRESHOLD", float(self.edit_clip_merge_threshold.text().strip() or 10.0))
        self.config_manager.set("MERGE_NEARBY_CLIPS", self.checkbox_merge_nearby_clips.isChecked())
        self.config_manager.set("ENABLE_LLM_LOCAL_DISTILL", self.checkbox_enable_local_distill.isChecked())
        self.config_manager.set("LLM_LOCAL_MODEL", self.edit_local_llm_model.text().strip())
        self.config_manager.set("LLM_HIGHLIGHT_MODEL", self.edit_remote_llm_model.text().strip())
        self.config_manager.set("LLM_VISION_MODEL", self.edit_remote_vision_model.text().strip())
        self.config_manager.set(
            "LLM_HIGHLIGHT_USER_PREFERENCE_PROMPT",
            self.edit_user_preference_prompt.toPlainText().strip(),
        )
        self.config_manager.save_config()
        self.status_label.setText("切片设置已保存")

    def _style_overrides(self) -> dict:
        overrides = {}
        font = self.font_combo.currentFont().family()
        if font:
            overrides["fontname"] = font
        if self._text_color is not None:
            overrides["primarycolor"] = (
                self._text_color.red(),
                self._text_color.green(),
                self._text_color.blue(),
            )
        if self._outline_color is not None:
            overrides["outlinecolor"] = (
                self._outline_color.red(),
                self._outline_color.green(),
                self._outline_color.blue(),
            )
        return overrides

    def _pick_text_color(self) -> None:
        color = QColorDialog.getColor(parent=self, title="选择文字颜色")
        if color.isValid():
            self._text_color = color
            self.text_color_btn.setStyleSheet(f"background-color: {color.name()}; color: #fff;")

    def _pick_outline_color(self) -> None:
        color = QColorDialog.getColor(parent=self, title="选择描边颜色")
        if color.isValid():
            self._outline_color = color
            self.outline_color_btn.setStyleSheet(f"background-color: {color.name()}; color: #fff;")

    def _load_subtitle_into_editor(self) -> None:
        path = self.sub_path_edit.text().strip()
        if not path:
            self.status_label.setText("请先选择字幕文件")
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception:
            try:
                text = Path(path).read_text(encoding="utf-16")
            except Exception as exc:
                self.status_label.setText(f"读取失败: {exc}")
                return
        self.subtitle_editor.setPlainText(text)
        self.status_label.setText("字幕已加载到编辑器")

    def _save_editor_to_subtitle(self) -> None:
        path = self.sub_path_edit.text().strip()
        if not path:
            self.status_label.setText("请先选择字幕文件")
            return
        try:
            Path(path).write_text(self.subtitle_editor.toPlainText(), encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(f"保存失败: {exc}")
            return
        self.status_label.setText("字幕已保存")

    def _save_editor_as_subtitle(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "另存为字幕",
            "",
            "Subtitle Files (*.ass *.srt)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.subtitle_editor.toPlainText(), encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(f"保存失败: {exc}")
            return
        self.sub_path_edit.setText(path)
        self.status_label.setText("字幕已另存为")


def create_subtitle_render_tab(main_window, config_manager) -> TabHandle:
    widget = SubtitleRenderWidget(config_manager)
    return TabHandle(title="字幕预览/渲染", widget=widget, controller=widget)
