"""Standalone GUI for managing the RAG vector database."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
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


def _iter_text_records_from_file(filepath: str) -> Iterable[Dict[str, object]]:
    """Yield clip transcript records from text/json/jsonl files."""
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix == ".txt":
            content = Path(filepath).read_text(encoding="utf-8")
            blocks = re.split(r"\n\s*\n+", content)
            for block in blocks:
                text = re.sub(r"\s+", " ", block).strip()
                if text:
                    yield {"text": text}
            return
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
                    if isinstance(obj, str):
                        yield {"text": obj}
                        continue
                    if not isinstance(obj, dict):
                        continue
                    yield {
                        "text": obj.get("text")
                        or obj.get("content")
                        or obj.get("transcript")
                        or obj.get("transcript_text")
                        or obj.get("raw_text")
                        or obj.get("summary_text")
                        or "",
                        "clip_path": obj.get("clip_path"),
                        "video_name": obj.get("video_name") or obj.get("video"),
                        "start": obj.get("start") or obj.get("start_sec"),
                        "end": obj.get("end") or obj.get("end_sec"),
                        "rating": obj.get("rating") or obj.get("score"),
                    }
            return
        if suffix == ".json":
            with open(filepath, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            items = None
            if isinstance(payload, dict):
                items = payload.get("clips") or payload.get("items")
                if items is None and "text" in payload:
                    items = [payload]
            elif isinstance(payload, list):
                items = payload
            if items:
                for obj in items:
                    if isinstance(obj, str):
                        yield {"text": obj}
                        continue
                    if not isinstance(obj, dict):
                        continue
                    yield {
                        "text": obj.get("text")
                        or obj.get("content")
                        or obj.get("transcript")
                        or obj.get("transcript_text")
                        or obj.get("raw_text")
                        or obj.get("summary_text")
                        or "",
                        "clip_path": obj.get("clip_path"),
                        "video_name": obj.get("video_name") or obj.get("video"),
                        "start": obj.get("start") or obj.get("start_sec"),
                        "end": obj.get("end") or obj.get("end_sec"),
                        "rating": obj.get("rating") or obj.get("score"),
                    }
            return
    except Exception as exc:
        logging.warning("[RAG GUI] Failed reading %s: %s", filepath, exc)
        return


def _resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_clips_db_path(config: ConfigManager) -> Optional[Path]:
    configured = (
        config.get("RAG_CLIPS_DB_PATH")
        or os.environ.get("RAG_CLIPS_DB_PATH")
    )
    candidates = []
    if configured:
        candidates.append(str(configured))
    candidates.extend(["rag_store/clips.db", "clips.db"])
    repo_root = _resolve_repo_root()
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        if path.exists():
            return path
    return None


def _resolve_rag_db_path(config: ConfigManager) -> Optional[Path]:
    configured = config.get("RAG_DB_PATH") or os.environ.get("RAG_DB_PATH")
    candidates: List[Path] = []
    if configured:
        path = Path(str(configured))
        if not path.is_absolute():
            path = (_resolve_repo_root() / path).resolve()
        candidates.append(path)
    candidates.append(processing_path("rag_database.json"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _iter_records_from_rag_db(filepath: Path) -> Iterable[Dict[str, object]]:
    try:
        payload = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.warning("[RAG GUI] Failed reading %s: %s", filepath, exc)
        return
    if not isinstance(payload, dict):
        return
    clips = payload.get("clips")
    if not isinstance(clips, list):
        return
    for rec in clips:
        if not isinstance(rec, dict):
            continue
        yield {
            "clip_path": rec.get("clip_path"),
            "video_name": rec.get("video_name"),
            "start": rec.get("clip_start_time") or rec.get("start"),
            "end": rec.get("clip_end_time") or rec.get("end"),
            "rating": rec.get("user_rating") or rec.get("rating"),
            "text": rec.get("transcript_text") or rec.get("text") or "",
        }


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
        self.import_text_btn = QtWidgets.QPushButton("导入剪辑内容…")
        self.import_text_btn.clicked.connect(self.import_clip_contents)
        self.import_db_btn = QtWidgets.QPushButton("从数据库导入")
        self.import_db_btn.clicked.connect(self.import_from_database)
        self.summary_btn = QtWidgets.QPushButton("偏好总结")
        self.summary_btn.clicked.connect(self.show_preferences)
        self.embed_btn = QtWidgets.QPushButton("生成向量")
        self.embed_btn.clicked.connect(self.ensure_embeddings)
        self.clear_btn = QtWidgets.QPushButton("清空数据库")
        self.clear_btn.clicked.connect(self.clear_database)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.import_text_btn)
        btn_layout.addWidget(self.import_db_btn)
        btn_layout.addWidget(self.summary_btn)
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

    def _build_manual_clip_path(self, source_path: str, index: int, existing: set) -> str:
        base = Path(source_path).stem or "manual"
        candidate = f"{base}_clip_{index}.txt"
        suffix = 1
        while candidate in existing:
            candidate = f"{base}_clip_{index}_{suffix}.txt"
            suffix += 1
        return candidate

    def import_clip_contents(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择剪辑内容文件",
            os.getcwd(),
            "文本/JSON (*.txt *.json *.jsonl);;所有文件 (*)",
        )
        if not files:
            return
        default_rating, ok = QtWidgets.QInputDialog.getInt(
            self,
            "默认评分",
            "请输入默认评分 (1-5)：",
            5,
            1,
            5,
        )
        if not ok:
            return
        existing = {clip.get("clip_path") for clip in self.db.get_all_clips()}
        added = 0
        for file_path in files:
            index = 1
            for record in _iter_text_records_from_file(file_path):
                text = str(record.get("text") or "").strip()
                if not text:
                    continue
                clip_path = str(record.get("clip_path") or "").strip()
                if not clip_path:
                    clip_path = self._build_manual_clip_path(file_path, index, existing)
                if clip_path in existing:
                    index += 1
                    continue
                video_name = str(record.get("video_name") or Path(file_path).stem)
                try:
                    start = float(record.get("start") or 0.0)
                except Exception:
                    start = 0.0
                try:
                    end = float(record.get("end") or 0.0)
                except Exception:
                    end = 0.0
                rating_val = record.get("rating")
                if rating_val is None:
                    rating = default_rating
                else:
                    try:
                        rating = int(round(float(rating_val)))
                    except Exception:
                        rating = default_rating
                rating = max(1, min(5, rating))
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
                index += 1
        if added:
            self._append_log(f"已导入 {added} 条剪辑内容。")
        else:
            self._append_log("未导入新的剪辑内容。")
        self.refresh_table()

    def _make_db_clip_id(self, db_path: Path, clip_id: object) -> str:
        return f"{db_path.name}#clip-{clip_id}"

    def import_from_database(self) -> None:
        db_path = _resolve_clips_db_path(self.config)
        if db_path:
            self._import_from_clips_db(db_path)
            return
        rag_db = _resolve_rag_db_path(self.config)
        if rag_db and rag_db.resolve() != Path(self.db_path).resolve():
            self._import_from_rag_db(rag_db)
            return
        QtWidgets.QMessageBox.warning(
            self,
            "未找到数据库",
            "未找到 clips.db，且 RAG_DB_PATH 与当前数据库相同或不存在。",
        )

    def _import_from_clips_db(self, db_path: Path) -> None:
        try:
            import sqlite3
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "SQLite 不可用", str(exc))
            return

        default_rating = self.config.get("RAG_IMPORT_DEFAULT_RATING", 5)
        try:
            rating = int(default_rating)
        except Exception:
            rating = 5
        rating = max(1, min(5, rating))

        existing = {clip.get("clip_path") for clip in self.db.get_all_clips()}
        added = 0
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT clip_id, video_id, start_sec, end_sec, summary_text, raw_text FROM clips"
            ).fetchall()
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.warning(self, "读取失败", f"无法读取数据库: {exc}")
            return
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        for row in rows:
            text = (row["summary_text"] or row["raw_text"] or "").strip()
            if not text:
                continue
            clip_path = self._make_db_clip_id(db_path, row["clip_id"])
            if clip_path in existing:
                continue
            try:
                start = float(row["start_sec"] or 0.0)
            except Exception:
                start = 0.0
            try:
                end = float(row["end_sec"] or 0.0)
            except Exception:
                end = 0.0
            if self.db.add_liked_clip_vector(
                clip_path=clip_path,
                transcript_text=text,
                video_name=str(row["video_id"] or ""),
                clip_start_time=start,
                clip_end_time=end,
                user_rating=rating,
            ):
                existing.add(clip_path)
                added += 1

        if added:
            self._append_log(f"已从 clips.db 导入 {added} 条剪辑内容。")
        else:
            self._append_log("未导入新的剪辑内容（可能为空或已存在）。")
        self.refresh_table()

    def _import_from_rag_db(self, rag_db: Path) -> None:
        existing = {clip.get("clip_path") for clip in self.db.get_all_clips()}
        default_rating = self.config.get("RAG_IMPORT_DEFAULT_RATING", 5)
        try:
            rating_default = int(default_rating)
        except Exception:
            rating_default = 5
        rating_default = max(1, min(5, rating_default))
        added = 0
        index = 1
        for record in _iter_records_from_rag_db(rag_db):
            text = str(record.get("text") or "").strip()
            if not text:
                continue
            clip_path = str(record.get("clip_path") or "").strip()
            if not clip_path:
                clip_path = self._build_manual_clip_path(str(rag_db), index, existing)
            if clip_path in existing:
                index += 1
                continue
            video_name = str(record.get("video_name") or "imported")
            try:
                start = float(record.get("start") or 0.0)
            except Exception:
                start = 0.0
            try:
                end = float(record.get("end") or 0.0)
            except Exception:
                end = 0.0
            rating_val = record.get("rating")
            if rating_val is None:
                rating = rating_default
            else:
                try:
                    rating = int(round(float(rating_val)))
                except Exception:
                    rating = rating_default
            rating = max(1, min(5, rating))
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
            index += 1

        if added:
            self._append_log(f"已从 RAG_DB_PATH 导入 {added} 条剪辑内容。")
        else:
            self._append_log("未导入新的剪辑内容（可能为空或已存在）。")
        self.refresh_table()

    def ensure_embeddings(self) -> None:
        created = self.db.ensure_embeddings()
        self._append_log(f"生成/补全向量 {created} 条。")

    # ---- Preference summary ------------------------------------------ #

    def show_preferences(self) -> None:
        """Show a lightweight summary of current RAG preferences."""
        clips = self.db.get_all_clips()
        if not clips:
            QtWidgets.QMessageBox.information(self, "偏好总结", "数据库为空，先导入或添加剪辑。")
            return

        summary_lines = self._build_summary(clips)

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("偏好总结")
        layout = QtWidgets.QVBoxLayout(dlg)
        text = QtWidgets.QPlainTextEdit("\n".join(summary_lines))
        text.setReadOnly(True)
        text.setMinimumHeight(260)
        layout.addWidget(text)
        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=QtCore.Qt.AlignRight)
        dlg.resize(520, 360)
        dlg.exec_()

    def _build_summary(self, clips: List[Dict[str, object]]) -> List[str]:
        """Generate human-readable preference hints from stored clips."""
        ratings = [c.get("user_rating") for c in clips if isinstance(c.get("user_rating"), (int, float))]
        durations = []
        videos = Counter()
        topic_items: List[Dict[str, object]] = []
        vectors = self.db.data.get("vectors", {}) if hasattr(self.db, "data") else {}
        vector_ready = sum(1 for c in clips if c.get("clip_path") in vectors and isinstance(vectors.get(c.get("clip_path")), dict))

        for c in clips:
            try:
                start = float(c.get("clip_start_time") or c.get("start") or 0.0)
                end = float(c.get("clip_end_time") or c.get("end") or 0.0)
                if end > start:
                    durations.append(end - start)
            except Exception:
                pass
            video_name = str(c.get("video_name") or "").strip()
            if video_name:
                videos[video_name] += 1
            text = str(c.get("transcript_text") or c.get("text") or "")
            if text.strip():
                clip_path = c.get("clip_path")
                vec = None
                if clip_path and isinstance(vectors, dict):
                    entry = vectors.get(clip_path)
                    if isinstance(entry, dict):
                        vec = entry.get("vector")
                topic_items.append({"text": text, "vector": vec})

        lines: List[str] = []
        lines.append(f"已收集剪辑: {len(clips)} 条，平均评分: {mean(ratings):.2f}" if ratings else f"已收集剪辑: {len(clips)} 条，暂无评分数据")
        if durations:
            lines.append(f"片段时长 (秒): 平均 {mean(durations):.1f} · 中位 {median(durations):.1f}")
        if videos:
            top_videos = ", ".join(f"{name}({cnt})" for name, cnt in videos.most_common(3))
            lines.append(f"常出现的视频/主播: {top_videos}")
        lines.extend(self._build_topic_summary(topic_items))
        if vectors:
            pct = (vector_ready / max(1, len(clips))) * 100
            lines.append(f"向量覆盖率: {pct:.0f}%（用于个性化相似度）")
        else:
            lines.append("向量覆盖率: 0%（点击“生成向量”后可启用个性化相似度）")

        # quick qualitative hint
        if ratings:
            high = sum(1 for r in ratings if r >= 4)
            low = sum(1 for r in ratings if r <= 2)
            if high > low * 2:
                lines.append("偏好倾向: 高分集中，说明偏好较明确，可进一步加大 RAG 权重测试。")
            elif low > high:
                lines.append("偏好倾向: 评分分布分散，建议补充更多高分样本。")
        return lines

    def _build_topic_summary(self, items: List[Dict[str, object]]) -> List[str]:
        texts_all = [str(item.get("text") or "").strip() for item in items if str(item.get("text") or "").strip()]
        if len(texts_all) < 2:
            return ["主题模型: 样本不足（至少需要 2 条文本）"]

        stopwords = {
            "and", "the", "with", "this", "that", "what", "you", "have", "for", "but",
            "are", "was", "when", "where", "how", "just", "like", "get", "got",
            "i", "me", "my", "we", "our", "us", "your", "youre", "im", "ive",
            "so", "thank", "thanks", "much", "follow", "raid", "good",
            "的", "了", "是", "我", "你", "他", "她", "它", "我们", "你们", "他们",
            "啊", "吗", "呀", "吧", "就", "都", "和", "与", "在", "有", "也", "很",
        }

        def _tokenize(text: str) -> List[str]:
            tokens = re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
            return [tok for tok in tokens if tok not in stopwords]

        items_with_vec = []
        for item in items:
            text = str(item.get("text") or "").strip()
            vec = item.get("vector")
            if text and isinstance(vec, list) and vec:
                items_with_vec.append((text, vec))

        data_texts = texts_all
        data_matrix = None
        try:
            import numpy as np
        except Exception:
            np = None

        if items_with_vec and np is not None:
            data_texts = [t for t, _ in items_with_vec]
            data_matrix = np.array([v for _, v in items_with_vec], dtype="float32")
        else:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
            except Exception:
                return ["主题模型: 未能加载 scikit-learn，无法生成主题"]
            vectorizer = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None, min_df=1, max_df=0.6, max_features=2000)
            try:
                tfidf = vectorizer.fit_transform(data_texts)
            except ValueError:
                return ["主题模型: 文本不足以生成主题"]
            data_matrix = tfidf.toarray()

        n_docs = len(data_texts)
        if n_docs < 2:
            return ["主题模型: 样本不足（至少需要 2 条文本）"]

        try:
            from sklearn.cluster import KMeans
            from sklearn.metrics import silhouette_score
        except Exception:
            return ["主题模型: 未能加载 scikit-learn，无法生成主题"]

        def _choose_k(data):
            max_k = min(6, n_docs - 1)
            if max_k < 2:
                km = KMeans(n_clusters=2 if n_docs >= 2 else 1, n_init=10, random_state=0)
                labels = km.fit_predict(data)
                return km, labels
            best_km = None
            best_labels = None
            best_score = -1.0
            for k in range(2, max_k + 1):
                km = KMeans(n_clusters=k, n_init=10, random_state=0)
                labels = km.fit_predict(data)
                try:
                    score = silhouette_score(data, labels)
                except Exception:
                    score = -1.0
                if score > best_score:
                    best_score = score
                    best_km = km
                    best_labels = labels
            if best_km is None or best_labels is None:
                best_km = KMeans(n_clusters=2, n_init=10, random_state=0)
                best_labels = best_km.fit_predict(data)
            return best_km, best_labels

        kmeans, labels = _choose_k(data_matrix)
        n_topics = len(set(labels)) if labels is not None else 0
        if not n_topics:
            return ["主题模型: 聚类失败，无法生成主题"]

        llm, model_name = self._get_topic_llm()
        llm_note = f" · LLM: {model_name}" if llm else " · LLM 不可用"
        lines = [f"主题模型: {n_topics} 个主题（基于 {n_docs} 段文本{llm_note}）"]

        try:
            import numpy as np
        except Exception:
            np = None

        clusters = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(int(label), []).append(idx)

        order = sorted(clusters.keys(), key=lambda k: len(clusters[k]), reverse=True)
        centers = getattr(kmeans, "cluster_centers_", None)

        for rank, label in enumerate(order, start=1):
            idxs = clusters[label]
            rep_texts = [data_texts[i] for i in idxs]
            if centers is not None and np is not None:
                center = centers[label]
                distances = [(i, float(np.linalg.norm(data_matrix[i] - center))) for i in idxs]
                distances.sort(key=lambda x: x[1])
                rep_texts = [data_texts[i] for i, _ in distances[:4]]
            topic_label = self._label_topic_llm(rep_texts, llm, stopwords)
            lines.append(f"主题{rank}: {topic_label}")
        return lines

    def _get_topic_llm(self):
        if getattr(self, "_topic_llm_checked", False):
            return getattr(self, "_topic_llm", None), getattr(self, "_topic_llm_model", "")
        self._topic_llm_checked = True
        model_name = str(
            self.config.get("RAG_TOPIC_LLM_MODEL")
            or self.config.get("LOCAL_SUMMARY_MODEL")
            or os.environ.get("RAG_TOPIC_LLM_MODEL")
            or os.environ.get("LOCAL_SUMMARY_MODEL")
            or "google/gemma-3-4b-it"
        ).strip()
        self._topic_llm_model = model_name
        if not model_name or model_name.lower() in {"off", "none", "disable", "disabled"}:
            self._topic_llm = None
            return None, model_name
        try:
            from transformers import pipeline
        except Exception:
            self._topic_llm = None
            return None, model_name
        try:
            self._topic_llm_task = "text2text-generation"
            device_id = self._resolve_hf_device_id()
            self._topic_llm = pipeline("text2text-generation", model=model_name, device=device_id)
        except Exception:
            try:
                self._topic_llm_task = "text-generation"
                device_id = self._resolve_hf_device_id()
                self._topic_llm = pipeline("text-generation", model=model_name, device=device_id)
            except Exception:
                self._topic_llm = None
        return self._topic_llm, model_name

    def _resolve_hf_device_id(self) -> int:
        enable_gpu = bool(self.config.get("ENABLE_GPU_ACCELERATION", True))
        if not enable_gpu:
            return -1
        try:
            import torch
        except Exception:
            return -1
        if not torch.cuda.is_available():
            return -1
        llm_device = self.config.get("LLM_DEVICE", 0)
        try:
            llm_device_id = int(llm_device)
        except (TypeError, ValueError):
            llm_device_id = None
        if llm_device_id is not None:
            return llm_device_id if llm_device_id >= 0 else -1
        gpu_device = str(self.config.get("GPU_DEVICE", "cuda:0") or "cuda:0")
        if gpu_device.startswith("cuda"):
            parts = gpu_device.split(":")
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
        return 0

    def _label_topic_llm(self, texts: List[str], llm, stopwords: set) -> str:
        texts = [re.sub(r"\s+", " ", t).strip() for t in texts if t and t.strip()]
        if not texts:
            return "（无有效文本）"
        use_chinese = any(re.search(r"[\u4e00-\u9fff]", t) for t in texts)
        snippets = [t[:220] for t in texts[:4]]
        if llm:
            if use_chinese:
                prompt = (
                    "根据以下剪辑转录内容，输出一个简短主题标签（2-6个词），只输出标签。\n"
                    "要求：不要直接引用原句，避免感谢/关注/打招呼/订阅/raid 等泛用语。\n"
                )
            else:
                prompt = (
                    "Given the following clip transcripts, return a short topic label (2-6 words). "
                    "Only return the label. Do not quote full sentences, and ignore generic "
                    "phrases like thanks, follows, greetings, subs, raids.\n"
                )
            prompt += "\n".join(f"- {s}" for s in snippets)
            try:
                output = llm(prompt, max_new_tokens=24, num_beams=4, do_sample=False, truncation=True)
                if isinstance(output, list) and output:
                    label = output[0].get("generated_text") or output[0].get("summary_text") or ""
                    if getattr(self, "_topic_llm_task", "") == "text-generation" and label.startswith(prompt):
                        label = label[len(prompt):]
                    label = label.strip().splitlines()[0]
                    if label:
                        return label
            except Exception:
                pass
        tokens = Counter()
        for text in snippets:
            for tok in re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", text.lower()):
                if tok in stopwords:
                    continue
                tokens[tok] += 1
        if tokens:
            return ", ".join(tok for tok, _ in tokens.most_common(5))
        return "（无法生成主题）"

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
