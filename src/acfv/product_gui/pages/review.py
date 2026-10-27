from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..components import EmptyState, ErrorState, PageHeader, StatusBadge, button, label
from ..controllers import ProductContext, ReviewController
from ..models import ClipModel, OBJECT_ROLE
from ..player import MediaPlayer
from ..viewmodels import VariantVM, duration_text


PROFILE_LABELS = {
    "SHORT": "短版",
    "STANDARD": "标准版",
    "LONG": "长版",
    "FULL_EVENT": "完整事件",
}


class ReviewPage(QWidget):
    def __init__(self, controller: ReviewController, context: ProductContext, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller; self.context = context
        self.workflow = None
        self.current_clip_id = ""
        self.current_profile = "STANDARD"
        self._variants: dict[str, VariantVM] = {}
        self._loading_cues = False
        self._dirty = False
        self._pending_render = False
        self.save_timer = QTimer(self); self.save_timer.setSingleShot(True); self.save_timer.setInterval(900)
        self.save_timer.timeout.connect(self.save_cues)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 20, 24, 16)
        layout.addWidget(PageHeader("Clip Review", "比较时长版本、检查双语字幕和风险，再接受、拒绝或导出。"))
        self.error = ErrorState(); self.error.setVisible(False); self.error.retry.connect(self._retry)
        layout.addWidget(self.error)
        split = QSplitter(Qt.Horizontal)
        left = QWidget(); left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.addWidget(label("待 Review", role="sectionTitle"))
        self.clip_model = ClipModel()
        self.clips = QListView(); self.clips.setObjectName("ClipList"); self.clips.setModel(self.clip_model); self.clips.setUniformItemSizes(True)
        self.clips.clicked.connect(self._clip_selected)
        left_layout.addWidget(self.clips, 1)
        self.empty = EmptyState("没有 Clip", "从搜索结果或 Evidence 创建 Clip 后会出现在这里。")
        self.empty.setVisible(False); left_layout.addWidget(self.empty)
        split.addWidget(left)
        self.editor = QWidget(); editor_layout = QVBoxLayout(self.editor); editor_layout.setContentsMargins(8, 0, 0, 0)
        self.title = label("选择一个 Clip", role="sectionTitle")
        self.status = StatusBadge("等待选择")
        title_row = QHBoxLayout(); title_row.addWidget(self.title, 1); title_row.addWidget(self.status)
        editor_layout.addLayout(title_row)
        self.player = MediaPlayer(); editor_layout.addWidget(self.player, 3)
        editor_layout.addWidget(label("时长版本", role="sectionTitle"))
        variant_row = QHBoxLayout(); self.variant_buttons: dict[str, QPushButton] = {}
        for profile in PROFILE_LABELS:
            action = QPushButton(PROFILE_LABELS[profile]); action.clicked.connect(lambda _checked=False, name=profile: self._variant_clicked(name))
            self.variant_buttons[profile] = action; variant_row.addWidget(action)
        editor_layout.addLayout(variant_row)
        boundary_row = QHBoxLayout()
        boundary_row.addWidget(label("入点", muted=True)); self.start = QDoubleSpinBox(); self.start.setRange(0, 999999); self.start.setDecimals(3); self.start.setSuffix(" s")
        boundary_row.addWidget(self.start)
        boundary_row.addWidget(label("出点", muted=True)); self.end = QDoubleSpinBox(); self.end.setRange(0, 999999); self.end.setDecimals(3); self.end.setSuffix(" s")
        boundary_row.addWidget(self.end); boundary_row.addStretch(1)
        boundary_row.addWidget(button("-0.5s", lambda: self.start.setValue(max(0, self.start.value() - .5))))
        boundary_row.addWidget(button("+0.5s", lambda: self.end.setValue(self.end.value() + .5)))
        editor_layout.addLayout(boundary_row)
        lower = QSplitter(Qt.Horizontal)
        subtitle = QWidget(); subtitle_layout = QVBoxLayout(subtitle); subtitle_layout.setContentsMargins(0, 0, 8, 0)
        subtitle_layout.addWidget(label("双语字幕", role="sectionTitle"))
        self.cues = QTableWidget(0, 5)
        self.cues.setHorizontalHeaderLabels(["时间", "中文", "English", "状态", "Cue"])
        self.cues.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.cues.verticalHeader().setVisible(False)
        self.cues.horizontalHeader().setStretchLastSection(False)
        self.cues.setColumnWidth(0, 112); self.cues.setColumnWidth(1, 260); self.cues.setColumnWidth(2, 260); self.cues.setColumnWidth(3, 104); self.cues.setColumnHidden(4, True)
        self.cues.itemChanged.connect(self._cue_changed)
        self.cues.cellDoubleClicked.connect(self._cue_seek)
        subtitle_layout.addWidget(self.cues, 1)
        subtitle_actions = QHBoxLayout()
        self.save_button = button("保存字幕", self.save_cues); self.save_button.setEnabled(False)
        subtitle_actions.addWidget(self.save_button)
        subtitle_actions.addWidget(button("Render Updated Clip", self.render, primary=True)); subtitle_actions.addStretch(1)
        subtitle_layout.addLayout(subtitle_actions); lower.addWidget(subtitle)
        warnings = QWidget(); warning_layout = QVBoxLayout(warnings); warning_layout.setContentsMargins(8, 0, 0, 0)
        warning_layout.addWidget(label("需要检查", role="sectionTitle"))
        self.warnings = QListWidget(); self.warnings.itemClicked.connect(self._warning_clicked)
        warning_layout.addWidget(self.warnings, 1); lower.addWidget(warnings); lower.setSizes([760, 300])
        editor_layout.addWidget(lower, 3)
        actions = QHBoxLayout()
        actions.addWidget(button("接受", self.accept, primary=True)); actions.addWidget(button("拒绝", self.reject))
        actions.addStretch(1); actions.addWidget(button("打开成片", self.open_output)); actions.addWidget(button("打开文件夹", self.open_folder))
        editor_layout.addLayout(actions)
        split.addWidget(self.editor); split.setSizes([300, 1100]); layout.addWidget(split, 1)
        controller.clips_ready.connect(self._clips_ready)
        controller.snapshot_ready.connect(self._snapshot_ready)
        controller.variant_ready.connect(self._variant_ready)
        controller.cues_saved.connect(self._cues_saved)
        controller.render_ready.connect(self._render_ready)
        controller.decision_ready.connect(self._decision_ready)
        controller.error.connect(self._show_error)
        context.creator_changed.connect(lambda creator: self.refresh(getattr(creator, "id", None)))
        context.clip_opened.connect(self.open_clip)
        QShortcut(QKeySequence.Save, self, activated=self.save_cues)

    def refresh(self, creator_id: str | None = None) -> None:
        self.controller.load_clips(creator_id)

    def open_clip(self, clip_id: str) -> None:
        self.current_clip_id = clip_id
        self.status.set_state("加载中")
        self.controller.open_clip(clip_id)

    def _clips_ready(self, rows) -> None:
        self.clip_model.replace(rows)
        self.clips.setVisible(bool(rows)); self.empty.setVisible(not rows)
        if self.current_clip_id:
            for row, clip in enumerate(rows):
                if clip.id == self.current_clip_id:
                    self.clips.setCurrentIndex(self.clip_model.index(row, 0)); break

    def _clip_selected(self, index) -> None:
        clip = index.data(OBJECT_ROLE)
        if clip:
            self.title.setText(clip.title); self.open_clip(clip.id)

    def _snapshot_ready(self, payload) -> None:
        self.workflow = payload["workflow"]
        self.current_profile = payload["selected"]
        self._variants = {item.profile: item for item in payload["variants"]}
        self._update_variant_buttons()
        selected = self._variants.get(self.current_profile)
        if selected and selected.status == "READY":
            self._show_variant(selected, payload.get("track"), payload.get("warnings") or [])
        else:
            self.player.stop(); self._clear_cues(); self.status.set_state("尚未生成")
        if payload.get("similarity_warning"):
            self._append_warning({"root_cause": payload["similarity_warning"], "start_ms": 0, "max_severity": "WARNING"})
        self.error.setVisible(False)

    def _update_variant_buttons(self) -> None:
        for name, action in self.variant_buttons.items():
            variant = self._variants.get(name)
            status = variant.status if variant else "NOT_GENERATED"
            suffix = {"READY": "可用", "NOT_GENERATED": "未生成", "NOT_AVAILABLE": "不可用"}.get(status, status.replace("_", " ").title())
            duration = f" · {duration_text(variant.duration_ms)}" if variant and variant.duration_ms else ""
            action.setText(f"{PROFILE_LABELS[name]}\n{suffix}{duration}")
            action.setProperty("primary", name == self.current_profile)
            action.style().unpolish(action); action.style().polish(action)

    def _variant_clicked(self, profile: str) -> None:
        if not self.workflow:
            return
        row = self._variants.get(profile)
        self.current_profile = profile
        if row and row.status == "READY":
            self.status.set_state("切换中")
            self.controller.select_variant(self.workflow, profile)
        elif row and row.status == "NOT_AVAILABLE":
            QMessageBox.information(self, "时长版本", "这个事件没有满足语义边界的该时长版本。")
        else:
            self.status.set_state("生成中")
            self.controller.generate(self.workflow, profile)

    def _variant_ready(self, payload) -> None:
        row = payload["row"]
        variant = self._variants.get(self.current_profile)
        if variant:
            variant = VariantVM(self.current_profile, "READY", int(row.get("duration_ms", 0)), int(row.get("start_ms", 0)), int(row.get("end_ms", 0)), str(row.get("latest_output_path") or row.get("base_output_path") or ""), int(row.get("revision", 0)), len(payload.get("warnings") or []))
            self._variants[self.current_profile] = variant
            self._show_variant(variant, payload.get("track"), payload.get("warnings") or [])
            self._update_variant_buttons()

    def _show_variant(self, variant: VariantVM, track, warnings) -> None:
        self.status.set_state("可用" if not warnings else "需要检查")
        self.start.setValue(variant.start_ms / 1000); self.end.setValue(variant.end_ms / 1000)
        self.player.load(variant.output_path)
        self.player.set_markers(
            variant.duration_ms,
            (),
            (0, variant.duration_ms),
        )
        self._load_cues(track)
        self.warnings.clear()
        for warning in warnings:
            self._append_warning(warning)

    def _load_cues(self, track) -> None:
        self._loading_cues = True; self.cues.setRowCount(0)
        for cue in getattr(track, "cues", ()):
            row = self.cues.rowCount(); self.cues.insertRow(row)
            values = [f"{duration_text(cue.start_ms)}–{duration_text(cue.end_ms)}", cue.zh_text, cue.en_text, cue.translation_status, cue.cue_id]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column not in {1, 2}:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setData(Qt.UserRole, (cue.start_ms, cue.end_ms))
                self.cues.setItem(row, column, item)
        self._loading_cues = False; self._dirty = False; self.save_button.setEnabled(False)

    def _clear_cues(self) -> None:
        self._loading_cues = True; self.cues.setRowCount(0); self._loading_cues = False

    def _cue_changed(self, item) -> None:
        if self._loading_cues or item.column() not in {1, 2}:
            return
        self._dirty = True; self.save_button.setEnabled(True); self.save_timer.start()

    def _cue_seek(self, row: int, _column: int) -> None:
        timing = self.cues.item(row, 0).data(Qt.UserRole)
        if timing:
            self.player.seek_to(int(timing[0]))

    def _edits(self):
        return [{"cue_id": self.cues.item(row, 4).text(), "zh_text": self.cues.item(row, 1).text(), "en_text": self.cues.item(row, 2).text()} for row in range(self.cues.rowCount())]

    def save_cues(self) -> None:
        if self.workflow and self._dirty:
            self.save_timer.stop(); self.status.set_state("保存中")
            self.controller.save_cues(self.workflow, self.current_profile, self._edits())

    def _cues_saved(self, warnings) -> None:
        self._dirty = False; self.save_button.setEnabled(False)
        self.status.set_state("字幕已保存" if not warnings else "字幕已保存 · 有警告")
        if self._pending_render:
            self._pending_render = False; self._start_render()

    def render(self) -> None:
        if not self.workflow:
            return
        if self._dirty:
            self._pending_render = True; self.save_cues(); return
        self._start_render()

    def _start_render(self) -> None:
        start_ms, end_ms = round(self.start.value() * 1000), round(self.end.value() * 1000)
        if end_ms <= start_ms:
            QMessageBox.warning(self, "边界无效", "出点必须晚于入点。")
            return
        self.status.set_state("渲染中")
        self.controller.rerender(self.workflow, self.current_profile, start_ms, end_ms)

    def _render_ready(self, _result) -> None:
        self.status.set_state("新版本已完成")
        if self.current_clip_id:
            self.controller.open_clip(self.current_clip_id)

    def accept(self) -> None:
        if self.workflow:
            self.controller.decide(self.workflow, "ACCEPTED")

    def reject(self) -> None:
        if not self.workflow:
            return
        reasons = ["内容不对", "边界不对", "字幕问题", "翻译问题", "节奏问题", "其他"]
        reason, ok = QInputDialog.getItem(self, "拒绝 Clip", "原因（可选）", reasons, 0, False)
        if ok:
            self.controller.decide(self.workflow, "REJECTED", reason)

    def _decision_ready(self, payload) -> None:
        self.status.set_state("已接受" if payload.get("decision") == "ACCEPTED" else "已拒绝")
        self.refresh(getattr(self.context.creator, "id", None))

    def _append_warning(self, warning) -> None:
        title = str(warning.get("root_cause") or warning.get("recommended_action") or warning.get("type") or "需要检查")
        severity = str(warning.get("max_severity") or warning.get("severity") or "WARNING")
        item = QListWidgetItem(f"{severity} · {title}")
        item.setData(Qt.UserRole, int(warning.get("start_ms") or 0)); self.warnings.addItem(item)

    def _warning_clicked(self, item) -> None:
        self.player.seek_to(int(item.data(Qt.UserRole) or 0))

    def selected_output(self) -> Path | None:
        if not self.workflow:
            return None
        try:
            return self.workflow.selected_output()
        except ValueError:
            return None

    def open_output(self) -> None:
        path = self.selected_output()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_folder(self) -> None:
        path = self.selected_output()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _show_error(self, message: str, details: str) -> None:
        self.error.set_error(message, details); self.error.setVisible(True); self.status.set_state("失败")

    def _retry(self) -> None:
        self.error.setVisible(False)
        if self.current_clip_id:
            self.controller.open_clip(self.current_clip_id)

