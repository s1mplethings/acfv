from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from threading import RLock
from typing import Any, Iterable, Iterator, Mapping

from .models import ReviewSample, ReviewTask, TASK_ORDER, TaskProgress, coerce_task


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HumanReviewRepository:
    """SQLite owner for review datasets and genuine human annotations."""

    def __init__(self, db_path: Path, *, backup_dir: Path | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.backup_dir = Path(backup_dir or self.db_path.parent / "backups").resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.read_only = False
        self._writer: sqlite3.Connection | None = None
        self._write_lock = RLock()
        self._closed = False
        self._bootstrap()
        if not self.read_only:
            # Keep the writer alive for the repository lifetime. Opening and
            # closing a SQLite writer per item is expensive on derived drives
            # and may checkpoint the WAL after every annotation.
            self._writer = self._connect(write=True, check_same_thread=False)
            self._writer.execute("SELECT 1 FROM review_meta LIMIT 1").fetchone()

    def _connect(self, *, write: bool = False, check_same_thread: bool = True) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Human Review repository is closed")
        if write and self.read_only:
            raise RuntimeError("Human Review database is in read-only recovery mode")
        if self.read_only:
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, check_same_thread=check_same_thread)
        else:
            connection = sqlite3.connect(self.db_path, check_same_thread=check_same_thread)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        if write and not self.read_only:
            # WAL + NORMAL keeps interactive annotation commits responsive on
            # slower/derived volumes while preserving atomic transactions.
            # Backup/close performs a FULL checkpoint below.
            connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=3000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self._writer
            if connection is None:
                raise RuntimeError("Human Review repository has no writable connection")
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _bootstrap(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if result.lower() != "ok":
                self.read_only = True
                return
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS review_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_samples (
                    sample_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    creator TEXT NOT NULL DEFAULT '',
                    content_type TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    media_a TEXT NOT NULL DEFAULT '',
                    media_b TEXT NOT NULL DEFAULT '',
                    start_ms INTEGER NOT NULL DEFAULT 0,
                    end_ms INTEGER NOT NULL DEFAULT 0,
                    prompt_json TEXT NOT NULL DEFAULT '{}',
                    private_json TEXT NOT NULL DEFAULT '{}',
                    source_path TEXT NOT NULL DEFAULT '',
                    consistency_control INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    sample_id TEXT PRIMARY KEY REFERENCES review_samples(sample_id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'completed',
                    answer_json TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    revisit INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS annotation_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id TEXT NOT NULL REFERENCES review_samples(sample_id) ON DELETE CASCADE,
                    previous_answer_json TEXT,
                    new_answer_json TEXT NOT NULL,
                    previous_status TEXT,
                    new_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    task TEXT,
                    sample_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_settings (
                    key TEXT PRIMARY KEY, value_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_review_samples_task_order
                    ON review_samples(task, sort_order, sample_id);
                CREATE INDEX IF NOT EXISTS ix_annotations_status
                    ON annotations(status, revisit);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO review_meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        finally:
            connection.close()

    def integrity_check(self) -> str:
        with closing(self._connect()) as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])

    def replace_dataset(self, samples: Iterable[ReviewSample], metadata: Mapping[str, Any]) -> int:
        rows = list(samples)
        identifiers = [item.sample_id for item in rows]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate sample id")
        pair_keys: set[tuple[str, str]] = set()
        for item in rows:
            if item.task in (ReviewTask.TRANSLATION, ReviewTask.WATCHABILITY):
                pair_id = str(item.private.get("pair_id", "")).strip()
                if pair_id:
                    key = (item.task.value, pair_id)
                    if key in pair_keys:
                        raise ValueError(f"duplicate formal A/B pair: {pair_id}")
                    pair_keys.add(key)
        with self.transaction() as connection:
            connection.execute("DELETE FROM annotations")
            connection.execute("DELETE FROM annotation_revisions")
            connection.execute("DELETE FROM review_samples")
            connection.executemany(
                """INSERT INTO review_samples(
                    sample_id,task,creator,content_type,title,media_a,media_b,start_ms,end_ms,
                    prompt_json,private_json,source_path,consistency_control,sort_order
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        item.sample_id,
                        item.task.value,
                        item.creator,
                        item.content_type,
                        item.title,
                        item.media_a,
                        item.media_b,
                        int(item.start_ms),
                        int(item.end_ms),
                        json.dumps(dict(item.prompt), ensure_ascii=False, sort_keys=True),
                        json.dumps(dict(item.private), ensure_ascii=False, sort_keys=True),
                        item.source_path,
                        int(item.consistency_control),
                        index,
                    )
                    for index, item in enumerate(rows)
                ],
            )
            for key, value in metadata.items():
                connection.execute(
                    "INSERT OR REPLACE INTO review_meta(key,value) VALUES(?,?)",
                    (str(key), json.dumps(value, ensure_ascii=False, sort_keys=True)),
                )
            connection.execute("DELETE FROM review_state")
        return len(rows)

    def dataset_metadata(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT key,value FROM review_meta").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[str(row["key"])] = json.loads(str(row["value"]))
            except json.JSONDecodeError:
                result[str(row["key"])] = str(row["value"])
        return result

    def merge_dataset(self, samples: Iterable[ReviewSample], metadata: Mapping[str, Any]) -> int:
        """Add dataset-v2 rows without deleting v1 samples or annotations."""
        rows = list(samples)
        with self.transaction() as connection:
            current_max = int(connection.execute("SELECT COALESCE(MAX(sort_order),-1) FROM review_samples").fetchone()[0])
            inserted = 0
            for offset, item in enumerate(rows, 1):
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO review_samples(
                    sample_id,task,creator,content_type,title,media_a,media_b,start_ms,end_ms,
                    prompt_json,private_json,source_path,consistency_control,sort_order
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item.sample_id, item.task.value, item.creator, item.content_type, item.title,
                        item.media_a, item.media_b, int(item.start_ms), int(item.end_ms),
                        json.dumps(dict(item.prompt), ensure_ascii=False, sort_keys=True),
                        json.dumps(dict(item.private), ensure_ascii=False, sort_keys=True), item.source_path,
                        int(item.consistency_control), current_max + offset,
                    ),
                )
                inserted += int(cursor.rowcount or 0)
            for key, value in metadata.items():
                connection.execute(
                    "INSERT OR REPLACE INTO review_meta(key,value) VALUES(?,?)",
                    (str(key), json.dumps(value, ensure_ascii=False, sort_keys=True)),
                )
        return inserted

    @staticmethod
    def _sample(row: sqlite3.Row) -> ReviewSample:
        return ReviewSample(
            sample_id=str(row["sample_id"]),
            task=ReviewTask(str(row["task"])),
            creator=str(row["creator"]),
            content_type=str(row["content_type"]),
            title=str(row["title"]),
            media_a=str(row["media_a"]),
            media_b=str(row["media_b"]),
            start_ms=int(row["start_ms"]),
            end_ms=int(row["end_ms"]),
            prompt=json.loads(str(row["prompt_json"])),
            private=json.loads(str(row["private_json"])),
            source_path=str(row["source_path"]),
            consistency_control=bool(row["consistency_control"]),
        )

    def sample(self, sample_id: str) -> ReviewSample | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM review_samples WHERE sample_id=?", (sample_id,)).fetchone()
        return self._sample(row) if row else None

    def samples(
        self,
        task: str | ReviewTask,
        *,
        state: str = "remaining",
        creator: str = "",
        content_type: str = "",
    ) -> list[ReviewSample]:
        clauses = ["s.task=?"]
        values: list[Any] = [coerce_task(task).value]
        if creator:
            clauses.append("s.creator=?"); values.append(creator)
        if content_type:
            clauses.append("s.content_type=?"); values.append(content_type)
        if state == "remaining":
            clauses.append("a.sample_id IS NULL")
        elif state == "completed":
            clauses.append("a.status='completed'")
        elif state == "skipped":
            clauses.append("a.status='skipped'")
        elif state == "revisit":
            clauses.append("a.revisit=1")
        sql = (
            "SELECT s.* FROM review_samples s LEFT JOIN annotations a ON a.sample_id=s.sample_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY s.sort_order,s.sample_id"
        )
        with closing(self._connect()) as connection:
            return [self._sample(row) for row in connection.execute(sql, values).fetchall()]

    def annotation(self, sample_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM annotations WHERE sample_id=?", (sample_id,)).fetchone()
        if not row:
            return None
        return {
            "sample_id": sample_id,
            "status": str(row["status"]),
            "answer": json.loads(str(row["answer_json"])),
            "note": str(row["note"]),
            "revisit": bool(row["revisit"]),
            "updated_at": str(row["updated_at"]),
        }

    def update_media(self, sample_id: str, path: str, *, side: str = "a") -> None:
        column = "media_b" if side.lower() == "b" else "media_a"
        resolved = str(Path(path).expanduser().resolve())
        if not Path(resolved).is_file():
            raise FileNotFoundError(resolved)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE review_samples SET {column}=? WHERE sample_id=?",  # column is allow-listed above
                (resolved, sample_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(sample_id)

    def filter_values(self, task: str | ReviewTask) -> tuple[list[str], list[str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT creator,content_type FROM review_samples WHERE task=?",
                (coerce_task(task).value,),
            ).fetchall()
        creators = sorted({str(row["creator"]) for row in rows if str(row["creator"])})
        content_types = sorted({str(row["content_type"]) for row in rows if str(row["content_type"])})
        return creators, content_types

    def save(
        self,
        sample_id: str,
        answer: Mapping[str, Any],
        *,
        status: str = "completed",
        note: str = "",
        revisit: bool = False,
        resume_sample_id: str | None = None,
    ) -> None:
        if status not in {"completed", "skipped"}:
            raise ValueError(f"unsupported annotation status: {status}")
        encoded = json.dumps(dict(answer), ensure_ascii=False, sort_keys=True)
        now = _now()
        with self.transaction() as connection:
            if not connection.execute("SELECT 1 FROM review_samples WHERE sample_id=?", (sample_id,)).fetchone():
                raise KeyError(sample_id)
            previous = connection.execute("SELECT * FROM annotations WHERE sample_id=?", (sample_id,)).fetchone()
            connection.execute(
                """INSERT INTO annotation_revisions(
                    sample_id,previous_answer_json,new_answer_json,previous_status,new_status,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (
                    sample_id,
                    str(previous["answer_json"]) if previous else None,
                    encoded,
                    str(previous["status"]) if previous else None,
                    status,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO annotations(sample_id,status,answer_json,note,revisit,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(sample_id) DO UPDATE SET
                status=excluded.status,answer_json=excluded.answer_json,note=excluded.note,
                revisit=excluded.revisit,updated_at=excluded.updated_at""",
                (sample_id, status, encoded, note, int(revisit), now),
            )
            state_sample_id = resume_sample_id or sample_id
            state_row = connection.execute("SELECT task FROM review_samples WHERE sample_id=?", (state_sample_id,)).fetchone()
            if not state_row:
                raise KeyError(state_sample_id)
            connection.execute(
                "INSERT OR REPLACE INTO review_state(id,task,sample_id,updated_at) VALUES(1,?,?,?)",
                (str(state_row["task"]), state_sample_id, now),
            )
            total = int(connection.execute("SELECT COUNT(*) FROM annotation_revisions").fetchone()[0])
        if total and total % 50 == 0:
            self.backup(reason=f"auto-{total}")

    def mark_revisit(self, sample_id: str, enabled: bool = True) -> None:
        current = self.annotation(sample_id)
        self.save(
            sample_id,
            (current or {}).get("answer", {}),
            status=(current or {}).get("status", "skipped"),
            note=(current or {}).get("note", ""),
            revisit=enabled,
        )

    def progress(self) -> list[TaskProgress]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT s.task,COUNT(*) total,
                SUM(CASE WHEN a.status='completed' THEN 1 ELSE 0 END) completed,
                SUM(CASE WHEN a.status='skipped' THEN 1 ELSE 0 END) skipped,
                SUM(CASE WHEN a.revisit=1 THEN 1 ELSE 0 END) revisit
                FROM review_samples s LEFT JOIN annotations a ON a.sample_id=s.sample_id
                GROUP BY s.task"""
            ).fetchall()
        by_task = {str(row["task"]): dict(row) for row in rows}
        return [
            TaskProgress(
                task=task,
                completed=int(by_task.get(task.value, {}).get("completed", 0) or 0),
                total=int(by_task.get(task.value, {}).get("total", 0) or 0),
                skipped=int(by_task.get(task.value, {}).get("skipped", 0) or 0),
                revisit=int(by_task.get(task.value, {}).get("revisit", 0) or 0),
            )
            for task in TASK_ORDER
        ]

    def resume_state(self) -> tuple[ReviewTask | None, str | None]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT task,sample_id FROM review_state WHERE id=1").fetchone()
        return (ReviewTask(str(row["task"])), str(row["sample_id"])) if row else (None, None)

    def set_state(self, task: str | ReviewTask, sample_id: str) -> None:
        """Persist the item currently on screen, independently of annotation writes."""
        task_value = coerce_task(task).value
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT task FROM review_samples WHERE sample_id=?", (sample_id,)
            ).fetchone()
            if not row or str(row["task"]) != task_value:
                raise KeyError(sample_id)
            connection.execute(
                "INSERT OR REPLACE INTO review_state(id,task,sample_id,updated_at) VALUES(1,?,?,?)",
                (task_value, sample_id, _now()),
            )

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO review_settings(key,value_json) VALUES(?,?)",
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )

    def settings(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT key,value_json FROM review_settings").fetchall()
        return {str(row["key"]): json.loads(str(row["value_json"])) for row in rows}

    def annotation_rows(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT s.sample_id,s.task,s.creator,s.content_type,s.title,s.prompt_json,
                s.private_json,s.consistency_control,a.status,a.answer_json,a.note,a.revisit,a.updated_at
                FROM annotations a JOIN review_samples s ON s.sample_id=a.sample_id
                ORDER BY s.task,s.sort_order"""
            ).fetchall()
        return [
            {
                "sample_id": str(row["sample_id"]),
                "task": str(row["task"]),
                "creator": str(row["creator"]),
                "content_type": str(row["content_type"]),
                "title": str(row["title"]),
                "prompt": json.loads(str(row["prompt_json"])),
                "private": json.loads(str(row["private_json"])),
                "consistency_control": bool(row["consistency_control"]),
                "status": str(row["status"]),
                "answer": json.loads(str(row["answer_json"])),
                "note": str(row["note"]),
                "revisit": bool(row["revisit"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def backup(self, *, reason: str = "manual") -> Path:
        if self.read_only:
            raise RuntimeError("cannot back up a failed database in recovery mode")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = self.backup_dir / f"human_review-{reason}-{stamp}.sqlite"
        with self._write_lock:
            if self._writer is None:
                raise RuntimeError("Human Review repository has no writable connection")
            self._writer.execute("PRAGMA wal_checkpoint(FULL)")
            with closing(self._connect()) as source, closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
        return target

    def close(self) -> Path | None:
        if self._closed:
            return None
        backup = None if self.read_only or not self.db_path.exists() else self.backup(reason="close")
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._closed = True
        return backup

    def __del__(self) -> None:
        writer = getattr(self, "_writer", None)
        if writer is not None:
            try:
                writer.close()
            except sqlite3.Error:
                pass
