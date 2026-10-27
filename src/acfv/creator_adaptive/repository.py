from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable, Iterator, Mapping
from uuid import uuid4

from acfv.runtime.storage import storage_root


SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreatorAdaptiveRepository:
    """Forward-only persistence owned by the creator-adaptive capabilities.

    It may share the Library SQLite file, but it never mutates raw media or existing
    transcript tables. Every derived row retains recording and profile provenance.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or storage_root() / "acfv.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.bootstrap()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def bootstrap(self) -> None:
        statements = (
            "CREATE TABLE IF NOT EXISTS creator_adaptive_schema_state(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, updated_at TEXT NOT NULL)",
            """CREATE TABLE IF NOT EXISTS creator_identity_profiles(
                creator_id TEXT NOT NULL, profile_version TEXT NOT NULL, visual_status TEXT NOT NULL DEFAULT 'NOT_BUILT',
                voice_status TEXT NOT NULL DEFAULT 'NOT_BUILT', trusted_speech_status TEXT NOT NULL DEFAULT 'NOT_BUILT',
                lexicon_status TEXT NOT NULL DEFAULT 'NOT_BUILT', adaptive_learning_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(creator_id,profile_version))""",
            """CREATE TABLE IF NOT EXISTS creator_identity_observations(
                id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                candidate_creator_id TEXT NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
                provider TEXT NOT NULL, model_version TEXT NOT NULL, evidence_ref TEXT NOT NULL DEFAULT '',
                raw_metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS ix_identity_observation_span ON creator_identity_observations(recording_id,start_ms,end_ms)",
            """CREATE TABLE IF NOT EXISTS avatar_label_mappings(
                id TEXT PRIMARY KEY, mapping_version TEXT NOT NULL, model_version TEXT NOT NULL,
                external_label TEXT NOT NULL, creator_id TEXT, status TEXT NOT NULL,
                provenance_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(mapping_version,model_version,external_label))""",
            """CREATE TABLE IF NOT EXISTS avatar_identity_observations(
                id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, timestamp_ms INTEGER NOT NULL,
                external_label TEXT NOT NULL, candidate_creator_id TEXT, confidence REAL NOT NULL,
                frame_quality REAL NOT NULL, bbox_json TEXT NOT NULL, track_id TEXT,
                provider TEXT NOT NULL, model_version TEXT NOT NULL, mapping_version TEXT NOT NULL,
                raw_metadata_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS ix_avatar_observation_recording ON avatar_identity_observations(recording_id,timestamp_ms)",
            """CREATE TABLE IF NOT EXISTS creator_visual_identity_spans(
                id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                creator_id TEXT, external_label TEXT NOT NULL, level TEXT NOT NULL,
                median_confidence REAL NOT NULL, support_frames INTEGER NOT NULL, conflict_frames INTEGER NOT NULL,
                coverage REAL NOT NULL, model_version TEXT NOT NULL, mapping_version TEXT NOT NULL,
                created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS creator_identity_decisions(
                id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                state TEXT NOT NULL, creator_id TEXT, visual_score REAL NOT NULL, voice_score REAL NOT NULL,
                recording_prior REAL NOT NULL, human_evidence INTEGER NOT NULL, reason TEXT NOT NULL,
                profile_version TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS creator_visual_exemplars(
                id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, recording_id TEXT NOT NULL, frame_locator TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL, confidence REAL NOT NULL, model_version TEXT NOT NULL,
                quality REAL NOT NULL, embedding_locator TEXT, profile_version TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS creator_voice_exemplars(
                id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, recording_id TEXT NOT NULL, start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL, audio_locator TEXT NOT NULL, embedding_json TEXT NOT NULL,
                duration_ms INTEGER NOT NULL, speech_quality REAL NOT NULL, identity_confidence REAL NOT NULL,
                asr_confidence REAL NOT NULL, overlap_status TEXT NOT NULL, music_status TEXT NOT NULL,
                trust_level TEXT NOT NULL, profile_version TEXT NOT NULL, temporal_region TEXT NOT NULL, created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS ix_voice_exemplar_creator ON creator_voice_exemplars(creator_id,profile_version,trust_level)",
            """CREATE TABLE IF NOT EXISTS trusted_speech_units(
                id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, recording_id TEXT NOT NULL, start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL, audio_locator TEXT NOT NULL, raw_asr TEXT NOT NULL, normalized_text TEXT NOT NULL,
                word_timestamps_json TEXT NOT NULL, speaker_identity_confidence REAL NOT NULL,
                visual_identity_confidence REAL NOT NULL, asr_confidence REAL NOT NULL, redecode_agreement REAL NOT NULL,
                trust_level TEXT NOT NULL, provenance_json TEXT NOT NULL, profile_version TEXT NOT NULL,
                created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS ix_trusted_speech_creator ON trusted_speech_units(creator_id,profile_version,trust_level)",
            """CREATE TABLE IF NOT EXISTS creator_lexicon_entries(
                id TEXT PRIMARY KEY, creator_id TEXT, text TEXT NOT NULL, normalized_text TEXT NOT NULL,
                type TEXT NOT NULL, frequency INTEGER NOT NULL, trusted_occurrences INTEGER NOT NULL,
                human_confirmed_occurrences INTEGER NOT NULL, confidence REAL NOT NULL, last_seen TEXT NOT NULL,
                scope TEXT NOT NULL, scope_key TEXT NOT NULL DEFAULT '', profile_version TEXT NOT NULL,
                provenance_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(creator_id,normalized_text,scope,scope_key,profile_version))""",
            """CREATE TABLE IF NOT EXISTS creator_acoustic_exemplars(
                id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, text TEXT NOT NULL, normalized_text TEXT NOT NULL,
                audio_locator TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                word_start_ms INTEGER NOT NULL, word_end_ms INTEGER NOT NULL, source_recording TEXT NOT NULL,
                trust_level TEXT NOT NULL, asr_confidence REAL NOT NULL, human_confirmed INTEGER NOT NULL,
                context TEXT NOT NULL, game_scope TEXT NOT NULL, profile_version TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS adaptive_transcript_decisions(
                id TEXT PRIMARY KEY, recording_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
                creator_id TEXT, identity_state TEXT NOT NULL, generic_text TEXT NOT NULL, adaptive_text TEXT NOT NULL,
                action TEXT NOT NULL, evidence_json TEXT NOT NULL, profile_version TEXT NOT NULL, shadow INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL)""",
            "CREATE TABLE IF NOT EXISTS creator_adaptive_settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at TEXT NOT NULL)",
        )
        with self.transaction() as connection:
            for statement in statements:
                connection.execute(statement)
            row = connection.execute("SELECT version FROM creator_adaptive_schema_state WHERE id=1").fetchone()
            if row and int(row[0]) > SCHEMA_VERSION:
                raise RuntimeError(f"Creator adaptive schema {row[0]} is newer than supported {SCHEMA_VERSION}")
            connection.execute(
                "INSERT INTO creator_adaptive_schema_state(id,version,updated_at) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at",
                (SCHEMA_VERSION, _now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO creator_adaptive_settings(key,value_json,updated_at) VALUES('creator_adaptation_enabled','false',?)",
                (_now(),),
            )

    def setting(self, key: str, default: Any = None) -> Any:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT value_json FROM creator_adaptive_settings WHERE key=?", (key,)).fetchone()
        return json.loads(str(row[0])) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO creator_adaptive_settings(key,value_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True), _now()),
            )

    def ensure_profile(self, creator_id: str, profile_version: str, **statuses: str) -> None:
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO creator_identity_profiles(
                creator_id,profile_version,created_at,updated_at) VALUES(?,?,?,?)""",
                (creator_id, profile_version, now, now),
            )
            allowed = {"visual_status", "voice_status", "trusted_speech_status", "lexicon_status"}
            for key, value in statuses.items():
                if key not in allowed:
                    raise ValueError(f"unsupported profile status: {key}")
                connection.execute(
                    f"UPDATE creator_identity_profiles SET {key}=?,updated_at=? WHERE creator_id=? AND profile_version=?",
                    (value, now, creator_id, profile_version),
                )

    def latest_profile(self, creator_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM creator_identity_profiles WHERE creator_id=? ORDER BY created_at DESC LIMIT 1",
                (creator_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_row(self, table: str, values: Mapping[str, Any]) -> str:
        allowed = {
            "creator_identity_observations", "creator_identity_decisions", "creator_visual_exemplars",
            "creator_voice_exemplars", "trusted_speech_units", "creator_lexicon_entries",
            "creator_acoustic_exemplars", "adaptive_transcript_decisions",
            "avatar_label_mappings", "avatar_identity_observations", "creator_visual_identity_spans",
        }
        if table not in allowed:
            raise ValueError(f"unsupported creator-adaptive table: {table}")
        payload = dict(values)
        if not payload.get("id"):
            payload["id"] = str(uuid4())
        payload.setdefault("created_at", _now())
        columns = tuple(payload)
        placeholders = ",".join("?" for _ in columns)
        with self.transaction() as connection:
            connection.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
                tuple(payload[column] for column in columns),
            )
        return str(payload["id"])

    def rows(self, table: str, *, where: str = "", params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        allowed = {
            "creator_identity_profiles", "creator_identity_observations", "creator_identity_decisions",
            "creator_visual_exemplars", "creator_voice_exemplars", "trusted_speech_units",
            "creator_lexicon_entries", "creator_acoustic_exemplars", "adaptive_transcript_decisions",
            "avatar_label_mappings", "avatar_identity_observations", "creator_visual_identity_spans",
        }
        if table not in allowed:
            raise ValueError(f"unsupported creator-adaptive table: {table}")
        sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "")
        with closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]

    def profile_summary(self, creator_id: str) -> dict[str, Any]:
        profile = self.latest_profile(creator_id)
        if not profile:
            return {"creator_id": creator_id, "status": "NOT_BUILT", "profile_version": ""}
        version = str(profile["profile_version"])
        voice = self.rows("creator_voice_exemplars", where="creator_id=? AND profile_version=?", params=(creator_id, version))
        speech = self.rows("trusted_speech_units", where="creator_id=? AND profile_version=?", params=(creator_id, version))
        lexicon = self.rows("creator_lexicon_entries", where="creator_id=? AND profile_version=?", params=(creator_id, version))
        return {
            **profile,
            "status": "READY" if all(profile[key] == "READY" for key in ("visual_status", "voice_status", "trusted_speech_status", "lexicon_status")) else "NEEDS_REVIEW",
            "voice_exemplars": len(voice),
            "trusted_speech_units": len(speech),
            "trusted_speech_duration_ms": sum(int(row["end_ms"]) - int(row["start_ms"]) for row in speech),
            "human_confirmed": sum(row["trust_level"] == "HUMAN_CONFIRMED" for row in speech),
            "lexicon_entries": len(lexicon),
        }
