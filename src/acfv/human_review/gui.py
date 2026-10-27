from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from acfv.product_gui.theme import stylesheet
from acfv.product_gui.workers import GuiExecutor, RequestToken

if os.environ.get("QT_QPA_PLATFORM", "").lower() not in {"offscreen", "minimal"}:
    from acfv.product_gui.player import MediaPlayer
else:  # Keep headless tests away from the Windows DirectShow plugin.
    MediaPlayer = None  # type: ignore[assignment,misc]

from .analysis import HumanReviewAnalysis
from .dataset import DatasetBuildResult, HumanReviewDatasetBuilder
from .export import HumanReviewExporter
from .models import ReviewSample, ReviewTask, TASK_ORDER
from .repository import HumanReviewRepository


TASK_LABELS = {
    ReviewTask.ASR: "ASR",
    ReviewTask.IDENTITY: "Identity",
    ReviewTask.TRUSTED_SPEECH: "Trusted Speech",
    ReviewTask.ADAPTIVE_ASR: "Adaptive ASR",
    ReviewTask.TRANSLATION: "Translation",
    ReviewTask.BOUNDARY: "Boundary",
    ReviewTask.WATCHABILITY: "Watchability",
    ReviewTask.SUBTITLE: "Subtitle",
    ReviewTask.PUBLISHABILITY: "Publishability",
}


def review_stylesheet() -> str:
    """Product tokens plus explicit text colors for reliable DPI/headless rendering."""
    return stylesheet() + """
    QLabel, QCheckBox, QGroupBox, QMenu, QStatusBar { color: #f4f6fb; }
    QPushButton, QToolButton, QComboBox, QPlainTextEdit { color: #f4f6fb; }
    QMenu { background: #171c28; border: 1px solid #293244; }
    QMenu::item:selected { background: #2a2450; }
    """

CHOICES = {
    ReviewTask.ASR: (("Correct", "correct"), ("Minor Error", "minor"), ("Wrong", "wrong"), ("Unclear", "unclear")),
    ReviewTask.IDENTITY: (("Correct", "correct"), ("Wrong", "wrong"), ("Unknown", "unknown"), ("Multiple", "multiple")),
    ReviewTask.ADAPTIVE_ASR: (("A Better", "a"), ("B Better", "b"), ("Same", "same"), ("Both Wrong", "both_wrong")),
    ReviewTask.TRANSLATION: (("A Better", "a"), ("B Better", "b"), ("Same", "same"), ("Both Bad", "both_bad")),
    ReviewTask.WATCHABILITY: (("A Better", "a"), ("B Better", "b"), ("Same", "same"), ("Both Bad", "both_bad")),
    ReviewTask.PUBLISHABILITY: (("Keep", "keep"), ("Maybe", "maybe"), ("Reject", "reject")),
}


def _card(parent: QWidget | None = None) -> QFrame:
    frame = QFrame(parent)
    frame.setProperty("card", True)
    return frame


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("muted", True)
    label.setWordWrap(True)
    return label


class _NullPlayerBackend:
    def __init__(self) -> None:
        self._position = 0

    def setPlaybackRate(self, _value: float) -> None:  # noqa: N802 - Qt-compatible test adapter
        return

    def position(self) -> int:
        return self._position

    def setPosition(self, value: int) -> None:  # noqa: N802 - Qt-compatible test adapter
        self._position = max(0, int(value))


class _OffscreenMediaPlayer(QWidget):
    """Avoid loading the Windows multimedia plugin in headless contract tests."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.player = _NullPlayerBackend()
        self._path = ""
        layout = QVBoxLayout(self)
        panel = QLabel("Media preview")
        panel.setAlignment(Qt.AlignCenter)
        panel.setMinimumHeight(240)
        panel.setStyleSheet("background:#050608;border-radius:10px")
        layout.addWidget(panel)

    def load(self, path: str, **_kwargs: Any) -> None:
        self._path = path

    def seek_to(self, _position_ms: int) -> None:
        self.player.setPosition(_position_ms)

    def stop(self) -> None:
        return


def _media_player(parent=None) -> QWidget:
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        return _OffscreenMediaPlayer(parent)
    assert MediaPlayer is not None
    return MediaPlayer(parent)


class SettingsDialog(QDialog):
    def __init__(self, values: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review Settings")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        self.speed = QComboBox()
        for value in (0.75, 1.0, 1.25, 1.5, 2.0):
            self.speed.addItem(f"{value:g}×", value)
        current = float(values.get("playback_speed", 1.0))
        self.speed.setCurrentIndex(max(0, self.speed.findData(current)))
        self.autoplay = QCheckBox("Auto play media")
        self.autoplay.setChecked(bool(values.get("auto_play", False)))
        self.auto_next = QCheckBox("Auto next after quick answer")
        self.auto_next.setChecked(bool(values.get("auto_next", True)))
        self.loop_asr = QCheckBox("Loop ASR audio")
        self.loop_asr.setChecked(bool(values.get("loop_asr", False)))
        self.order = QComboBox()
        self.order.addItems(["High Information", "Random", "Sequential"])
        self.order.setCurrentText(str(values.get("review_order", "High Information")))
        self.reveal = QCheckBox("Reveal A/B identity after answer")
        self.reveal.setChecked(bool(values.get("reveal_after_answer", False)))
        self.theme = QComboBox(); self.theme.addItems(["Dark"])
        for label, widget in (
            ("Playback speed", self.speed), ("Review order", self.order), ("Theme", self.theme)
        ):
            row = QHBoxLayout(); row.addWidget(QLabel(label)); row.addStretch(); row.addWidget(widget); layout.addLayout(row)
        layout.addWidget(self.autoplay); layout.addWidget(self.auto_next); layout.addWidget(self.loop_asr); layout.addWidget(self.reveal)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def result_values(self) -> dict[str, Any]:
        return {
            "playback_speed": float(self.speed.currentData()), "auto_play": self.autoplay.isChecked(),
            "auto_next": self.auto_next.isChecked(), "loop_asr": self.loop_asr.isChecked(),
            "review_order": self.order.currentText(), "reveal_after_answer": self.reveal.isChecked(), "theme": self.theme.currentText(),
        }


class OverviewPage(QWidget):
    def __init__(self, on_continue: Callable[[], None], on_task: Callable[[ReviewTask], None], on_build: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ReviewOverview")
        self._on_task = on_task
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 24); layout.setSpacing(18)
        title = QLabel("Human Review"); title.setProperty("role", "pageTitle")
        self.overall = QLabel("Overall · 0 / 0"); self.overall.setProperty("muted", True)
        head = QHBoxLayout(); head.addWidget(title); head.addStretch(); head.addWidget(self.overall)
        layout.addLayout(head)
        self.empty = _card(); empty_layout = QVBoxLayout(self.empty)
        empty_layout.addWidget(QLabel("Human Review dataset not built."))
        empty_layout.addWidget(_muted("Build it from canonical ACFV evidence. The operation runs in the background."))
        build = QPushButton("Build Dataset"); build.setProperty("primary", True); build.clicked.connect(on_build); empty_layout.addWidget(build, 0, Qt.AlignLeft)
        layout.addWidget(self.empty)
        self.continue_button = QPushButton("Continue Review →"); self.continue_button.setProperty("primary", True); self.continue_button.setMinimumHeight(46); self.continue_button.clicked.connect(on_continue)
        layout.addWidget(self.continue_button)
        self.grid = QGridLayout(); self.grid.setSpacing(14); layout.addLayout(self.grid)
        self.cards: dict[ReviewTask, tuple[QLabel, QProgressBar, QPushButton, QFrame]] = {}
        for index, task in enumerate(TASK_ORDER):
            frame = _card(); box = QVBoxLayout(frame); box.setContentsMargins(18, 16, 18, 16)
            name = QLabel(TASK_LABELS[task]); name.setProperty("role", "sectionTitle")
            progress_label = QLabel("0 / 0"); progress_label.setProperty("muted", True)
            bar = QProgressBar(); bar.setTextVisible(False); bar.setRange(0, 1)
            button = QPushButton("Continue"); button.clicked.connect(lambda _=False, current=task: self._on_task(current))
            box.addWidget(name); box.addWidget(progress_label); box.addWidget(bar); box.addWidget(button, 0, Qt.AlignLeft)
            self.grid.addWidget(frame, index // 3, index % 3)
            self.cards[task] = (progress_label, bar, button, frame)
        layout.addStretch()

    def refresh(self, progress) -> None:
        total = sum(item.total for item in progress); done = sum(item.completed for item in progress)
        self.overall.setText(f"Overall · {done} / {total}")
        self.empty.setVisible(total == 0); self.continue_button.setEnabled(done < total and total > 0)
        for item in progress:
            label, bar, button, _frame = self.cards[item.task]
            label.setText("✓" if item.total and item.completed >= item.total else f"{item.completed} / {item.total}")
            bar.setRange(0, max(1, item.total)); bar.setValue(item.completed)
            button.setEnabled(item.completed < item.total)


class ReviewPage(QWidget):
    def __init__(self, task: ReviewTask, shell: "HumanReviewWindow", parent=None) -> None:
        super().__init__(parent)
        self.task = task; self.shell = shell; self.current: ReviewSample | None = None; self.items: list[ReviewSample] = []; self.index = -1
        self.queue_state = "remaining"; self.creator_filter = ""; self.content_filter = ""; self.subtitle_mode = ""
        self.choice_buttons: list[QPushButton] = []
        outer = QVBoxLayout(self); outer.setContentsMargins(24, 18, 24, 16); outer.setSpacing(12)
        top = QHBoxLayout()
        self.header = QLabel(TASK_LABELS[task]); self.header.setProperty("role", "pageTitle")
        self.counter = QLabel("0 / 0"); self.counter.setProperty("muted", True)
        self.filter_button = QPushButton("Filter ▾"); self.filter_button.clicked.connect(self._filters)
        top.addWidget(self.header); top.addWidget(self.counter); top.addStretch()
        self.cue_filter = QPushButton("Cue"); self.clip_filter = QPushButton("Clip")
        for button, mode in ((self.cue_filter, "cue"), (self.clip_filter, "clip")):
            button.setCheckable(True); button.clicked.connect(lambda _=False, value=mode: self._set_subtitle_mode(value)); top.addWidget(button)
            button.setVisible(task == ReviewTask.SUBTITLE)
        top.addWidget(self.filter_button); outer.addLayout(top)
        split = QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False)
        media_card = _card(); media_layout = QVBoxLayout(media_card); media_layout.setContentsMargins(14, 14, 14, 14)
        self.player = _media_player(); media_layout.addWidget(self.player, 1)
        media_status = getattr(self.player.player, "mediaStatusChanged", None)
        if media_status is not None:
            media_status.connect(self._media_status_changed)
        pair = QHBoxLayout(); self.play_a = QPushButton("Play A"); self.play_b = QPushButton("Play B")
        self.play_a.clicked.connect(lambda: self._load_pair("a")); self.play_b.clicked.connect(lambda: self._load_pair("b")); pair.addWidget(self.play_a); pair.addWidget(self.play_b); pair.addStretch(); media_layout.addLayout(pair)
        self.missing_media = _muted(""); self.missing_media.setProperty("state", "warning")
        self.relink = QPushButton("Relink Media…"); self.relink.clicked.connect(self._relink_media)
        media_layout.addWidget(self.missing_media); media_layout.addWidget(self.relink, 0, Qt.AlignLeft)
        self.context = QLabel(""); self.context.setWordWrap(True); self.context.setTextInteractionFlags(Qt.TextSelectableByMouse); media_layout.addWidget(self.context)
        split.addWidget(media_card)
        decision_card = _card(); decision_layout = QVBoxLayout(decision_card); decision_layout.setContentsMargins(18, 16, 18, 16)
        self.decision_title = QLabel("Your judgement"); self.decision_title.setProperty("role", "sectionTitle"); decision_layout.addWidget(self.decision_title)
        self.choice_box = QVBoxLayout(); decision_layout.addLayout(self.choice_box)
        self.human_text = QPlainTextEdit(); self.human_text.setPlaceholderText("Human transcript / correct Creator ID"); self.human_text.setMaximumHeight(100); self.human_text.setVisible(task in {ReviewTask.ASR, ReviewTask.IDENTITY, ReviewTask.ADAPTIVE_ASR}); decision_layout.addWidget(self.human_text)
        self.more = QGroupBox("More"); self.more.setCheckable(True); self.more.setChecked(False); self.more_layout = QVBoxLayout(self.more)
        self.more_fields: dict[str, Any] = {}; self._build_more(); decision_layout.addWidget(self.more)
        self.details = QGroupBox("Details"); self.details.setCheckable(True); self.details.setChecked(False); self.details_text = _muted(""); details_layout = QVBoxLayout(self.details); details_layout.addWidget(self.details_text); decision_layout.addWidget(self.details)
        self.note = QPlainTextEdit(); self.note.setPlaceholderText("Optional note"); self.note.setMaximumHeight(80); self.note.setVisible(False)
        note_button = QPushButton("Add note"); note_button.clicked.connect(lambda: self.note.setVisible(not self.note.isVisible())); decision_layout.addWidget(note_button); decision_layout.addWidget(self.note)
        decision_layout.addStretch(); split.addWidget(decision_card); split.setStretchFactor(0, 7); split.setStretchFactor(1, 4)
        outer.addWidget(split, 1)
        bottom = QHBoxLayout(); self.back = QPushButton("← Back"); self.back.clicked.connect(self.go_back)
        self.revisit = QPushButton("☆ Revisit"); self.revisit.clicked.connect(self.mark_revisit)
        self.skip = QPushButton("Skip"); self.skip.clicked.connect(self.skip_current)
        self.saved = QLabel(""); self.saved.setProperty("state", "ready")
        self.save_next = QPushButton("Save & Next →"); self.save_next.setProperty("primary", True); self.save_next.clicked.connect(self.save)
        bottom.addWidget(self.back); bottom.addWidget(self.revisit); bottom.addStretch(); bottom.addWidget(self.saved); bottom.addWidget(self.skip); bottom.addWidget(self.save_next); outer.addLayout(bottom)
        hint = _muted("1–4 choose · Space play · R replay · Ctrl+Enter next")
        if task == ReviewTask.BOUNDARY: hint.setText(hint.text() + " · I start · O end")
        outer.addWidget(hint)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.save)
        QShortcut(QKeySequence("R"), self, activated=lambda: self.player.seek_to(self.current.start_ms if self.current else 0))
        if task == ReviewTask.ASR:
            QShortcut(QKeySequence("L"), self, activated=self._toggle_loop)
        if task == ReviewTask.BOUNDARY:
            QShortcut(QKeySequence("I"), self, activated=lambda: self._capture_boundary("manual_start_ms"))
            QShortcut(QKeySequence("O"), self, activated=lambda: self._capture_boundary("manual_end_ms"))
        for index in range(4):
            QShortcut(QKeySequence(str(index + 1)), self, activated=lambda current=index: self._shortcut(current))

    def _clear_choices(self) -> None:
        while self.choice_box.count():
            item = self.choice_box.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.choice_buttons = []

    def _add_choice(self, label: str, value: str, group: str = "choice") -> QPushButton:
        button = QPushButton(label); button.setCheckable(True); button.setMinimumHeight(42); button.setProperty("answer_group", group); button.setProperty("answer_value", value)
        button.clicked.connect(lambda checked, current=button: self._select(current, checked))
        self.choice_box.addWidget(button); self.choice_buttons.append(button); return button

    def _build_choices(self, sample: ReviewSample) -> None:
        self._clear_choices()
        if self.task == ReviewTask.BOUNDARY:
            for group, labels in (("start", ("Too Early", "Good", "Too Late")), ("end", ("Too Early", "Good", "Too Late")), ("length", ("Too Short", "Good", "Too Long"))):
                self.choice_box.addWidget(_muted(group.title()))
                row = QHBoxLayout()
                for label in labels:
                    value = label.lower().replace(" ", "_"); button = QPushButton(label); button.setCheckable(True); button.setProperty("answer_group", group); button.setProperty("answer_value", value); button.clicked.connect(lambda checked, current=button: self._select(current, checked)); row.addWidget(button); self.choice_buttons.append(button)
                self.choice_box.addLayout(row)
        elif self.task == ReviewTask.TRUSTED_SPEECH:
            self.choice_box.addWidget(_muted("Speaker"))
            for label, value in (("Correct", "correct"), ("Wrong", "wrong")):
                self._add_choice(label, value, "speaker")
            self.choice_box.addWidget(_muted("Transcript"))
            for label, value in (("Correct", "correct"), ("Wrong", "wrong")):
                self._add_choice(label, value, "transcript")
        elif self.task == ReviewTask.SUBTITLE:
            mode = str(sample.prompt.get("mode", "cue"))
            options = (("Good", "good"), ("Acceptable", "acceptable"), ("Bad", "bad")) if mode == "clip" else (("Good", "good"), ("Too Fast", "too_fast"), ("Bad Break", "bad_break"), ("Bad Translation", "bad_translation"))
            for label, value in options: self._add_choice(label, value)
        else:
            for label, value in CHOICES.get(self.task, ()): self._add_choice(label, value)

    def _build_more(self) -> None:
        if self.task == ReviewTask.TRANSLATION:
            for name in ("Accuracy", "Naturalness", "Tone"):
                combo = QComboBox(); combo.addItems(["—", "1", "2", "3", "4", "5"]); row = QHBoxLayout(); row.addWidget(QLabel(name)); row.addStretch(); row.addWidget(combo); self.more_layout.addLayout(row); self.more_fields[name.lower()] = combo
            for label in ("Wrong Meaning", "Too Literal", "Lost Joke", "Invented Joke", "Tone", "Profanity", "Pronoun", "Term", "Other"):
                box = QCheckBox(label); self.more_layout.addWidget(box); self.more_fields[f"flag_{label.lower().replace(' ', '_')}"] = box
        elif self.task == ReviewTask.BOUNDARY:
            for label in ("Setup enough", "Core complete", "Payoff complete", "Aftermath useful"):
                box = QCheckBox(label); self.more_layout.addWidget(box); self.more_fields[label.lower().replace(" ", "_")] = box
            combo = QComboBox(); combo.addItems(["—", "SHORT", "STANDARD", "LONG", "FULL_EVENT"]); self.more_layout.addWidget(combo); self.more_fields["preferred_profile"] = combo
        elif self.task == ReviewTask.WATCHABILITY:
            for label in ("Better Hook", "More Complete", "Better Ending", "Less Boring", "Better Pace", "More Relevant", "Better Reaction", "Other"):
                box = QCheckBox(label); self.more_layout.addWidget(box); self.more_fields[label.lower().replace(" ", "_")] = box
        elif self.task == ReviewTask.SUBTITLE:
            for label in ("Too Slow", "Too Many Words", "Blocks UI", "Sync Problem", "Needs Merge", "Needs Split"):
                box = QCheckBox(label); self.more_layout.addWidget(box); self.more_fields[label.lower().replace(" ", "_")] = box
        elif self.task == ReviewTask.PUBLISHABILITY:
            for name in ("Content", "Pacing", "ASR", "Translation", "Subtitle"):
                combo = QComboBox(); combo.addItems(["—", "1", "2", "3", "4", "5"]); row = QHBoxLayout(); row.addWidget(QLabel(name)); row.addStretch(); row.addWidget(combo); self.more_layout.addLayout(row); self.more_fields[f"rating_{name.lower()}"] = combo
            for label in ("Bad Event", "Bad Start", "Bad End", "Too Long", "Too Short", "ASR", "Translation", "Subtitle", "Duplicate", "Boring", "Missing Context", "Missing Payoff", "Other"):
                box = QCheckBox(label); self.more_layout.addWidget(box); self.more_fields[f"reject_{label.lower().replace(' ', '_')}"] = box
        elif self.task in {ReviewTask.ASR, ReviewTask.IDENTITY, ReviewTask.TRUSTED_SPEECH, ReviewTask.ADAPTIVE_ASR}:
            row = QHBoxLayout()
            row.addWidget(QLabel("Voice style changed?")); row.addStretch()
            combo = QComboBox(); combo.addItems(["—", "Yes", "No", "Unsure"])
            row.addWidget(combo); self.more_layout.addLayout(row)
            self.more_fields["voice_style_changed"] = combo
            self.more_layout.addWidget(_muted("Do not infer a nationality or accent; use the optional note for observable style changes only."))

    def _select(self, button: QPushButton, checked: bool) -> None:
        group = str(button.property("answer_group"))
        for other in self.choice_buttons:
            if other is not button and str(other.property("answer_group")) == group:
                other.setChecked(False)
        button.setChecked(checked)
        if self.task == ReviewTask.ASR:
            self.human_text.setStyleSheet("border-color:#f5b942" if button.property("answer_value") in ("minor", "wrong") else "")
        if self.task == ReviewTask.PUBLISHABILITY:
            self.more.setChecked(button.property("answer_value") == "reject")

    def _shortcut(self, index: int) -> None:
        if index < len(self.choice_buttons): self.choice_buttons[index].click()

    def _capture_boundary(self, key: str) -> None:
        if self.task != ReviewTask.BOUNDARY or not self.current:
            return
        value = int(self.player.player.position())
        self._manual_boundary[key] = value
        label = "start" if key == "manual_start_ms" else "end"
        self.saved.setText(f"Marked {label} · {value / 1000:.2f}s")

    def _details_payload(self, *, reveal: bool = False) -> dict[str, Any]:
        if not self.current:
            return {}
        payload: dict[str, Any] = {
            "sample_id": self.current.sample_id,
            "source": self.current.source_path,
        }
        is_blind = self.task in (ReviewTask.TRANSLATION, ReviewTask.WATCHABILITY, ReviewTask.ADAPTIVE_ASR)
        if not is_blind or reveal:
            payload.update(dict(self.current.private))
        elif self.current.consistency_control:
            payload["consistency_control"] = True
        return payload

    def _filters(self) -> None:
        menu = QMenu(self)
        for label, state in (("Remaining", "remaining"), ("Completed", "completed"), ("Skipped", "skipped"), ("Revisit", "revisit")):
            action = menu.addAction(label); action.triggered.connect(lambda _=False, value=state: self.load(value, creator=self.creator_filter, content_type=self.content_filter))
        creators, content_types = self.shell.repository.filter_values(self.task)
        if creators:
            creator_menu = menu.addMenu("Creator")
            creator_menu.addAction("All").triggered.connect(lambda _=False: self.load(self.queue_state, creator="", content_type=self.content_filter))
            for creator in creators:
                creator_menu.addAction(creator).triggered.connect(lambda _=False, value=creator: self.load(self.queue_state, creator=value, content_type=self.content_filter))
        if content_types:
            content_menu = menu.addMenu("Content Type")
            content_menu.addAction("All").triggered.connect(lambda _=False: self.load(self.queue_state, creator=self.creator_filter, content_type=""))
            for content_type in content_types:
                content_menu.addAction(content_type).triggered.connect(lambda _=False, value=content_type: self.load(self.queue_state, creator=self.creator_filter, content_type=value))
        menu.exec_(self.filter_button.mapToGlobal(self.filter_button.rect().bottomLeft()))

    def load(self, state: str = "remaining", *, sample_id: str | None = None, creator: str = "", content_type: str = "") -> None:
        self.queue_state = state; self.creator_filter = creator; self.content_filter = content_type
        self.items = self.shell.repository.samples(self.task, state=state, creator=creator, content_type=content_type)
        if self.task == ReviewTask.SUBTITLE and self.subtitle_mode:
            self.items = [item for item in self.items if str(item.prompt.get("mode", "cue")) == self.subtitle_mode]
        self.index = next((i for i, item in enumerate(self.items) if item.sample_id == sample_id), 0) if self.items else -1
        self.show_current()

    def _set_subtitle_mode(self, mode: str) -> None:
        self.subtitle_mode = "" if self.subtitle_mode == mode else mode
        self.cue_filter.setChecked(self.subtitle_mode == "cue"); self.clip_filter.setChecked(self.subtitle_mode == "clip")
        self.load(self.queue_state, creator=self.creator_filter, content_type=self.content_filter)

    def show_current(self, *, persist_state: bool = True) -> None:
        if self.index < 0 or self.index >= len(self.items):
            self.current = None; self.header.setText(f"{TASK_LABELS[self.task]} · Complete"); self.counter.setText("✓"); self.context.setText("No items in this queue."); self.player.load(""); self.save_next.setEnabled(False); return
        self.current = self.items[self.index]; self.save_next.setEnabled(True); self.saved.clear(); self._manual_boundary: dict[str, int] = {}
        if persist_state:
            self.shell.repository.set_state(self.task, self.current.sample_id)
        self.header.setText(f"{TASK_LABELS[self.task]} · {self.index + 1} / {len(self.items)}"); self.counter.setText(f"{self.current.creator} · {self.current.content_type}".strip(" ·"))
        self._build_choices(self.current); prompt = dict(self.current.prompt)
        if self.task == ReviewTask.TRANSLATION:
            body = f"SOURCE\n{prompt.get('source','')}\n\nCONTEXT\n{prompt.get('context','')}\n\nA\n{prompt.get('a','')}\n\nB\n{prompt.get('b','')}"
        elif self.task == ReviewTask.SUBTITLE:
            body = f"ENGLISH\n{prompt.get('english','')}\n\nCHINESE\n{prompt.get('chinese','')}" if prompt.get("mode") == "cue" else "Watch the full clip and judge subtitle readability."
        elif self.task == ReviewTask.ADAPTIVE_ASR:
            body = f"CONTEXT\n{prompt.get('context','')}\n\nA\n{prompt.get('a','')}\n\nB\n{prompt.get('b','')}"
        elif self.task == ReviewTask.IDENTITY:
            body = f"PREDICTED CREATOR\n{prompt.get('predicted_creator','Unknown')}\n\n{prompt.get('context','')}"
        elif self.task == ReviewTask.TRUSTED_SPEECH:
            body = f"PREDICTED SPEAKER\n{prompt.get('predicted_creator','Unknown')}\n\nTRANSCRIPT\n{prompt.get('transcript','')}\n\n{prompt.get('context','')}"
        else:
            body = str(prompt.get("context") or prompt.get("transcript") or prompt.get("summary") or prompt.get("current_asr") or "Watch or listen, then choose.")
        self.context.setText(body); self.details_text.setText(json.dumps(self._details_payload(), ensure_ascii=False, indent=2))
        self.play_b.setVisible(bool(self.current.media_b)); self.play_a.setText("Play A" if self.current.media_b else "Replay")
        media_exists = bool(self.current.media_a and Path(self.current.media_a).is_file())
        self.missing_media.setText("Missing Media · skip or relink this item" if not media_exists else "")
        self.missing_media.setVisible(not media_exists); self.relink.setVisible(not media_exists)
        self.player.load(self.current.media_a, position_ms=self.current.start_ms, autoplay=bool(self.shell.settings.get("auto_play", False)))
        self.player.player.setPlaybackRate(float(self.shell.settings.get("playback_speed", 1.0)))
        existing = self.shell.repository.annotation(self.current.sample_id)
        self.note.setPlainText(str((existing or {}).get("note", ""))); self.human_text.setPlainText(str((existing or {}).get("answer", {}).get("human_transcript", "")))
        if existing:
            answers = existing["answer"]
            for button in self.choice_buttons:
                if answers.get(str(button.property("answer_group"))) == button.property("answer_value"):
                    button.setChecked(True)

    def _load_pair(self, side: str) -> None:
        if not self.current: return
        path = self.current.media_b if side == "b" else self.current.media_a
        self.player.load(path, autoplay=True)

    def _relink_media(self) -> None:
        if not self.current:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Relink review media", "", "Media (*.mp4 *.mkv *.webm *.wav *.mp3);;All files (*)")
        if not path:
            return
        self.shell.repository.update_media(self.current.sample_id, path)
        self.current = self.shell.repository.sample(self.current.sample_id)
        self.show_current()

    def _toggle_loop(self) -> None:
        enabled = not bool(self.shell.settings.get("loop_asr", False))
        self.shell.settings["loop_asr"] = enabled; self.shell.repository.set_setting("loop_asr", enabled)
        self.saved.setText(f"Loop {'on' if enabled else 'off'}")

    def _media_status_changed(self, status: int) -> None:
        # QMediaPlayer.EndOfMedia is 7 in Qt 5; avoid importing multimedia in headless runs.
        if int(status) == 7 and self.task == ReviewTask.ASR and bool(self.shell.settings.get("loop_asr", False)):
            self.player.seek_to(self.current.start_ms if self.current else 0)
            play = getattr(self.player.player, "play", None)
            if play is not None:
                play()

    def _answer(self) -> dict[str, Any]:
        answer: dict[str, Any] = {}
        for button in self.choice_buttons:
            if button.isChecked(): answer[str(button.property("answer_group"))] = str(button.property("answer_value"))
        if self.task == ReviewTask.ASR and self.current:
            answer["human_transcript"] = self.human_text.toPlainText().strip(); answer["current_asr"] = str(self.current.prompt.get("current_asr", ""))
        elif self.task == ReviewTask.ADAPTIVE_ASR and self.current:
            answer["human_transcript"] = self.human_text.toPlainText().strip()
        elif self.task == ReviewTask.IDENTITY and self.current:
            answer["correct_creator_id"] = self.human_text.toPlainText().strip()
        details: dict[str, Any] = {}
        for key, widget in self.more_fields.items():
            if isinstance(widget, QCheckBox) and widget.isChecked(): details[key] = True
            elif isinstance(widget, QComboBox) and widget.currentIndex() > 0: details[key] = widget.currentText()
            elif isinstance(widget, QPlainTextEdit) and widget.toPlainText().strip(): details[key] = widget.toPlainText().strip()
        if details: answer["details"] = details
        if self.task == ReviewTask.BOUNDARY and self._manual_boundary:
            answer.update(self._manual_boundary)
        if self.task == ReviewTask.PUBLISHABILITY:
            answer["reject_reasons"] = [key.removeprefix("reject_") for key, widget in self.more_fields.items() if key.startswith("reject_") and isinstance(widget, QCheckBox) and widget.isChecked()]
        if self.task == ReviewTask.TRANSLATION:
            answer["flags"] = [key.removeprefix("flag_") for key, widget in self.more_fields.items() if key.startswith("flag_") and isinstance(widget, QCheckBox) and widget.isChecked()]
        return answer

    def save(self) -> None:
        if not self.current: return
        answer = self._answer()
        required = (("start", "end", "length") if self.task == ReviewTask.BOUNDARY else
                    ("speaker", "transcript") if self.task == ReviewTask.TRUSTED_SPEECH else ("choice",))
        if any(key not in answer for key in required):
            self.saved.setText("Choose an answer first"); self.saved.setProperty("state", "warning"); self.saved.style().polish(self.saved); return
        if self.task == ReviewTask.ASR and answer.get("choice") in ("minor", "wrong") and not answer.get("human_transcript"):
            self.saved.setText("Enter the human transcript"); return
        sample_id = self.current.sample_id
        auto_next = bool(self.shell.settings.get("auto_next", True))
        next_id = self.items[self.index + 1].sample_id if auto_next and self.index + 1 < len(self.items) else sample_id
        self.shell.repository.save(sample_id, answer, note=self.note.toPlainText().strip(), resume_sample_id=next_id)
        self._promote_creator_adaptive_human_truth(answer)
        self.saved.setText("Saved ✓"); self.shell.refresh_progress(); self.shell.mark_analysis_dirty()
        if bool(self.shell.settings.get("reveal_after_answer", False)):
            self.details_text.setText(json.dumps(self._details_payload(reveal=True), ensure_ascii=False, indent=2))
            self.details.setChecked(True)
        QTimer.singleShot(900, self.saved.clear)
        if auto_next: self._advance(persist_state=False)

    def _promote_creator_adaptive_human_truth(self, answer: dict[str, Any]) -> None:
        """Route human truth through canonical services; the GUI never writes domain tables."""
        if not self.current:
            return
        private = dict(self.current.private)
        recording_id = str(private.get("recording_id") or "")
        creator_id = str(private.get("creator_id") or "")
        if not recording_id:
            return
        try:
            if self.task in {ReviewTask.ASR, ReviewTask.ADAPTIVE_ASR} and answer.get("human_transcript") and creator_id:
                from acfv.creator_adaptive.models import IdentityState, TrustLevel
                from acfv.trusted_speech_memory import TrustedSpeechMemoryService
                TrustedSpeechMemoryService().store_unit(
                    creator_id=creator_id, recording_id=recording_id,
                    start_ms=self.current.start_ms, end_ms=self.current.end_ms,
                    audio_locator=self.current.media_a, raw_asr=str(answer["human_transcript"]), word_timestamps=[],
                    identity_state=IdentityState.CONFIRMED, speaker_identity_confidence=1.0,
                    visual_identity_confidence=1.0, asr_confidence=1.0, redecode_agreement=1.0,
                    requested_trust=TrustLevel.HUMAN_CONFIRMED,
                    provenance={"source": "HUMAN_REVIEW_LAB", "sample_id": self.current.sample_id},
                    profile_version=str(private.get("profile_version") or "creator_profile_v1"),
                    independent_evidence=("human",),
                )
            elif self.task == ReviewTask.IDENTITY and answer.get("choice") in {"correct", "wrong"}:
                selected = str(answer.get("correct_creator_id") or creator_id)
                if selected:
                    from acfv.creator_adaptive.models import IdentityObservation, IdentitySource
                    from acfv.creator_identity import CreatorIdentityService
                    CreatorIdentityService().record_observation(IdentityObservation(
                        recording_id=recording_id, start_ms=self.current.start_ms, end_ms=self.current.end_ms,
                        candidate_creator_id=selected, source=IdentitySource.HUMAN, confidence=1.0,
                        provider="human-review-lab", model_version="human-v1", evidence_ref=self.current.sample_id,
                    ))
            elif self.task == ReviewTask.TRUSTED_SPEECH:
                from acfv.trusted_speech_memory import TrustedSpeechMemoryService
                TrustedSpeechMemoryService().confirm_unit(
                    str(private.get("trusted_speech_unit_id") or ""),
                    speaker_correct=answer.get("speaker") == "correct",
                    transcript_correct=answer.get("transcript") == "correct",
                    review_sample_id=self.current.sample_id,
                )
        except Exception as exc:
            self.saved.setText(f"Review saved · adaptive memory pending ({type(exc).__name__})")

    def skip_current(self) -> None:
        if not self.current: return
        next_id = self.items[self.index + 1].sample_id if self.index + 1 < len(self.items) else self.current.sample_id
        self.shell.repository.save(self.current.sample_id, {}, status="skipped", note=self.note.toPlainText().strip(), resume_sample_id=next_id); self.shell.refresh_progress(); self.shell.mark_analysis_dirty(); self._advance(persist_state=False)

    def mark_revisit(self) -> None:
        if not self.current: return
        self.shell.repository.mark_revisit(self.current.sample_id, True); self.saved.setText("Added to Revisit ✓"); self.shell.refresh_progress()

    def _advance(self, *, persist_state: bool = True) -> None:
        if self.current:
            self.items = [item for item in self.items if item.sample_id != self.current.sample_id]
        if self.index >= len(self.items): self.index = max(0, len(self.items) - 1)
        self.show_current(persist_state=persist_state)

    def go_back(self) -> None:
        completed = self.shell.repository.samples(self.task, state="completed")
        if completed:
            self.items = completed; self.index = len(completed) - 1; self.show_current()


class AnalysisPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.setObjectName("ReviewAnalysis")
        layout = QVBoxLayout(self); layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Analysis"); title.setProperty("role", "pageTitle"); layout.addWidget(title)
        layout.addWidget(_muted("Current Human Data · automatically refreshed from saved annotations only."))
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True); self.content = QWidget(); self.box = QVBoxLayout(self.content); self.scroll.setWidget(self.content); layout.addWidget(self.scroll, 1)
        self.advanced = QGroupBox("Advanced Analysis"); self.advanced.setCheckable(True); self.advanced.setChecked(False); advanced_layout = QVBoxLayout(self.advanced); self.raw = QPlainTextEdit(); self.raw.setReadOnly(True); advanced_layout.addWidget(self.raw); layout.addWidget(self.advanced)

    def refresh(self, analysis: dict[str, Any]) -> None:
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for task, data in analysis.items():
            frame = _card(); layout = QVBoxLayout(frame); heading = QLabel(task.title()); heading.setProperty("role", "sectionTitle"); layout.addWidget(heading)
            layout.addWidget(_muted(f"{data.get('reviewed',0)} reviewed · {data.get('maturity','Not enough data')}"))
            summary = {key: value for key, value in data.items() if key not in ("reviewed", "maturity") and value not in (None, {}, [])}
            labels = data.get("labels", {})
            if labels:
                total = max(1, sum(int(value) for value in labels.values()))
                for label, value in labels.items():
                    row = QHBoxLayout(); row.addWidget(QLabel(str(label).replace("_", " ").title()))
                    bar = QProgressBar(); bar.setRange(0, total); bar.setValue(int(value)); bar.setFormat(f"{value} · {100 * int(value) / total:.0f}%"); bar.setTextVisible(True)
                    row.addWidget(bar, 1); layout.addLayout(row)
            compact = {key: value for key, value in summary.items() if key != "labels"}
            detail = QLabel(" · ".join(f"{key}: {value}" for key, value in compact.items()) or ("" if labels else "No statistics yet")); detail.setWordWrap(True); layout.addWidget(detail); self.box.addWidget(frame)
        self.box.addStretch(); self.raw.setPlainText(json.dumps(analysis, ensure_ascii=False, indent=2))


class HumanReviewWindow(QMainWindow):
    def __init__(self, repository: HumanReviewRepository, *, source_root: Path | None = None, output_root: Path | None = None) -> None:
        super().__init__(); self.repository = repository; self.source_root = source_root; self.output_root = Path(output_root or repository.db_path.parent / "exports")
        self.settings = {"playback_speed": 1.0, "auto_play": False, "auto_next": True, "loop_asr": False, "review_order": "High Information", "reveal_after_answer": False, **repository.settings()}
        self.executor = GuiExecutor(max_workers=2, parent=self); self.executor.result_ready.connect(self._result); self.executor.task_failed.connect(self._failure)
        self._analysis_dirty = True
        self._analysis_timer = QTimer(self); self._analysis_timer.setSingleShot(True); self._analysis_timer.setInterval(180); self._analysis_timer.timeout.connect(self.refresh_analysis)
        self.setWindowTitle("ACFV · Human Review Lab"); self.setObjectName("HumanReviewLab"); self.resize(1440, 900); self.setMinimumSize(1050, 650)
        root = QWidget(); self.setCentralWidget(root); main = QHBoxLayout(root); main.setContentsMargins(0, 0, 0, 0); main.setSpacing(0)
        side = QFrame(); self.side = side; side.setFixedWidth(210); side.setProperty("card", True); side_layout = QVBoxLayout(side); side_layout.setContentsMargins(12, 16, 12, 16)
        brand = QLabel("HUMAN REVIEW"); brand.setProperty("role", "sectionTitle"); side_layout.addWidget(brand)
        self.nav: dict[str, QPushButton] = {}
        self._add_nav(side_layout, "overview", "Overview", lambda: self.show_page("overview"))
        for task in TASK_ORDER: self._add_nav(side_layout, task.value, TASK_LABELS[task], lambda _=False, current=task: self.open_task(current))
        self._add_nav(side_layout, "analysis", "Analysis", lambda: self.show_page("analysis")); side_layout.addStretch(); main.addWidget(side)
        content = QVBoxLayout(); content.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout(); toolbar.setContentsMargins(20, 10, 20, 8); self.global_progress = QLabel("0 / 0"); toolbar.addStretch(); toolbar.addWidget(self.global_progress)
        self.menu_button = QToolButton(); self.menu_button.setText("⋯"); self.menu_button.setPopupMode(QToolButton.InstantPopup); self.menu_button.setMenu(self._menu()); toolbar.addWidget(self.menu_button); content.addLayout(toolbar)
        self.stack = QStackedWidget(); content.addWidget(self.stack, 1); wrapper = QWidget(); wrapper.setLayout(content); main.addWidget(wrapper, 1)
        self.pages: dict[str, QWidget] = {}
        self.overview = OverviewPage(self.continue_review, self.open_task, self.build_dataset); self.pages["overview"] = self.overview; self.stack.addWidget(self.overview)
        self.review_pages: dict[ReviewTask, ReviewPage] = {}
        for task in TASK_ORDER:
            page = ReviewPage(task, self); self.review_pages[task] = page; self.pages[task.value] = page; self.stack.addWidget(page)
        self.analysis_page = AnalysisPage(); self.pages["analysis"] = self.analysis_page; self.stack.addWidget(self.analysis_page)
        self.statusBar().showMessage("Ready"); self.refresh_progress(); self.refresh_analysis(); self.show_page("overview")

    def _add_nav(self, layout: QVBoxLayout, key: str, label: str, callback: Callable) -> None:
        button = QPushButton(label); button.setProperty("full_label", label); button.setCheckable(True); button.setProperty("nav", True); button.clicked.connect(lambda _checked=False: callback()); layout.addWidget(button); self.nav[key] = button

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        compact = event.size().width() < 1150
        self.side.setFixedWidth(150 if compact else 210)
        short = {"overview": "Overview", "watchability": "Watch", "publishability": "Publish", "analysis": "Analysis"}
        for key, button in self.nav.items():
            full = str(button.property("full_label"))
            progress = str(button.property("current_progress") or "")
            label = short.get(key, full) if compact else full
            button.setText(f"{label}{'  ' if compact else '    '}{progress}".rstrip())
        super().resizeEvent(event)

    def _menu(self) -> QMenu:
        menu = QMenu(self)
        for label, callback in (
            ("Export Results", self.export_results), ("Backup Annotations", self.backup), ("Dataset Info", self.dataset_info),
            ("Settings", self.open_settings), ("Open Review Folder", self.open_folder),
        ):
            action = QAction(label, self); action.triggered.connect(callback); menu.addAction(action)
        return menu

    def show_page(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        for name, button in self.nav.items(): button.setChecked(name == key)
        if key == "analysis" and self._analysis_dirty: self.refresh_analysis()

    def open_task(self, task: ReviewTask) -> None:
        self.show_page(task.value); self.review_pages[task].load("remaining")

    def continue_review(self) -> None:
        resume_task, resume_id = self.repository.resume_state()
        if resume_task and resume_id:
            remaining = self.repository.samples(resume_task, state="remaining")
            if any(item.sample_id == resume_id for item in remaining):
                self.show_page(resume_task.value); self.review_pages[resume_task].load("remaining", sample_id=resume_id); return
        for item in self.repository.progress():
            if item.completed + item.skipped < item.total:
                self.open_task(item.task); return

    def refresh_progress(self) -> None:
        progress = self.repository.progress(); self.overview.refresh(progress)
        total = sum(item.total for item in progress); done = sum(item.completed for item in progress); self.global_progress.setText(f"{done} / {total}")
        for item in progress:
            value = "✓" if item.total and item.completed >= item.total else f"{item.completed} / {item.total}"
            self.nav[item.task.value].setProperty("current_progress", value)
            self.nav[item.task.value].setText(f"{TASK_LABELS[item.task]}    {value}")

    def refresh_analysis(self) -> None:
        self.analysis_page.refresh(HumanReviewAnalysis(self.repository).calculate())
        self._analysis_dirty = False

    def mark_analysis_dirty(self) -> None:
        self._analysis_dirty = True
        if self.stack.currentWidget() is self.analysis_page:
            self._analysis_timer.start()

    def build_dataset(self) -> None:
        self.statusBar().showMessage("Preparing review dataset…"); self.executor.submit("dataset", lambda: HumanReviewDatasetBuilder(self.source_root).build())

    def _result(self, token: RequestToken, value: Any) -> None:
        if token.channel == "dataset" and isinstance(value, DatasetBuildResult):
            count = self.repository.merge_dataset(value.samples, value.metadata); self.refresh_progress(); self.refresh_analysis(); self.statusBar().showMessage(f"Dataset v4 ready · {count} samples merged", 5000)

    def _failure(self, token: RequestToken, message: str, details: str) -> None:
        self.statusBar().showMessage("Operation failed"); QMessageBox.critical(self, "Human Review", f"{message}\n\n{details[-1200:]}")

    def export_results(self) -> None:
        try:
            paths = HumanReviewExporter(self.repository).export(self.output_root); self.statusBar().showMessage(f"Exported · {paths['folder']}", 7000)
        except Exception as exc: QMessageBox.critical(self, "Export failed", str(exc))

    def backup(self) -> None:
        try: self.statusBar().showMessage(f"Backup created · {self.repository.backup()}", 7000)
        except Exception as exc: QMessageBox.critical(self, "Backup failed", str(exc))

    def dataset_info(self) -> None:
        QMessageBox.information(self, "Dataset Info", json.dumps(self.repository.dataset_metadata(), ensure_ascii=False, indent=2))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_() == QDialog.Accepted:
            self.settings.update(dialog.result_values())
            for key, value in self.settings.items(): self.repository.set_setting(key, value)

    def open_folder(self) -> None:
        self.repository.db_path.parent.mkdir(parents=True, exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.repository.db_path.parent)))

    def closeEvent(self, event) -> None:  # noqa: N802
        for page in self.review_pages.values(): page.player.stop()
        self.executor.shutdown(wait=False)
        try: self.repository.close()
        except Exception: pass
        event.accept()


def default_review_root() -> Path:
    configured = os.environ.get("ACFV_HUMAN_REVIEW_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else (storage_root() / "human_review").resolve()


def launch_review_lab(*, test_db: bool = False, source_root: Path | None = None, output_root: Path | None = None) -> int:
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("ACFV Human Review Lab"); application.setStyleSheet(review_stylesheet())
    root = default_review_root(); root.mkdir(parents=True, exist_ok=True)
    db_name = "human_review_test.sqlite" if test_db else "human_review.sqlite"
    repository = HumanReviewRepository(root / db_name, backup_dir=root / "backups")
    window = HumanReviewWindow(repository, source_root=source_root, output_root=output_root or root / "exports")
    window.show(); return application.exec_()


__all__ = ["HumanReviewWindow", "ReviewPage", "AnalysisPage", "launch_review_lab", "review_stylesheet"]
