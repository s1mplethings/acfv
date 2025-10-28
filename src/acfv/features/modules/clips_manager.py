"""Three-level clips browser (video → run → clip) with thumbnails."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from acfv.runtime.storage import resolve_clips_base_dir, storage_root, processing_path
from acfv.ui import build_section_header, card_frame_style, wrap_in_card
from acfv.utils import extract_time_from_clip_filename

__all__ = ["create_clips_manager"]

SUPPORTED_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
ALL_VIDEOS = "__ALL_VIDEOS__"


def _open_path(target: Path | str) -> None:
    """Open files/folders in the platform file explorer."""
    try:
        path = Path(target).expanduser()
    except Exception:
        logging.warning("[clips_manager] invalid path payload: %s", target)
        return

    if not path.exists():
        logging.warning("[clips_manager] path not found: %s", path)
        return

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as exc:  # noqa: BLE001
        logging.warning("[clips_manager] failed to open %s: %s", path, exc)


@dataclass
class ClipEntry:
    path: Path
    size_bytes: int
    duration: Optional[float]

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class RunEntry:
    name: str
    path: Path
    clips: List[ClipEntry]
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


@dataclass
class VideoEntry:
    name: str
    path: Path
    runs: List[RunEntry]
    flat_clips: List[ClipEntry]


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_duration(value: Optional[float]) -> str:
    if not value:
        return "--"
    minutes, seconds = divmod(int(value), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class ClipsManager:
    """PyQt facade shown inside the main window."""

    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        self.config_manager = config_manager

        self.clip_list: Optional[QListWidget] = None
        self.status_label: Optional[QLabel] = None
        self.video_combo: Optional[QComboBox] = None
        self.run_combo: Optional[QComboBox] = None
        self.open_button: Optional[QPushButton] = None
        self.open_folder_button: Optional[QPushButton] = None

        self.rate_button: Optional[QPushButton] = None
        self.rating_spin: Optional[QSpinBox] = None
        self.rating_notes: Optional[QTextEdit] = None

        self._base_dir: Path = resolve_clips_base_dir(config_manager, ensure=True)
        self._inventory: List[VideoEntry] = []

        self._thumb_cache_dir = processing_path("thumbnails") / "clip_covers"
        self._thumb_cache_dir.mkdir(parents=True, exist_ok=True)
        self._list_icon_size = QSize(240, 135)
        self._accent_color = self._resolve_accent_color()
        self._file_icon = self._build_file_icon()

        self._current_run_meta: Optional[Path] = None
        self._current_run_output: Optional[Path] = None
        self._selected_video_name: Optional[str] = None
        self._selected_run_name: Optional[str] = None
        self._rag_db = None
        self._rag_db_disabled = False

        self._hydrate_recent_run()

    # ------------------------------------------------------------------ UI assembly

    def init_ui(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        container.setStyleSheet(card_frame_style())
        header = build_section_header("切片浏览", "浏览、打开并评分生成的剪辑")
        layout.addWidget(header)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)

        lbl_video = QLabel("视频")
        self.video_combo = QComboBox()
        self.video_combo.currentIndexChanged.connect(self._on_video_changed)
        controls_row.addWidget(lbl_video)
        controls_row.addWidget(self.video_combo, 1)

        lbl_run = QLabel("Run")
        self.run_combo = QComboBox()
        self.run_combo.currentIndexChanged.connect(self._on_run_changed)
        controls_row.addWidget(lbl_run)
        controls_row.addWidget(self.run_combo, 1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_clips)
        controls_row.addWidget(refresh_btn)
        controls_row.addStretch(1)

        layout.addLayout(controls_row)

        self.clip_list = QListWidget(container)
        self.clip_list.setViewMode(QListWidget.ListMode)
        self.clip_list.setSelectionMode(QListWidget.SingleSelection)
        self.clip_list.setIconSize(self._list_icon_size)
        self.clip_list.setWordWrap(True)
        self.clip_list.setSpacing(8)
        self.clip_list.setMovement(QListWidget.Static)
        self.clip_list.setUniformItemSizes(False)
        self.clip_list.currentItemChanged.connect(self._on_clip_changed)
        self.clip_list.itemDoubleClicked.connect(self._on_clip_double_clicked)
        layout.addWidget(self.clip_list, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self.status_label = QLabel("选择左侧切片查看操作")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #5E5E5E;")
        status_row.addWidget(self.status_label, 1)

        self.open_button = QPushButton("打开切片")
        self.open_button.clicked.connect(self._open_selected_clip)
        self.open_button.setEnabled(False)
        status_row.addWidget(self.open_button)

        self.open_folder_button = QPushButton("打开所在文件夹")
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        self.open_folder_button.setEnabled(False)
        status_row.addWidget(self.open_folder_button)

        status_widget = QWidget()
        status_widget.setLayout(status_row)
        layout.addWidget(wrap_in_card(status_widget))

        rating_panel = QWidget()
        rating_layout = QVBoxLayout(rating_panel)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.setSpacing(4)

        rating_controls = QHBoxLayout()
        rating_controls.setSpacing(8)

        rating_controls.addWidget(QLabel("评分 (1-5)"))
        self.rating_spin = QSpinBox()
        self.rating_spin.setRange(1, 5)
        self.rating_spin.setValue(5)
        rating_controls.addWidget(self.rating_spin)

        self.rate_button = QPushButton("保存评分并写入 RAG")
        self.rate_button.clicked.connect(self._rate_selected_clip)
        self.rate_button.setEnabled(False)
        rating_controls.addWidget(self.rate_button, 1)

        rating_layout.addLayout(rating_controls)

        self.rating_notes = QTextEdit()
        self.rating_notes.setPlaceholderText("可选：记录亮点或重写文本（将写入评分记录/RAG）")
        self.rating_notes.setFixedHeight(80)
        rating_layout.addWidget(self.rating_notes)

        layout.addWidget(wrap_in_card(rating_panel))

        QTimer.singleShot(0, self.refresh_clips)

    # ------------------------------------------------------------------ public API used by pipeline

    def record_run_start(self, video_slug: str, run_dir: Path) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "video": video_slug,
            "run_dir": str(run_dir),
            "run_id": run_dir.name,
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        meta_path = run_dir / "run.json"
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] failed to write run metadata: %s", exc)
        self._current_run_output = run_dir / "output_clips"
        self._current_run_meta = meta_path
        return meta_path

    def finalize_run(
        self,
        meta_path: Optional[Path],
        success: bool,
        clip_paths: Optional[List[str]] = None,
    ) -> None:
        clip_path_objs: List[Path] = []
        if clip_paths:
            clip_path_objs = [Path(p) for p in clip_paths if p]
        target_run_dir: Optional[Path] = None
        try:
            if meta_path:
                target_run_dir = meta_path.parent
                meta: dict = {}
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except Exception:
                        meta = {}
                meta["status"] = "success" if success else "failed"
                meta["finished_at"] = datetime.now().isoformat(timespec="seconds")
                if clip_paths is not None:
                    meta["clip_count"] = len(clip_paths)
                    meta["clips"] = clip_paths
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] failed to update run metadata: %s", exc)
        finally:
            try:
                if target_run_dir is None and clip_path_objs:
                    candidate = clip_path_objs[0]
                    try:
                        candidate = candidate.resolve()
                    except Exception:
                        candidate = candidate.absolute()
                    if candidate.parent.name == "output_clips":
                        target_run_dir = candidate.parent.parent
                    else:
                        target_run_dir = candidate.parent
                self._sync_flattened_clips(target_run_dir, clip_path_objs)
            except Exception as exc:
                logging.debug("[clips_manager] failed to sync flattened clips: %s", exc)
            self._current_run_meta = None
            self.refresh_clips()

    def _save_rating(self, clip_path: str, data: dict) -> None:
        try:
            clip = Path(clip_path)
            if not clip.exists():
                return
            rating_file = clip.with_suffix(clip.suffix + ".rating.json")
            rating_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] failed to write rating data: %s", exc)

    # ------------------------------------------------------------------ refresh / data collection

    def refresh_clips(self) -> None:
        previous_video = self._selected_video_name
        previous_run = self._selected_run_name
        previous_clip_path = None
        payload = self._selected_payload()
        if payload and payload.get("clip"):
            previous_clip_path = str(payload["clip"].path)

        self._base_dir = resolve_clips_base_dir(self.config_manager, ensure=True)
        self._inventory = self._collect_inventory(self._base_dir)
        self._rebuild_selectors(previous_video, previous_run, previous_clip_path)

    def _collect_inventory(self, base_dir: Path) -> List[VideoEntry]:
        videos: List[VideoEntry] = []
        if not base_dir.exists():
            return videos
        for video_dir in sorted([p for p in base_dir.iterdir() if p.is_dir()]):
            runs: List[RunEntry] = []
            runs_dir = video_dir / "runs"
            if runs_dir.is_dir():
                for run_dir in sorted([p for p in runs_dir.iterdir() if p.is_dir()]):
                    clips = self._gather_clips(run_dir / "output_clips")
                    status, started, finished = self._load_run_meta(run_dir / "run.json")
                    runs.append(
                        RunEntry(
                            name=run_dir.name,
                            path=run_dir,
                            clips=clips,
                            status=status,
                            started_at=started,
                            finished_at=finished,
                        )
                    )
            flat_clips = self._gather_clips(video_dir)
            videos.append(VideoEntry(name=video_dir.name, path=video_dir, runs=runs, flat_clips=flat_clips))
        return videos

    def _gather_clips(self, directory: Path) -> List[ClipEntry]:
        clips: List[ClipEntry] = []
        if not directory.is_dir():
            return clips
        for clip_path in sorted(directory.iterdir()):
            if clip_path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            try:
                stat = clip_path.stat()
            except OSError:
                continue
            clips.append(
                ClipEntry(
                    path=clip_path,
                    size_bytes=stat.st_size,
                    duration=self._probe_duration(clip_path),
                )
            )
        return clips

    # ------------------------------------------------------------------ navigation helpers

    def _rebuild_selectors(
        self,
        preferred_video: Optional[str],
        preferred_run: Optional[str],
        preferred_clip_path: Optional[str],
    ) -> None:
        if (
            self.video_combo is None
            or self.run_combo is None
            or self.clip_list is None
        ):
            return

        video_names = [video.name for video in self._inventory]

        self.video_combo.blockSignals(True)
        self.video_combo.clear()

        if not video_names:
            self.video_combo.addItem("暂无视频", None)
            self.video_combo.setEnabled(False)
            self.run_combo.blockSignals(True)
            self.run_combo.clear()
            self.run_combo.addItem("无可用 run", None)
            self.run_combo.setEnabled(False)
            self.run_combo.blockSignals(False)
            self._selected_video_name = None
            self._selected_run_name = None
            if self.clip_list is not None:
                self.clip_list.clear()
            self._update_selection_display(None)
            self.video_combo.blockSignals(False)
            return

        available_ids = [ALL_VIDEOS] + video_names

        self.video_combo.setEnabled(True)
        self.run_combo.setEnabled(True)

        self.video_combo.addItem("全部视频", ALL_VIDEOS)
        for video in self._inventory:
            self.video_combo.addItem(video.name, video.name)

        if preferred_video in available_ids:
            target_video = preferred_video
        elif self._selected_video_name in available_ids:
            target_video = self._selected_video_name
        else:
            target_video = video_names[0]

        self._selected_video_name = target_video

        video_index = self.video_combo.findData(target_video)
        if video_index < 0:
            video_index = 0
        self.video_combo.setCurrentIndex(video_index)
        self.video_combo.blockSignals(False)

        self._populate_run_combo(preferred_run)
        self._populate_clip_list(preferred_clip_path)

    def _resolve_video(self, name: Optional[str]) -> Optional[VideoEntry]:
        if not name:
            return None
        for video in self._inventory:
            if video.name == name:
                return video
        return None

    def _resolve_run(self, video: VideoEntry, name: Optional[str]) -> Optional[RunEntry]:
        if not name:
            return None
        for run in video.runs:
            if run.name == name:
                return run
        return None

    def _current_video(self) -> Optional[VideoEntry]:
        if not self._selected_video_name or self._selected_video_name == ALL_VIDEOS:
            return None
        return self._resolve_video(self._selected_video_name)

    def _current_run(self, video: Optional[VideoEntry]) -> Optional[RunEntry]:
        if not (video and self._selected_run_name):
            return None
        return self._resolve_run(video, self._selected_run_name)

    def _populate_run_combo(self, preferred_run: Optional[str]) -> None:
        if self.run_combo is None:
            return

        video = self._current_video()
        self.run_combo.blockSignals(True)
        self.run_combo.clear()

        if self._selected_video_name == ALL_VIDEOS:
            self.run_combo.addItem("全部剪辑", None)
            self.run_combo.setCurrentIndex(0)
            self._selected_run_name = None
            self.run_combo.setEnabled(False)
            self.run_combo.blockSignals(False)
            return

        self.run_combo.setEnabled(True)

        if not video:
            self.run_combo.addItem("无可用 run", None)
            self.run_combo.setCurrentIndex(0)
            self._selected_run_name = None
            self.run_combo.blockSignals(False)
            return

        self.run_combo.addItem("全部切片", None)
        for run in video.runs:
            label = run.name
            if run.status and run.status not in {"success", ""}:
                label = f"{run.name} ({run.status})"
            self.run_combo.addItem(label, run.name)

        if preferred_run and any(run.name == preferred_run for run in video.runs):
            target_run = preferred_run
        else:
            target_run = None

        run_index = self.run_combo.findData(target_run)
        if run_index < 0:
            run_index = 0
        self.run_combo.setCurrentIndex(run_index)
        self._selected_run_name = self.run_combo.itemData(run_index)
        self.run_combo.blockSignals(False)

    def _make_clip_item(self, video: VideoEntry, run: Optional[RunEntry], clip: ClipEntry) -> QListWidgetItem:
        icon = self._icon_for_clip(video, run, clip)
        owner = run.name if run else "视频根目录"
        label = (
            f"{clip.name}\n"
            f"{video.name} · {owner}\n"
            f"{_format_size(clip.size_bytes)} · {_format_duration(clip.duration)}"
        )
        item = QListWidgetItem(icon, label)
        item.setData(Qt.UserRole, {"type": "clip", "video": video, "run": run, "clip": clip})
        item.setToolTip(str(clip.path))
        item.setSizeHint(QSize(self._list_icon_size.width() + 120, self._list_icon_size.height() + 16))
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        return item

    # ------------------------------------------------------------------ selection helpers

    def _selected_payload(self) -> Optional[dict]:
        if self.clip_list is None:
            return None
        item = self.clip_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole) or {}

    # ------------------------------------------------------------------ slots

    def _on_video_changed(self, index: int) -> None:
        if self.video_combo is None:
            return
        self._selected_video_name = self.video_combo.itemData(index)
        self._populate_run_combo(None)
        self._populate_clip_list(None)

    def _on_run_changed(self, index: int) -> None:
        if self.run_combo is None:
            return
        self._selected_run_name = self.run_combo.itemData(index)
        self._populate_clip_list(None)

    def _on_clip_changed(self, current: Optional[QListWidgetItem], _: Optional[QListWidgetItem]) -> None:
        self._update_selection_display(current)

    def _on_clip_double_clicked(self, _: QListWidgetItem) -> None:
        self._open_selected_clip()

    def _populate_clip_list(self, preferred_clip_path: Optional[str]) -> None:
        if self.clip_list is None:
            return

        all_videos_mode = self._selected_video_name == ALL_VIDEOS
        video = self._current_video()
        run = self._current_run(video)

        clip_rows: List[tuple[VideoEntry, Optional[RunEntry], ClipEntry, float]] = []

        def _push(entry_video: VideoEntry, entry_run: Optional[RunEntry], clip_entry: ClipEntry) -> None:
            try:
                mtime = clip_entry.path.stat().st_mtime
            except OSError:
                mtime = 0.0
            clip_rows.append((entry_video, entry_run, clip_entry, mtime))

        if all_videos_mode:
            for v in self._inventory:
                for r in v.runs:
                    for clip in r.clips:
                        _push(v, r, clip)
                for clip in v.flat_clips:
                    _push(v, None, clip)
        elif video:
            if run:
                for clip in run.clips:
                    _push(video, run, clip)
            else:
                for r in video.runs:
                    for clip in r.clips:
                        _push(video, r, clip)
                for clip in video.flat_clips:
                    _push(video, None, clip)

        self.clip_list.blockSignals(True)
        self.clip_list.clear()

        target_row = -1
        clip_rows.sort(key=lambda row: row[3], reverse=True)

        for idx, (row_video, row_run, row_clip, _) in enumerate(clip_rows):
            item = self._make_clip_item(row_video, row_run, row_clip)
            self.clip_list.addItem(item)
            if preferred_clip_path and str(row_clip.path) == preferred_clip_path:
                target_row = idx

        self.clip_list.blockSignals(False)

        if clip_rows:
            if target_row < 0:
                target_row = 0
            self.clip_list.setCurrentRow(target_row)
            current_item = self.clip_list.item(target_row)
            self._update_selection_display(current_item)
        else:
            self._update_selection_display(None)

    def _open_selected_folder(self) -> None:
        payload = self._selected_payload()
        if not payload:
            return
        p_type = payload.get("type")
        if p_type == "clip":
            clip_path = payload["clip"].path
            _open_path(clip_path.parent)

    def _open_selected_clip(self) -> None:
        payload = self._selected_payload()
        if payload and payload.get("clip"):
            _open_path(payload["clip"].path)

    def _update_selection_display(self, item: Optional[QListWidgetItem]) -> None:
        clip = None
        video = None
        run = None
        if item:
            payload = item.data(Qt.UserRole) or {}
            clip = payload.get("clip")
            video = payload.get("video")
            run = payload.get("run")

        if self.status_label is not None:
            if clip and video:
                owner = run.name if run else "视频根目录"
                info_text = f"{clip.name} - {owner} - {_format_duration(clip.duration)}"
                self.status_label.setText(info_text)
                self.status_label.setToolTip(str(clip.path))
            else:
                self.status_label.setText("选择左侧切片查看操作")
                self.status_label.setToolTip("")

        enabled = bool(clip)
        if self.open_button is not None:
            self.open_button.setEnabled(enabled)
        if self.open_folder_button is not None:
            self.open_folder_button.setEnabled(enabled)
        if self.rate_button is not None:
            self.rate_button.setEnabled(enabled)

    # ------------------------------------------------------------------ thumbnails & metadata

    def _icon_for_clip(self, video: VideoEntry, run: Optional[RunEntry], clip: ClipEntry) -> QIcon:
        thumb = self._ensure_thumbnail(video, run, clip)
        if thumb and thumb.exists():
            pix = QPixmap(str(thumb)).scaled(
                self._list_icon_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            if not pix.isNull():
                return QIcon(pix)
        return self._file_icon

    def _ensure_thumbnail(self, video: VideoEntry, run: Optional[RunEntry], clip: ClipEntry) -> Optional[Path]:
        safe_parts = [self._sanitize(video.name)]
        if run:
            safe_parts.append(self._sanitize(run.name))
        cache_dir = self._thumb_cache_dir.joinpath(*safe_parts)
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{clip.path.stem}.jpg"
        try:
            clip_mtime = clip.path.stat().st_mtime
        except OSError:
            return None
        if target.exists():
            try:
                if target.stat().st_mtime >= clip_mtime:
                    return target
            except OSError:
                pass

        frame_time = 1.0
        if clip.duration and clip.duration > 2:
            frame_time = min(max(clip.duration * 0.25, 1.0), clip.duration - 1.0)

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(frame_time),
            "-i",
            str(clip.path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-1",
            str(target),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0 and target.exists():
                os.utime(target, (clip_mtime, clip_mtime))
                return target
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] failed to generate thumbnail: %s", exc)
        return None

    def _probe_duration(self, clip_path: Path) -> Optional[float]:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(clip_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            logging.debug("[clips_manager] failed to probe duration for %s", clip_path)
        return None

    def _load_run_meta(self, meta_path: Path) -> tuple[str, Optional[datetime], Optional[datetime]]:
        status = "unknown"
        started = finished = None
        if not meta_path.exists():
            return status, started, finished
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            status = data.get("status", status)
            started_val = data.get("started_at")
            finished_val = data.get("finished_at")
            if started_val:
                try:
                    started = datetime.fromisoformat(str(started_val))
                except Exception:
                    started = None
            if finished_val:
                try:
                    finished = datetime.fromisoformat(str(finished_val))
                except Exception:
                    finished = None
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] failed to read run metadata: %s", exc)
        return status, started, finished

        # ------------------------------------------------------------------ misc helpers

    def _hydrate_recent_run(self) -> None:
        try:
            output_dir = self.config_manager.get("OUTPUT_CLIPS_DIR")
        except Exception:
            output_dir = None
        if not output_dir:
            return
        candidate = Path(str(output_dir)).expanduser()
        if not candidate.is_absolute():
            candidate = (storage_root().parent / candidate).resolve()
        if not candidate.exists():
            return
        self._current_run_output = candidate
        meta_path = candidate.parent / "run.json"
        if meta_path.exists():
            self._current_run_meta = meta_path

    def _sanitize(self, text: str) -> str:
        cleaned = text.strip().replace(os.sep, "_")
        return cleaned or "video"

    def _build_file_icon(self) -> QIcon:
        width = self._list_icon_size.width()
        height = self._list_icon_size.height()
        pix = QPixmap(width, height)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        accent_color = self._accent_color if isinstance(self._accent_color, QColor) else None
        if accent_color is None or not accent_color.isValid():
            accent_color = QColor("#5DADE2")
        painter.setBrush(accent_color)
        paper_x = int(width * 0.15)
        paper_width = width - paper_x * 2
        painter.drawRoundedRect(paper_x, int(height * 0.05), paper_width, int(height * 0.9), 18, 18)

        painter.setBrush(QColor("#FFFFFF"))
        line_height = max(6, int(height * 0.07))
        top_y = int(height * 0.32)
        gap = max(6, int(height * 0.05))
        line_width = paper_width - int(width * 0.1)
        line_x = paper_x + int(width * 0.05)
        for offset in range(3):
            current_width = line_width if offset < 2 else int(line_width * 0.7)
            painter.drawRect(line_x, top_y + offset * (line_height + gap), current_width, line_height)
        painter.end()
        return QIcon(pix)

    def _resolve_accent_color(self) -> QColor:
        default_hex = "#5DADE2"
        try:
            configured = self.config_manager.get("CLIPS_ICON_ACCENT_COLOR")
        except Exception:
            configured = None
        if configured:
            candidate = QColor(str(configured))
            if candidate.isValid():
                return candidate
            logging.warning("[clips_manager] 无法解析 CLIPS_ICON_ACCENT_COLOR: %s", configured)
        return QColor(default_hex)

    # ------------------------------------------------------------------ rating helpers

    def _rate_selected_clip(self) -> None:
        payload = self._selected_payload()
        if not payload or not payload.get("clip"):
            QMessageBox.warning(self.main_window, "评分失败", "请先选择一个切片。")
            return

        clip_entry: ClipEntry = payload["clip"]
        video_entry: Optional[VideoEntry] = payload.get("video")
        run_entry: Optional[RunEntry] = payload.get("run")

        rating_value = int(self.rating_spin.value() if self.rating_spin else 5)
        notes_text = self.rating_notes.toPlainText().strip() if self.rating_notes else ""

        metadata = self._extract_clip_metadata(clip_entry, video_entry, run_entry)
        transcript = metadata.get("text") or notes_text or clip_entry.name

        feedback = {
            "clip_path": str(clip_entry.path),
            "video_name": metadata.get("video_name"),
            "start": metadata.get("start"),
            "end": metadata.get("end"),
            "rating": rating_value,
            "notes": notes_text,
            "text": transcript,
            "source": "manual",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }

        self._save_rating(str(clip_entry.path), feedback)
        self._append_manual_rating_log(clip_entry, feedback, run_entry)

        rag_updated = False
        rag_db = self._ensure_rag_db()
        if rag_db:
            try:
                start_val = metadata.get("start")
                end_val = metadata.get("end")
                rag_db.add_liked_clip_vector(
                    clip_path=str(clip_entry.path),
                    transcript_text=transcript,
                    video_name=metadata.get("video_name") or "",
                    clip_start_time=float(start_val) if start_val is not None else 0.0,
                    clip_end_time=float(end_val) if end_val is not None else 0.0,
                    user_rating=rating_value,
                )
                rag_db.ensure_embeddings()
                rag_updated = True
            except Exception as exc:  # noqa: BLE001
                logging.warning("[clips_manager] 写入RAG失败: %s", exc)

        if self.rating_notes:
            self.rating_notes.clear()

        msg = "评分已保存"
        if rag_updated:
            msg += "，RAG 已更新。"
        QMessageBox.information(self.main_window, "评分完成", msg)

    def _extract_clip_metadata(
        self,
        clip: ClipEntry,
        video: Optional[VideoEntry],
        run: Optional[RunEntry],
    ) -> dict:
        info = {
            "video_name": video.name if video else "",
            "start": None,
            "end": None,
            "text": "",
        }
        start, end = extract_time_from_clip_filename(clip.name)
        if start is not None:
            info["start"] = start
        if end is not None:
            info["end"] = end

        candidates = []
        if run:
            candidates.append(run.path / "data" / "ratings.json")
        if clip.path.parent.name == "output_clips":
            candidates.append(clip.path.parent.parent / "data" / "ratings.json")
        if video:
            candidates.append(video.path / "data" / "ratings.json")
        candidates.extend(
            [
                clip.path.parent / "ratings.json",
                clip.path.parent.parent / "ratings.json" if clip.path.parent.parent else None,
            ]
        )

        seen = set()
        for candidate in candidates:
            if not candidate:
                continue
            candidate = Path(candidate)
            if candidate in seen or not candidate.exists():
                continue
            seen.add(candidate)
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            entry = payload.get(clip.name)
            if isinstance(entry, dict):
                info["text"] = entry.get("text") or info["text"]
                info["start"] = entry.get("start", info["start"])
                info["end"] = entry.get("end", info["end"])
                break
        return info

    def _append_manual_rating_log(
        self,
        clip: ClipEntry,
        record: dict,
        run: Optional[RunEntry],
    ) -> None:
        log_dir = None
        if run:
            log_dir = run.path / "data"
        elif clip.path.parent.name == "output_clips":
            log_dir = clip.path.parent.parent / "data"
        else:
            log_dir = clip.path.parent
        if not log_dir:
            return
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "acfv_ratings.jsonl"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] 追加评分日志失败: %s", exc)

    def _ensure_rag_db(self):
        if self._rag_db_disabled:
            return None
        if self._rag_db is None:
            try:
                from acfv.rag_vector_database import RAGVectorDatabase
            except Exception as exc:  # noqa: BLE001
                logging.warning("[clips_manager] 无法导入RAG数据库: %s", exc)
                self._rag_db_disabled = True
                return None
            rag_path = self.config_manager.get("RAG_DB_PATH")
            if not rag_path:
                rag_path = str(processing_path("rag_database.json"))
                self.config_manager.set("RAG_DB_PATH", rag_path, persist=True)
            rag_path = os.path.abspath(str(rag_path))
            os.makedirs(os.path.dirname(rag_path), exist_ok=True)
            try:
                self._rag_db = RAGVectorDatabase(database_path=rag_path)
            except Exception as exc:  # noqa: BLE001
                logging.warning("[clips_manager] 初始化RAG数据库失败: %s", exc)
                self._rag_db_disabled = True
                return None
        return self._rag_db

def create_clips_manager(main_window, config_manager) -> ClipsManager:
    """Factory used by the GUI bootstrapper."""
    return ClipsManager(main_window, config_manager)
