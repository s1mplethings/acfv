"""Simplified clips manager facade.

The legacy GUI expects a ``create_clips_manager`` factory returning an object
with ``init_ui`` and (optionally) ``_lazy_load_data``.  The full-featured
implementation from the old interest_rating project has not been migrated yet,
so we provide a light‑weight drop-in that can list generated clips and open the
output directory.  Once the richer manager lands, this module can forward to it.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
import json
import time

from PyQt5.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acfv.runtime.storage import processing_path

__all__ = ["create_clips_manager"]


class _BasicClipsManager:
    """Minimal clips manager to keep the GUI functional."""

    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        self.config_manager = config_manager
        self._list: QListWidget | None = None
        # Internal directories / widgets
        self._output_dir = None  # type: Path | None
        self._runs_dir = None  # type: Path | None
        self._refresh_button = None  # type: QPushButton | None

    def init_ui(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)

        layout.addWidget(QLabel("剪辑结果（按视频汇总）"))
        self._list = QListWidget()
        layout.addWidget(self._list)

        # 操作按钮行
        btn_open = QPushButton("打开输出目录")
        btn_open.clicked.connect(self._open_folder)  # type: ignore[attr-defined]
        layout.addWidget(btn_open)

        self._refresh_button = QPushButton("刷新")
        self._refresh_button.clicked.connect(self._lazy_load_data)  # type: ignore[attr-defined]
        layout.addWidget(self._refresh_button)

        self._lazy_load_data()

    def _resolve_output_dir(self) -> Path:
        configured = self.config_manager.get("OUTPUT_CLIPS_DIR")
        base = Path(configured) if configured else processing_path("output_clips")
        base.mkdir(parents=True, exist_ok=True)
        self._output_dir = base
        # runs metadata directory (sibling of output_clips)
        runs_dir = base.parent / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir = runs_dir
        return base

    # ---------------------- Run Metadata Management ----------------------
    def _run_meta_path(self, video_base: str, run_id: str | None = None) -> Path:
        if not self._runs_dir:
            self._resolve_output_dir()
        assert self._runs_dir is not None
        if run_id is None:
            run_id = time.strftime("%Y%m%d-%H%M%S")
        safe_base = video_base.replace(os.sep, "_")
        return self._runs_dir / f"{safe_base}__{run_id}.run.json"

    def record_run_start(self, video_base: str) -> Path:
        """Create a run metadata file for a new processing attempt.

        This can be called by pipeline code at start; if not called explicitly,
        we fall back to heuristic counting during listing.
        """
        meta = {
            "video": video_base,
            "started_at": time.time(),
            "status": "running",
        }
        path = self._run_meta_path(video_base)
        try:
            path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            logging.debug("[clips_manager] 记录新的运行: %s", path.name)
        except Exception as exc:  # noqa: BLE001
            logging.debug("[clips_manager] 写入运行元数据失败: %s", exc)
        return path

    def finalize_run(self, meta_path: Path, success: bool = True) -> None:
        try:
            if meta_path.exists():
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                data["finished_at"] = time.time()
                data["status"] = "success" if success else "failed"
                meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_explicit_runs(self) -> dict[str, int]:
        """Count runs per video based on explicit run metadata files (.run.json)."""
        counts: dict[str, int] = {}
        if not self._runs_dir:
            self._resolve_output_dir()
        assert self._runs_dir is not None
        try:
            for p in self._runs_dir.glob("*.run.json"):
                try:
                    with p.open("r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    base = data.get("video") or "(未知来源)"
                    counts[base] = counts.get(base, 0) + 1
                except Exception:
                    continue
        except Exception:
            pass
        return counts

    def _lazy_load_data(self) -> None:
        """Load grouped clip summary with improved run counting.

        Priority of run count sources:
          1. Explicit run metadata files in runs/ (one per processing attempt)
          2. Historical heuristic file run_history.json (backward compatibility)
          3. Fallback: assume at least 1 run if clips exist.
        """
        if not self._list:
            return
        directory = self._resolve_output_dir()
        self._list.clear()
        history_path = directory / "run_history.json"  # legacy
        import re
        run_history: dict[str, int] = {}
        # --- explicit runs ---
        explicit_runs = self._load_explicit_runs()
        # --- legacy heuristic history ---
        if not explicit_runs and history_path.exists():
            try:
                run_history = json.loads(history_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logging.debug("[clips_manager] 读取 run_history 失败: %s", exc)
        # Scan clips
        try:
            clips = [p for p in directory.iterdir() if p.suffix.lower() == ".mp4"]
        except FileNotFoundError:
            logging.info("[clips_manager] 输出目录不存在: %s", directory)
            return
        except Exception as exc:  # noqa: BLE001
            logging.error("[clips_manager] 列出剪辑失败: %s", exc)
            return
        pattern = re.compile(r"^(?P<base>.+?)(?:__clip_|_clip_).+")
        grouped: dict[str, list[Path]] = {}
        for clip in clips:
            name = clip.name
            m = pattern.match(name)
            base = m.group("base") if m else "(未知来源)"
            grouped.setdefault(base, []).append(clip)
        # Determine counts
        if explicit_runs:
            counts_source = "explicit"
            counts = explicit_runs
        else:
            counts_source = "legacy"
            # ensure at least 1 for bases with clips
            for base in grouped:
                run_history.setdefault(base, 1)
            counts = run_history
            # persist legacy file (keep previous behavior)
            try:
                history_path.write_text(json.dumps(run_history, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        # Populate list sorted by last modification of newest clip
        def newest_mtime(items: list[Path]) -> float:
            return max((p.stat().st_mtime for p in items), default=0.0)
        ordered = sorted(grouped.items(), key=lambda kv: newest_mtime(kv[1]), reverse=True)
        total_clip_files = 0
        for base, file_list in ordered:
            run_count = counts.get(base, 1)
            display = f"{base}  |  运行次数: {run_count}  | 剪辑数: {len(file_list)}  | 来源: {counts_source}"
            item = QListWidgetItem(display)
            # Store detail payload (list of paths) as joined string
            item.setData(256, "|".join(str(p) for p in file_list))
            self._list.addItem(item)
            total_clip_files += len(file_list)
        logging.info("[clips_manager] 已分组加载 %d 个视频，共 %d 个剪辑文件", len(grouped), total_clip_files)

    def _open_folder(self) -> None:
        directory = self._resolve_output_dir()
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", str(directory)])
            elif sys.platform == "darwin":  # type: ignore[name-defined]
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)])
        except Exception as exc:  # noqa: BLE001
            logging.error("[clips_manager] 打开目录失败: %s", exc)


def create_clips_manager(main_window, config_manager):
    """Factory used by the GUI."""
    return _BasicClipsManager(main_window, config_manager)
