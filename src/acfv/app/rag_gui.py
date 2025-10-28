"""Standalone GUI for managing the RAG vector database."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise

from acfv.config._config_impl import ConfigManager, config_manager  # reuse singleton
from acfv.rag_vector_database import RAGVectorDatabase
from acfv.runtime.storage import processing_path

# --------------------------------------------------------------------------- #
# Helpers


def _default_rag_path() -> str:
    """Return the configured RAG database path (guaranteed absolute)."""
    configured = config_manager.get("RAG_DB_PATH")
    if configured:
        return os.path.abspath(config_manager.get("RAG_DB_PATH"))
    path = processing_path("rag_database.json")
    config_manager.set("RAG_DB_PATH", str(path), persist=True)
    return str(path)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _iter_records_from_file(filepath: str) -> Iterable[Dict[str, object]]:
    """Yield normalized clip records from ratings.json / jsonl files."""
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix == ".jsonl":
            with open(filepath, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    yield {
                        "video_name": obj.get("video_name") or obj.get("video"),
                        "clip_path": obj.get("clip_path"),
                        "start": obj.get("start") or obj.get("start_sec"),
                        "end": obj.get("end") or obj.get("end_sec"),
                        "score": obj.get("score") or obj.get("rating"),
                        "text": obj.get("content") or obj.get("text") or "",
                    }
            return

        with open(filepath, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        logging.warning("[RAG GUI] Failed reading %s: %s", filepath, exc)
        return

    base_dir = Path(filepath).resolve().parent
    clips_dir = (base_dir / ".." / "output_clips").resolve()

    def _normalise_entry(name: str, rec: Dict[str, object]) -> Dict[str, object]:
        clip_path = rec.get("clip_path")
        if not clip_path:
            clip_path = clips_dir / name
        return {
            "video_name": rec.get("video_name") or base_dir.parent.name,
            "clip_path": str(clip_path),
            "start": rec.get("start") or rec.get("start_sec"),
            "end": rec.get("end") or rec.get("end_sec"),
            "score": rec.get("rating") or rec.get("score"),
            "text": rec.get("text") or "",
        }

    if isinstance(payload, dict):
        for key, rec in payload.items():
            if not isinstance(rec, dict):
                continue
            yield _normalise_entry(key, rec)
    elif isinstance(payload, list):
        for rec in payload:
            if not isinstance(rec, dict):
                continue
            clip_name = rec.get("clip_filename") or rec.get("clip") or rec.get("name") or "clip.mp4"
            yield _normalise_entry(str(clip_name), rec)


# --------------------------------------------------------------------------- #
# GUI widgets


class RAGManagerWindow(QtWidgets.QMainWindow):
    """Simple manager for inspecting and editing the RAG vector database."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ACFV RAG 管理器")
        self.resize(900, 600)

        self.config: ConfigManager = config_manager
        self.db_path = _default_rag_path()
        _ensure_parent(self.db_path)
        self.db = RAGVectorDatabase(database_path=self.db_path)

        self._build_ui()
        self.refresh_table()

    # ---- UI setup ----------------------------------------------------- #

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setSpacing(12)

        # Path selector
        path_layout = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit(self.db_path)
        self.path_edit.setReadOnly(True)
        browse_btn = QtWidgets.QPushButton("选择文件…")
        browse_btn.clicked.connect(self.choose_db_path)
        path_layout.addWidget(QtWidgets.QLabel("RAG 数据库:"))
        path_layout.addWidget(self.path_edit, 1)
        path_layout.addWidget(browse_btn)
        root_layout.addLayout(path_layout)

        # Table
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["视频", "片段", "开始", "结束", "评分"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        root_layout.addWidget(self.table, 1)

        # Buttons row
        btn_layout = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_table)
        self.import_btn = QtWidgets.QPushButton("导入 ratings…")
        self.import_btn.clicked.connect(self.import_ratings)
        self.embed_btn = QtWidgets.QPushButton("生成向量")
        self.embed_btn.clicked.connect(self.ensure_embeddings)
        self.clear_btn = QtWidgets.QPushButton("清空数据库")
        self.clear_btn.clicked.connect(self.clear_database)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.embed_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch(1)
        root_layout.addLayout(btn_layout)

        # Status area
        self.summary_label = QtWidgets.QLabel()
        self.summary_label.setWordWrap(True)
        root_layout.addWidget(self.summary_label)

        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(300)
        root_layout.addWidget(self.log_box, stretch=0)

        self._append_log("RAG GUI 已初始化。")

    # ---- Actions ------------------------------------------------------ #

    def _append_log(self, message: str) -> None:
        self.log_box.appendPlainText(message)
        self.statusBar().showMessage(message, 5000)

    def choose_db_path(self) -> None:
        new_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "选择 RAG 数据库文件",
            self.db_path,
            "JSON 文件 (*.json);;所有文件 (*)",
        )
        if not new_path:
            return
        self.db_path = os.path.abspath(new_path)
        _ensure_parent(self.db_path)
        self.path_edit.setText(self.db_path)
        self.config.set("RAG_DB_PATH", self.db_path, persist=True)
        self.db = RAGVectorDatabase(database_path=self.db_path)
        self._append_log(f"已切换数据库: {self.db_path}")
        self.refresh_table()

    def refresh_table(self) -> None:
        clips = self.db.get_all_clips()
        self.table.setRowCount(len(clips))
        for row, clip in enumerate(clips):
            video = clip.get("video_name") or ""
            path = clip.get("clip_path") or ""
            start = clip.get("clip_start_time") or clip.get("start") or 0.0
            end = clip.get("clip_end_time") or clip.get("end") or 0.0
            rating = clip.get("user_rating") or ""
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(video)))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(Path(path).name)))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{float(start):.1f}"))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(f"{float(end):.1f}"))
            self.table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(rating)))
        self.summary_label.setText(
            f"目前记录 {len(clips)} 个剪辑 · 数据库路径：{self.db_path}"
        )
        self._append_log(f"已刷新，载入 {len(clips)} 条记录。")

    def import_ratings(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择 ratings.json / jsonl",
            os.getcwd(),
            "Ratings (*.json *.jsonl);;所有文件 (*)",
        )
        if not files:
            return
        existing = {clip.get("clip_path") for clip in self.db.get_all_clips()}
        added = 0
        for file_path in files:
            for record in _iter_records_from_file(file_path):
                clip_path = record.get("clip_path")
                if not clip_path:
                    continue
                clip_path = os.path.abspath(str(clip_path))
                if clip_path in existing:
                    continue
                text = str(record.get("text") or "")
                video_name = str(record.get("video_name") or "")
                start = float(record.get("start") or 0.0)
                end = float(record.get("end") or 0.0)
                try:
                    score_val = record.get("score")
                    rating = int(round(float(score_val))) if score_val is not None else 5
                except Exception:
                    rating = 5
                if self.db.add_liked_clip_vector(
                    clip_path=clip_path,
                    transcript_text=text,
                    video_name=video_name,
                    clip_start_time=start,
                    clip_end_time=end,
                    user_rating=rating,
                ):
                    existing.add(clip_path)
                    added += 1
        if added:
            self._append_log(f"已导入 {added} 条剪辑。")
        else:
            self._append_log("未导入新的剪辑（可能全部已存在）。")
        self.refresh_table()

    def ensure_embeddings(self) -> None:
        created = self.db.ensure_embeddings()
        self._append_log(f"生成/补全向量 {created} 条。")

    def clear_database(self) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "确认清空",
            "确定要清空 RAG 数据库吗？此操作不可撤销。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self.db.clear_database()
        self._append_log("数据库已清空。")
        self.refresh_table()


# --------------------------------------------------------------------------- #


def launch_rag_gui() -> int:
    """Entry point used by CLI helpers."""
    app = QtWidgets.QApplication.instance()
    owns_app = False
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        owns_app = True
    window = RAGManagerWindow()
    window.show()
    return app.exec_() if owns_app else 0


__all__ = ["launch_rag_gui", "RAGManagerWindow"]
