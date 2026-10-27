from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt5.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QCheckBox,
)

from acfv.clips import GuiVariantWorkflowService
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService

from .base import TabHandle


LOGGER = logging.getLogger(__name__)
PROFILE_LABELS = {
    "SHORT": "Short", "STANDARD": "Standard", "LONG": "Long",
    "FULL_EVENT": "Full Event", "CUSTOM": "Custom",
}


class _WorkflowWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str, str)

    def __init__(self, workflow: GuiVariantWorkflowService, action: str, *, profile: str = "STANDARD",
                 preserve_edits: bool = True, start_ms: int | None = None, end_ms: int | None = None):
        super().__init__()
        self.workflow = workflow
        self.action = action
        self.profile = profile
        self.preserve_edits = preserve_edits
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.cancel_requested = False

    def cancel_pending(self):
        self.cancel_requested = True

    def run(self):  # pragma: no cover - exercised through Qt integration tests
        try:
            if self.action == "generate_all":
                result = self.workflow.generate_all(
                    preserve_edits=self.preserve_edits,
                    progress=lambda profile, stage: self.progress.emit(profile, stage),
                    cancelled=lambda: self.cancel_requested,
                )
            elif self.action == "generate_selected":
                result = self.workflow.generate_selected(
                    self.profile, preserve_edits=self.preserve_edits,
                    progress=lambda profile, stage: self.progress.emit(profile, stage),
                )
            elif self.action == "rerender":
                self.progress.emit(self.profile, "RENDERING_BILINGUAL")
                result = self.workflow.rerender(self.profile, start_ms=self.start_ms, end_ms=self.end_ms)
                self.progress.emit(self.profile, "READY")
            else:
                raise ValueError(f"Unknown workflow action: {self.action}")
            self.completed.emit(result)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Review workflow failed")
            self.failed.emit(str(exc))


class ReviewTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.library = LibraryService()
        self.feedback = FeedbackService(self.library.repository)
        self.workflow: GuiVariantWorkflowService | None = None
        self.worker: _WorkflowWorker | None = None
        self._loading = False
        self._cue_dirty = False
        self._media_path: Path | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        self.event_header = QLabel("Recording / Event: select a Clip or open an Event Plan")
        self.event_header.setWordWrap(True)
        self.event_header.setStyleSheet("font-weight: 600; padding: 6px;")
        root.addWidget(self.event_header)

        selector_row = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.load_selected_clip)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        selector_row.addWidget(QLabel("Clip:"))
        selector_row.addWidget(self.selector, 1)
        selector_row.addWidget(refresh)
        root.addLayout(selector_row)

        upper = QHBoxLayout()
        upper.addWidget(self._build_player(), 3)
        upper.addWidget(self._build_duration_controls(), 2)
        root.addLayout(upper)
        variant_group = self._build_variant_table()
        root.addWidget(variant_group)
        root.addWidget(self.similarity_warning)
        root.addWidget(self._build_subtitle_controls())
        root.addWidget(self._build_cue_editor(), 1)

        action_row = QHBoxLayout()
        for label, slot in (
            ("Save Cues", self.save_cues), ("Re-render", self.rerender),
            ("Open Video", self.open_video), ("Open Folder", self.open_folder),
            ("Reject", self.reject), ("Accept", self.accept),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            action_row.addWidget(button)
        root.addLayout(action_row)

        preference_row = QHBoxLayout()
        self.preference = QLineEdit()
        self.preference.setPlaceholderText("显式偏好，例如：不要纯 gameplay")
        save_preference = QPushButton("保存偏好")
        save_preference.clicked.connect(self.add_preference)
        preference_row.addWidget(self.preference, 1)
        preference_row.addWidget(save_preference)
        root.addLayout(preference_row)
        self.status = QLabel("Ready")
        root.addWidget(self.status)
        self.refresh()

    def _build_player(self) -> QGroupBox:
        group = QGroupBox("Video Preview")
        layout = QVBoxLayout(group)
        try:
            from PyQt5.QtMultimedia import QMediaPlayer
            from PyQt5.QtMultimediaWidgets import QVideoWidget
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(230)
            self.player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
            self.player.setVideoOutput(self.video_widget)
            self.player.positionChanged.connect(self._position_changed)
            self.player.durationChanged.connect(self._duration_changed)
            layout.addWidget(self.video_widget)
        except Exception as exc:  # pragma: no cover
            self.player = None
            self.video_widget = QLabel(f"Video preview unavailable: {exc}")
            self.video_widget.setMinimumHeight(230)
            self.video_widget.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.video_widget)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(lambda value: self.player and self.player.setPosition(value))
        self.time_label = QLabel("00:00 / 00:00")
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(50)
        self.volume.setMaximumWidth(110)
        self.volume.valueChanged.connect(lambda value: self.player and self.player.setVolume(value))
        self.volume.sliderReleased.connect(self._settings_changed)
        controls.addWidget(self.play_button)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.time_label)
        controls.addWidget(QLabel("Volume"))
        controls.addWidget(self.volume)
        layout.addLayout(controls)
        return group

    def _build_duration_controls(self) -> QGroupBox:
        group = QGroupBox("Duration Profile")
        layout = QVBoxLayout(group)
        self.duration_profile = QComboBox()
        for value in ("SHORT", "STANDARD", "LONG", "FULL_EVENT", "CUSTOM"):
            self.duration_profile.addItem(PROFILE_LABELS[value], value)
        self.duration_profile.setCurrentIndex(self.duration_profile.findData("STANDARD"))
        self.duration_profile.currentIndexChanged.connect(self._profile_changed)
        layout.addWidget(self.duration_profile)
        custom_form = QFormLayout()
        self.custom_target = QDoubleSpinBox(); self.custom_target.setRange(5, 600); self.custom_target.setValue(60)
        self.custom_min = QDoubleSpinBox(); self.custom_min.setRange(5, 600); self.custom_min.setValue(30)
        self.custom_max = QDoubleSpinBox(); self.custom_max.setRange(5, 600); self.custom_max.setValue(90)
        custom_form.addRow("Target Duration", self.custom_target)
        custom_form.addRow("Minimum", self.custom_min)
        custom_form.addRow("Maximum", self.custom_max)
        layout.addLayout(custom_form)
        self.custom_controls = (self.custom_target, self.custom_min, self.custom_max)
        self.custom_labels = tuple(custom_form.labelForField(control) for control in self.custom_controls)
        self.generate_selected_button = QPushButton("Generate Selected")
        self.generate_selected_button.clicked.connect(self.generate_selected)
        self.generate_all_button = QPushButton("Generate All")
        self.generate_all_button.clicked.connect(self.generate_all)
        self.cancel_button = QPushButton("Cancel Pending")
        self.cancel_button.clicked.connect(self.cancel_pending)
        self.cancel_button.setEnabled(False)
        layout.addWidget(self.generate_selected_button)
        layout.addWidget(self.generate_all_button)
        layout.addWidget(self.cancel_button)
        self._profile_changed()
        return group

    def _build_variant_table(self) -> QGroupBox:
        group = QGroupBox("Variant Comparison")
        layout = QVBoxLayout(group)
        self.variant_table = QTableWidget(5, 11)
        self.variant_table.setHorizontalHeaderLabels(
            ["Profile", "Duration", "Start / End", "Hook", "Setup", "Payoff", "Reaction", "Aftermath", "Cues", "Status", "Actions"]
        )
        self.variant_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.variant_table.verticalHeader().setVisible(False)
        self.variant_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.variant_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.variant_table)
        self.similarity_warning = QLabel("")
        self.similarity_warning.setStyleSheet("color: #8a6d3b;")
        return group

    def _build_subtitle_controls(self) -> QGroupBox:
        group = QGroupBox("Subtitle Mode")
        layout = QHBoxLayout(group)
        self.bilingual_mode = QComboBox()
        self.bilingual_mode.addItems(["ZH_EN", "EN_ZH", "ZH_ONLY", "EN_ONLY", "SOURCE_ONLY", "SOURCE_ZH", "SOURCE_EN"])
        self.subtitle_completeness = QComboBox(); self.subtitle_completeness.addItems(["COMPLETE", "CLEAN"])
        self.subtitle_position = QComboBox(); self.subtitle_position.addItems(["AUTO_SAFE_AREA", "TOP", "BOTTOM"])
        self.resolved_position = QLabel("Resolved Position: TOP")
        self.apply_to_all = QCheckBox("Apply to All Variants")
        for control in (self.bilingual_mode, self.subtitle_completeness, self.subtitle_position):
            control.currentTextChanged.connect(self._settings_changed)
        layout.addWidget(self.bilingual_mode)
        layout.addWidget(self.subtitle_completeness)
        layout.addWidget(self.subtitle_position)
        layout.addWidget(self.resolved_position)
        layout.addWidget(self.apply_to_all)
        layout.addStretch(1)
        return group

    def _build_cue_editor(self) -> QGroupBox:
        group = QGroupBox("Subtitle Cue Editor")
        layout = QVBoxLayout(group)
        boundary = QHBoxLayout()
        self.start = QDoubleSpinBox(); self.end = QDoubleSpinBox()
        for control in (self.start, self.end):
            control.setRange(0, 24 * 3600); control.setDecimals(3)
        boundary.addWidget(QLabel("Start")); boundary.addWidget(self.start)
        boundary.addWidget(QLabel("End")); boundary.addWidget(self.end)
        for label, slot in (
            ("Start -1s", lambda: self.start.setValue(max(0, self.start.value() - 1))),
            ("Start +1s", lambda: self.start.setValue(self.start.value() + 1)),
            ("End -1s", lambda: self.end.setValue(max(0, self.end.value() - 1))),
            ("End +1s", lambda: self.end.setValue(self.end.value() + 1)),
        ):
            button = QPushButton(label); button.clicked.connect(slot); boundary.addWidget(button)
        layout.addLayout(boundary)
        self.cue_table = QTableWidget(0, 8)
        self.cue_table.setHorizontalHeaderLabels(["Cue ID", "Start", "End", "中文", "English", "Translation", "Dirty", "Warning"])
        self.cue_table.verticalHeader().setVisible(False)
        self.cue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.cue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.cue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.cue_table.itemChanged.connect(self._cue_item_changed)
        layout.addWidget(self.cue_table)
        return group

    def refresh(self):
        selected = self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        for clip in self.library.repository.list_clips():
            self.selector.addItem(f"{clip.id[:8]} · {clip.render_status.value} · {clip.query}", clip.id)
        index = self.selector.findData(selected)
        self.selector.setCurrentIndex(index if index >= 0 else (0 if self.selector.count() else -1))
        self.selector.blockSignals(False)
        if self.workflow:
            self.refresh_variants()
        else:
            self.load_selected_clip()

    def open_recording(self, recording_id: str):
        for index in range(self.selector.count()):
            clip = self.library.repository.get_clip(self.selector.itemData(index))
            if clip and clip.recording_id == recording_id:
                self.selector.setCurrentIndex(index)
                return
        if self.library.get_recording(recording_id) is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        self.event_header.setText(f"Recording: {recording_id} · No reviewed Clip/Event Plan loaded")

    def open_event_plan(self, event_plan, *, recording_id=None, output_root=None):
        plan_path = Path(str(event_plan)).resolve()
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_recording = str(raw.get("recording_id") or "")
        if recording_id and plan_recording and str(recording_id) != plan_recording:
            raise ValueError("Recording does not match event plan")
        identity = str(recording_id or raw.get("recording_id") or raw.get("event_id"))
        target = Path(str(output_root)).resolve() if output_root else (
            Path(__file__).resolve().parents[4] / "outputs" / "bilingual-duration-validation" / identity
        )
        self.workflow = GuiVariantWorkflowService(plan_path, target, repository=self.library.repository)
        self.event_header.setText(
            f"Recording: {identity} · Event: {self.workflow.plan.event_id} · Payoff: {self.workflow.plan.payoff_anchor_ms} ms"
        )
        self._load_settings()
        self.refresh_variants()
        preferred = "STANDARD" if (self.workflow.state["variants"].get("STANDARD") or {}).get("status") == "READY" else self.workflow.selected_profile
        self._select_profile_control(preferred)
        self.load_variant(preferred, select=True)

    def _load_settings(self):
        if not self.workflow:
            return
        settings = self.workflow.settings()
        self._loading = True
        self.bilingual_mode.setCurrentText(settings["display_mode"])
        self.subtitle_completeness.setCurrentText(settings["completeness"])
        self.subtitle_position.setCurrentText(settings["position"])
        self.custom_target.setValue(float(settings["custom_target_seconds"]))
        self.custom_min.setValue(float(settings["custom_min_seconds"]))
        self.custom_max.setValue(float(settings["custom_max_seconds"]))
        self.volume.setValue(int(settings["preview_volume"]))
        self._loading = False

    def load_selected_clip(self):
        if self.workflow:
            return
        clip_id = self.selector.currentData()
        clip = self.library.repository.get_clip(clip_id) if clip_id else None
        if clip is None:
            return
        self.start.setValue(clip.final_start_ms / 1000)
        self.end.setValue(clip.final_end_ms / 1000)
        self.event_header.setText(f"Recording: {clip.recording_id} · Query: {clip.query} · Moment: {clip.moment_id}")
        self.status.setText(f"Render: {clip.render_status.value} · Review: {clip.review_status.value}")

    def refresh_variants(self):
        if not self.workflow:
            return
        rows = self.workflow.scan_outputs()
        for row_index, row in enumerate(rows):
            profile = str(row.get("profile"))
            duration = f"{int(row.get('duration_ms', 0)) / 1000:.1f} sec" if row.get("duration_ms") else "—"
            bounds = f"{int(row.get('start_ms', 0)) / 1000:.3f} / {int(row.get('end_ms', 0)) / 1000:.3f}" if row.get("start_ms") is not None else "—"
            structural = {
                "SHORT": ("Yes", "Minimum", "Yes", "Primary", "No"),
                "STANDARD": ("Yes", "Yes", "Yes", "Yes", "Short"),
                "LONG": ("Yes", "Full", "Yes", "Yes", "Discussion"),
                "FULL_EVENT": ("Yes", "Full", "Yes", "Full", "Full"),
            }.get(profile, ("Yes", "Custom", "Yes", "Custom", "Custom"))
            cue_count = "—"
            report = self.workflow.output_root / profile.casefold() / "subtitle_timeline_report.json"
            if report.is_file():
                try:
                    cue_count = str(json.loads(report.read_text(encoding="utf-8"))["cue_count"])
                except Exception:
                    pass
            values = [PROFILE_LABELS.get(profile, profile), duration, bounds, *structural, cue_count,
                      str(row.get("status") or "NOT_GENERATED")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if row.get("selected") or profile == self.workflow.selected_profile:
                    item.setBackground(Qt.yellow)
                self.variant_table.setItem(row_index, column, item)
            actions = QWidget(); action_layout = QHBoxLayout(actions); action_layout.setContentsMargins(0, 0, 0, 0)
            preview = QPushButton("Preview")
            preview.setEnabled(row.get("status") == "READY")
            preview.clicked.connect(lambda _checked=False, name=profile: self.load_variant(name))
            select = QPushButton("Selected" if profile == self.workflow.selected_profile else "Select")
            select.setEnabled(row.get("status") == "READY")
            select.clicked.connect(lambda _checked=False, name=profile: self.select_variant(name))
            retry = QPushButton("Retry")
            retry.setVisible(row.get("status") in {"FAILED", "INTERRUPTED", "RETRY_AVAILABLE"})
            retry.clicked.connect(lambda _checked=False, name=profile: self._start_worker("generate_selected", name))
            action_layout.addWidget(preview); action_layout.addWidget(select); action_layout.addWidget(retry)
            self.variant_table.setCellWidget(row_index, 10, actions)
        self.similarity_warning.setText(self.workflow.similarity_warning())

    def _select_profile_control(self, profile: str):
        index = self.duration_profile.findData(profile)
        if index >= 0:
            self.duration_profile.setCurrentIndex(index)

    def _profile_changed(self):
        is_custom = self.duration_profile.currentData() == "CUSTOM"
        for control in getattr(self, "custom_controls", ()):
            control.setVisible(is_custom)
        for label in getattr(self, "custom_labels", ()):
            if label:
                label.setVisible(is_custom)

    def _settings_changed(self):
        if self._loading or not self.workflow:
            return
        try:
            self._persist_settings()
            resolved = "TOP" if self.subtitle_position.currentText() == "AUTO_SAFE_AREA" else self.subtitle_position.currentText()
            self.resolved_position.setText(f"Resolved Position: {resolved}")
            self.refresh_variants()
        except Exception as exc:
            QMessageBox.warning(self, "Subtitle settings", str(exc))

    def _persist_settings(self):
        if not self.workflow:
            raise ValueError("No event plan selected")
        self.workflow.update_settings(
            display_mode=self.bilingual_mode.currentText(), completeness=self.subtitle_completeness.currentText(),
            position=self.subtitle_position.currentText(), custom_target_seconds=self.custom_target.value(),
            custom_min_seconds=self.custom_min.value(), custom_max_seconds=self.custom_max.value(),
            preview_volume=self.volume.value(), apply_to_all=self.apply_to_all.isChecked(),
        )

    def _regeneration_policy(self, profiles: list[str]) -> bool | None:
        if not self.workflow or not any((self.workflow.state["variants"].get(name) or {}).get("cue_edit_count") for name in profiles):
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Regenerate subtitles")
        box.setText("Regenerating may overwrite subtitle edits.")
        preserve = box.addButton("Regenerate and Preserve Edits When Possible", QMessageBox.AcceptRole)
        box.addButton("Regenerate and Reset Edits", QMessageBox.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is cancel:
            return None
        return box.clickedButton() is preserve

    def generate_selected(self):
        profile = str(self.duration_profile.currentData())
        policy = self._regeneration_policy([profile])
        if policy is not None:
            self._persist_settings()
            self._start_worker("generate_selected", profile, preserve_edits=policy)

    def generate_all(self):
        profiles = ["SHORT", "STANDARD", "LONG", "FULL_EVENT"]
        policy = self._regeneration_policy(profiles)
        if policy is not None:
            self._persist_settings()
            self._start_worker("generate_all", "STANDARD", preserve_edits=policy)

    def _start_worker(self, action: str, profile: str, *, preserve_edits: bool = True):
        if not self.workflow:
            QMessageBox.warning(self, "Review", "No event plan selected")
            return
        if self.worker and self.worker.isRunning():
            return
        self.worker = _WorkflowWorker(self.workflow, action, profile=profile, preserve_edits=preserve_edits,
                                      start_ms=round(self.start.value() * 1000), end_ms=round(self.end.value() * 1000))
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._worker_completed)
        self.worker.failed.connect(self._worker_failed)
        self.worker.finished.connect(lambda: self.cancel_button.setEnabled(False))
        self.cancel_button.setEnabled(action == "generate_all")
        self.generate_all_button.setEnabled(False); self.generate_selected_button.setEnabled(False)
        self.worker.start()

    def _progress(self, profile: str, stage: str):
        self.status.setText(f"{PROFILE_LABELS.get(profile, profile)} · {stage}")
        self.refresh_variants()

    def _worker_completed(self, _result):
        self.generate_all_button.setEnabled(True); self.generate_selected_button.setEnabled(True)
        self.refresh_variants()
        profile = "STANDARD" if self.workflow and (self.workflow.state["variants"].get("STANDARD") or {}).get("status") == "READY" else self.workflow.selected_profile
        self.load_variant(profile, select=True)
        self.status.setText("Workflow completed")

    def _worker_failed(self, message: str):
        self.generate_all_button.setEnabled(True); self.generate_selected_button.setEnabled(True)
        self.refresh_variants()
        QMessageBox.critical(self, "Variant render failed", message)

    def cancel_pending(self):
        if self.worker:
            self.worker.cancel_pending()
            self.status.setText("Cancel requested; current safe write will finish.")

    def load_variant(self, profile: str, *, select: bool = False):
        if not self.workflow:
            return
        row = self.workflow.state["variants"].get(profile) or {}
        if row.get("status") != "READY":
            return
        self._select_profile_control(profile)
        self.start.setValue(int(row["start_ms"]) / 1000)
        self.end.setValue(int(row["end_ms"]) / 1000)
        self._load_cues(profile)
        path = Path(str(row.get("latest_output_path") or row.get("base_output_path") or ""))
        self.set_preview(path)
        if select:
            self.workflow.select_variant(profile)
            self.refresh_variants()

    def select_variant(self, profile: str):
        if not self.workflow:
            return
        self.workflow.select_variant(profile)
        self.load_variant(profile)
        self.refresh_variants()

    def _load_cues(self, profile: str):
        if not self.workflow:
            return
        try:
            track = self.workflow.load_track(profile)
        except Exception as exc:
            QMessageBox.critical(self, "Subtitle track invalid", str(exc))
            return
        warnings = set((self.workflow.state["variants"].get(profile) or {}).get("validation_warnings") or [])
        self._loading = True
        self.cue_table.setRowCount(len(track.cues))
        for row, cue in enumerate(track.cues):
            values = [cue.cue_id, self._format_ms(cue.start_ms), self._format_ms(cue.end_ms), cue.zh_text,
                      cue.en_text, cue.translation_status, "Yes" if cue.translation_status == "USER_EDITED" else "No",
                      "; ".join(item for item in warnings if item.startswith(cue.cue_id))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column not in {3, 4}:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.cue_table.setItem(row, column, item)
        self._loading = False
        self._cue_dirty = False

    def _cue_item_changed(self, item):
        if not self._loading and item.column() in {3, 4}:
            self._cue_dirty = True
            dirty = self.cue_table.item(item.row(), 6)
            if dirty:
                dirty.setText("Yes")

    def save_cues(self):
        if not self.workflow:
            QMessageBox.warning(self, "Save Cues", "No event plan selected")
            return False
        profile = str(self.duration_profile.currentData())
        edits = []
        for row in range(self.cue_table.rowCount()):
            edits.append({"cue_id": self.cue_table.item(row, 0).text(),
                          "zh_text": self.cue_table.item(row, 3).text(),
                          "en_text": self.cue_table.item(row, 4).text()})
        try:
            warnings = self.workflow.save_cues(profile, edits)
            self._cue_dirty = False
            self.status.setText(f"Cues saved · {len(warnings)} warning(s)")
            self._load_cues(profile)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Save Cues", str(exc))
            return False

    def rerender(self):
        if not self.workflow:
            QMessageBox.warning(self, "Re-render", "No event plan selected")
            return
        self._persist_settings()
        if self._cue_dirty and not self.save_cues():
            return
        self._start_worker("rerender", str(self.duration_profile.currentData()))

    def set_preview(self, path: Path):
        if not path.is_file():
            QMessageBox.critical(self, "Output file missing", str(path))
            return
        self._media_path = path.resolve()
        if self.player:
            from PyQt5.QtMultimedia import QMediaContent
            self.player.stop()
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(self._media_path))))
            self.player.setPosition(0)
            self.play_button.setText("Play")
        self.status.setText(f"Preview loaded: {self._media_path.name}")

    def toggle_play(self):
        if not self.player or not self._media_path:
            return
        from PyQt5.QtMultimedia import QMediaPlayer
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause(); self.play_button.setText("Play")
        else:
            if self.player.position() >= max(0, self.player.duration() - 250):
                self.player.setPosition(0)
            self.player.play(); self.play_button.setText("Pause")

    def _position_changed(self, value: int):
        self.seek.setValue(value)
        self.time_label.setText(f"{self._format_ms(value)} / {self._format_ms(self.player.duration() if self.player else 0)}")

    def _duration_changed(self, value: int):
        self.seek.setRange(0, value)

    @staticmethod
    def _format_ms(value: int) -> str:
        seconds = max(0, int(value)) // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def open_video(self):
        try:
            path = self.workflow.selected_output() if self.workflow else self._media_path
            if not path or not Path(path).is_file():
                raise ValueError("Output file missing")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
        except Exception as exc:
            QMessageBox.critical(self, "Open Video", str(exc))

    def open_folder(self):
        if not self.workflow:
            QMessageBox.warning(self, "Open Folder", "No event plan selected")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.workflow.output_root)))

    def accept(self):
        if self.workflow:
            try:
                decision = self.workflow.record_decision(FeedbackDecision.ACCEPTED.value)
                self.status.setText(f"Accepted: {decision['profile']}")
            except Exception as exc:
                QMessageBox.critical(self, "Accept", str(exc))
            return
        clip = self._selected_clip()
        if clip:
            self.feedback.decide(clip.id, FeedbackDecision.ACCEPTED)
            self.refresh()

    def reject(self):
        reasons = ["Wrong Content", "Too Short", "Too Long", "Bad Boundary", "Bad Subtitle",
                   "Translation Problem", "Low Watchability", "Other"]
        reason, ok = QInputDialog.getItem(self, "Reject", "Reason", reasons, 0, False)
        if not ok:
            return
        if self.workflow:
            self.workflow.record_decision(FeedbackDecision.REJECTED.value, reason=reason)
            self.status.setText(f"Rejected: {reason}")
            return
        clip = self._selected_clip()
        if clip:
            self.feedback.decide(clip.id, FeedbackDecision.REJECTED, reason=reason)
            self.refresh()

    def add_preference(self):
        clip = self._selected_clip()
        try:
            self.feedback.add_preference(self.preference.text(), creator_id=clip.creator_id if clip else None)
            self.preference.clear()
            QMessageBox.information(self, "Preference", "显式偏好已保存。")
        except Exception as exc:
            QMessageBox.critical(self, "Preference", str(exc))

    def _selected_clip(self):
        clip_id = self.selector.currentData()
        return self.library.repository.get_clip(clip_id) if clip_id else None

    def closeEvent(self, event):
        if self.player:
            self.player.stop()
        if self.worker and self.worker.isRunning():
            self.worker.cancel_pending()
        super().closeEvent(event)


def create_review_tab(parent, config_manager) -> TabHandle:
    widget = ReviewTab(config_manager, parent)
    return TabHandle(title="Review", widget=widget, controller=widget)
