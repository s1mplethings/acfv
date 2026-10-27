from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Clip, UserInteraction, UserPreference

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    clip_id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    duration REAL NOT NULL,
    summary_text TEXT,
    raw_text TEXT,
    tags_json TEXT,
    highlight_score REAL,
    emotion_score REAL,
    talk_ratio REAL,
    extra_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT PRIMARY KEY,
    tag_weights_json TEXT,
    feature_prefs_json TEXT,
    pref_embedding BLOB,
    raw_preference_text TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_clip_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    clip_id INTEGER NOT NULL,
    feedback_type TEXT NOT NULL,
    watch_ratio REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def insert_clip(db_path: Path, clip: Clip) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO clips (
                video_id, start_sec, end_sec, duration, summary_text, raw_text,
                tags_json, highlight_score, emotion_score, talk_ratio, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip.video_id,
                clip.start_sec,
                clip.end_sec,
                clip.duration,
                clip.summary_text,
                clip.raw_text,
                json.dumps(clip.tags, ensure_ascii=False) if clip.tags else None,
                clip.highlight_score,
                clip.emotion_score,
                clip.talk_ratio,
                json.dumps(clip.extra, ensure_ascii=False) if clip.extra else None,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_clips(db_path: Path, clip_ids: Iterable[int]) -> List[Clip]:
    ids = list(clip_ids)
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    query = f"SELECT * FROM clips WHERE clip_id IN ({placeholders})"
    with _connect(db_path) as conn:
        rows = conn.execute(query, ids).fetchall()
    clips: List[Clip] = []
    for row in rows:
        clips.append(
            Clip(
                clip_id=row["clip_id"],
                video_id=row["video_id"],
                start_sec=row["start_sec"],
                end_sec=row["end_sec"],
                duration=row["duration"],
                summary_text=row["summary_text"],
                raw_text=row["raw_text"],
                tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
                highlight_score=row["highlight_score"],
                emotion_score=row["emotion_score"],
                talk_ratio=row["talk_ratio"],
                extra=json.loads(row["extra_json"]) if row["extra_json"] else {},
                created_at=row["created_at"],
            )
        )
    return clips


def insert_interaction(db_path: Path, interaction: UserInteraction) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_clip_interactions (user_id, clip_id, feedback_type, watch_ratio)
            VALUES (?, ?, ?, ?)
            """,
            (
                interaction.user_id,
                interaction.clip_id,
                interaction.feedback_type,
                interaction.watch_ratio,
            ),
        )
        conn.commit()


def get_user_pref(db_path: Path, user_id: str) -> Optional[UserPreference]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return None
    return UserPreference(
        user_id=row["user_id"],
        tag_weights=json.loads(row["tag_weights_json"]) if row["tag_weights_json"] else {},
        feature_prefs=json.loads(row["feature_prefs_json"]) if row["feature_prefs_json"] else {},
        pref_embedding=row["pref_embedding"],
        raw_preference_text=row["raw_preference_text"],
        updated_at=row["updated_at"],
    )


def save_user_pref(db_path: Path, pref: UserPreference) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO user_preferences (
                user_id, tag_weights_json, feature_prefs_json,
                pref_embedding, raw_preference_text, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                tag_weights_json=excluded.tag_weights_json,
                feature_prefs_json=excluded.feature_prefs_json,
                pref_embedding=excluded.pref_embedding,
                raw_preference_text=excluded.raw_preference_text,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                pref.user_id,
                json.dumps(pref.tag_weights, ensure_ascii=False),
                json.dumps(pref.feature_prefs, ensure_ascii=False),
                pref.pref_embedding,
                pref.raw_preference_text,
            ),
        )
        conn.commit()
