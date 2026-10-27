"""Scalable Qt model/view projections for product collections."""

from __future__ import annotations

from typing import Any, Iterable

from PyQt5.QtCore import QAbstractListModel, QModelIndex, Qt
from PyQt5.QtGui import QIcon

from .viewmodels import ClipVM, CreatorVM, JobVM, MomentVM, RecordingVM, duration_text


OBJECT_ROLE = Qt.UserRole + 1
ID_ROLE = Qt.UserRole + 2
STATUS_ROLE = Qt.UserRole + 3


class ObjectListModel(QAbstractListModel):
    def __init__(self, rows: Iterable[Any] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = list(rows)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == OBJECT_ROLE:
            return row
        if role == ID_ROLE:
            return getattr(row, "id", "")
        if role == STATUS_ROLE:
            return getattr(row, "status", getattr(row, "state", ""))
        if role in {Qt.DisplayRole, Qt.ToolTipRole}:
            return self.display_text(row)
        if role == Qt.AccessibleTextRole:
            return self.display_text(row)
        return None

    def display_text(self, row: Any) -> str:
        return str(row)

    def replace(self, rows: Iterable[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def append(self, rows: Iterable[Any]) -> None:
        values = list(rows)
        if not values:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(values) - 1)
        self._rows.extend(values)
        self.endInsertRows()

    def object_at(self, index: QModelIndex) -> Any | None:
        return self.data(index, OBJECT_ROLE)

    @property
    def rows(self) -> list[Any]:
        return list(self._rows)


class CreatorModel(ObjectListModel):
    def display_text(self, row: CreatorVM) -> str:
        activity = f" · {row.processing_count} 处理中" if row.processing_count else ""
        profile = {"READY": "Profile ✓", "NOT_BUILT": "Profile 未构建"}.get(row.profile_status, "Profile 需检查")
        return f"{row.name}\n{row.platform} · {row.recording_count} 个 Recording{activity}\n{profile}"


class RecordingModel(ObjectListModel):
    def __init__(self, rows=(), parent=None) -> None:
        super().__init__(rows, parent)
        self._thumbnails: dict[str, QIcon] = {}

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DecorationRole and index.isValid():
            row = self._rows[index.row()]
            return self._thumbnails.get(row.id)
        return super().data(index, role)

    def display_text(self, row: RecordingVM) -> str:
        missing = " · 媒体缺失" if row.missing_media else ""
        return (
            f"{row.title}\n{row.date} · {duration_text(row.duration_ms)} · "
            f"{row.source_type} · {row.language}\n{row.status}{missing}"
        )

    def set_thumbnail(self, recording_id: str, path: str) -> None:
        if not path:
            return
        self._thumbnails[recording_id] = QIcon(path)
        for row, item in enumerate(self._rows):
            if item.id == recording_id:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [Qt.DecorationRole])
                break


class MomentModel(ObjectListModel):
    def display_text(self, row: MomentVM) -> str:
        excerpt = " ".join(row.excerpt.split())
        if len(excerpt) > 150:
            excerpt = excerpt[:147] + "…"
        return (
            f"{row.summary}\n{row.recording_title} · {duration_text(row.start_ms)} · "
            f"{duration_text(row.end_ms - row.start_ms)} · {row.relevance}\n{excerpt}"
        )


class ClipModel(ObjectListModel):
    def display_text(self, row: ClipVM) -> str:
        return (
            f"{row.title}\n{duration_text(row.start_ms)}–{duration_text(row.end_ms)} · "
            f"{duration_text(row.end_ms - row.start_ms)}\n{row.render_status} · {row.review_status}"
        )


class JobModel(ObjectListModel):
    def display_text(self, row: JobVM) -> str:
        progress = "" if row.progress is None else f" · {row.progress:.0f}%"
        return f"{row.label}\n{row.context} · {row.state}{progress}"

