from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import delete, inspect, or_, text
from sqlmodel import Session, SQLModel, create_engine, select

from acfv.runtime.storage import storage_root

from .models import (
    Creator,
    Clip,
    ExplicitPreference,
    Feedback,
    IndexStatus,
    LibraryFolder,
    LibrarySchemaState,
    ProcessingStatus,
    Recording,
    RecordingStatus,
    Source,
    VodDownload,
    DownloadStatus,
    utc_now,
)
from acfv.moments.models import Moment, MomentStatus

SCHEMA_VERSION = 7
DEFAULT_CREATOR_NAME = "Default Creator"
DEFAULT_CREATOR_SLUG = "default"


class LibraryRepository:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or storage_root() / "acfv.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )

    def bootstrap(self) -> None:
        SQLModel.metadata.create_all(self.engine)
        self._migrate_legacy_creator_names()
        self._migrate_recording_download_columns()
        self._migrate_feedback_review_columns()
        with Session(self.engine) as session:
            state = session.get(LibrarySchemaState, 1)
            if state is None:
                session.add(LibrarySchemaState(id=1, version=SCHEMA_VERSION))
            elif state.version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Library database schema {state.version} is newer than supported {SCHEMA_VERSION}"
                )
            else:
                state.version = SCHEMA_VERSION
                state.updated_at = utc_now()
                session.add(state)
            self._recover_interrupted(session)
            session.commit()

    def _migrate_legacy_creator_names(self) -> None:
        columns = {column["name"] for column in inspect(self.engine).get_columns("library_creators")}
        with self.engine.begin() as connection:
            if "display_name" not in columns:
                connection.execute(text("ALTER TABLE library_creators ADD COLUMN display_name VARCHAR"))
            if "slug" not in columns:
                connection.execute(text("ALTER TABLE library_creators ADD COLUMN slug VARCHAR"))
            if "avatar_url" not in columns:
                connection.execute(text("ALTER TABLE library_creators ADD COLUMN avatar_url VARCHAR"))
            if "name" in columns:
                connection.execute(text("UPDATE library_creators SET display_name = COALESCE(display_name, name)"))
            connection.execute(text("UPDATE library_creators SET display_name = COALESCE(display_name, 'Default Creator')"))
            connection.execute(text("UPDATE library_creators SET slug = COALESCE(slug, 'creator-' || substr(id, 1, 8))"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_library_creators_slug ON library_creators (slug)"))

    def _migrate_recording_download_columns(self) -> None:
        columns = {column["name"] for column in inspect(self.engine).get_columns("library_recordings")}
        migrations = {
            "external_vod_id": "ALTER TABLE library_recordings ADD COLUMN external_vod_id VARCHAR",
            "provider": "ALTER TABLE library_recordings ADD COLUMN provider VARCHAR",
            "download_metadata_json": "ALTER TABLE library_recordings ADD COLUMN download_metadata_json VARCHAR NOT NULL DEFAULT '{}'",
            "is_partial_source": "ALTER TABLE library_recordings ADD COLUMN is_partial_source BOOLEAN NOT NULL DEFAULT 0",
            "source_start_offset_ms": "ALTER TABLE library_recordings ADD COLUMN source_start_offset_ms INTEGER",
            "source_end_offset_ms": "ALTER TABLE library_recordings ADD COLUMN source_end_offset_ms INTEGER",
        }
        with self.engine.begin() as connection:
            for name, statement in migrations.items():
                if name not in columns:
                    connection.execute(text(statement))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_library_recordings_external_vod_id "
                "ON library_recordings (external_vod_id) WHERE external_vod_id IS NOT NULL"
            ))

    def _migrate_feedback_review_columns(self) -> None:
        columns = {column["name"] for column in inspect(self.engine).get_columns("library_feedback")}
        migrations = {
            "subtitle_edit": "ALTER TABLE library_feedback ADD COLUMN subtitle_edit VARCHAR NOT NULL DEFAULT ''",
            "reason": "ALTER TABLE library_feedback ADD COLUMN reason VARCHAR NOT NULL DEFAULT ''",
        }
        with self.engine.begin() as connection:
            for name, statement in migrations.items():
                if name not in columns:
                    connection.execute(text(statement))

    @staticmethod
    def _recover_interrupted(session: Session) -> None:
        stale = session.exec(
            select(Recording).where(
                (Recording.recording_status == RecordingStatus.RECORDING)
                | (Recording.processing_status == ProcessingStatus.PROCESSING)
                | (Recording.index_status == IndexStatus.INDEXING)
            )
        ).all()
        for recording in stale:
            if recording.recording_status == RecordingStatus.RECORDING:
                recording.recording_status = RecordingStatus.FAILED
            if recording.processing_status == ProcessingStatus.PROCESSING:
                recording.processing_status = ProcessingStatus.FAILED
            if recording.index_status == IndexStatus.INDEXING:
                recording.index_status = IndexStatus.FAILED
            recording.error_message = "Application stopped before the operation completed"
            recording.updated_at = utc_now()
            session.add(recording)
        downloads = session.exec(
            select(VodDownload).where(
                (VodDownload.status == DownloadStatus.DOWNLOADING)
                | (VodDownload.status == DownloadStatus.DOWNLOAD_PENDING)
            )
        ).all()
        for download in downloads:
            download.status = DownloadStatus.INTERRUPTED
            download.error_message = "Application stopped before the download completed"
            download.updated_at = utc_now()
            session.add(download)

    def save(self, value):
        with Session(self.engine) as session:
            merged = session.merge(value)
            session.commit()
            session.refresh(merged)
            return merged

    def get_creator(self, creator_id: str) -> Optional[Creator]:
        with Session(self.engine) as session:
            return session.get(Creator, creator_id)

    def get_creator_by_slug(self, slug: str) -> Optional[Creator]:
        with Session(self.engine) as session:
            return session.exec(select(Creator).where(Creator.slug == slug)).first()

    def list_creators(self) -> list[Creator]:
        with Session(self.engine) as session:
            return list(session.exec(select(Creator).order_by(Creator.display_name)).all())

    def default_creator(self) -> Creator:
        creator = self.get_creator_by_slug(DEFAULT_CREATOR_SLUG)
        if creator is not None:
            return creator
        return self.save(Creator(display_name=DEFAULT_CREATOR_NAME, slug=DEFAULT_CREATOR_SLUG, legacy_name=DEFAULT_CREATOR_NAME))

    def get_source(self, source_id: str) -> Optional[Source]:
        with Session(self.engine) as session:
            return session.get(Source, source_id)

    def get_source_by_external(self, platform: str, external_id: str) -> Optional[Source]:
        with Session(self.engine) as session:
            return session.exec(
                select(Source).where(Source.platform == platform, Source.external_id == external_id)
            ).first()

    def list_sources(self, creator_id: Optional[str] = None) -> list[Source]:
        with Session(self.engine) as session:
            statement = select(Source)
            if creator_id:
                statement = statement.where(Source.creator_id == creator_id)
            return list(session.exec(statement.order_by(Source.created_at)).all())

    def get_recording(self, recording_id: str) -> Optional[Recording]:
        with Session(self.engine) as session:
            return session.get(Recording, recording_id)

    def get_recording_by_path(self, canonical_path: str) -> Optional[Recording]:
        with Session(self.engine) as session:
            return session.exec(
                select(Recording).where(Recording.canonical_path == canonical_path)
            ).first()

    def get_recording_by_external_vod_id(self, external_vod_id: str) -> Optional[Recording]:
        with Session(self.engine) as session:
            return session.exec(
                select(Recording).where(Recording.external_vod_id == external_vod_id)
            ).first()

    def get_vod_download(self, download_id: str) -> Optional[VodDownload]:
        with Session(self.engine) as session:
            return session.get(VodDownload, download_id)

    def get_vod_download_by_external(self, platform: str, external_vod_id: str) -> Optional[VodDownload]:
        with Session(self.engine) as session:
            return session.exec(
                select(VodDownload).where(
                    VodDownload.platform == platform,
                    VodDownload.external_vod_id == external_vod_id,
                )
            ).first()

    def list_vod_downloads(self) -> list[VodDownload]:
        with Session(self.engine) as session:
            return list(session.exec(select(VodDownload).order_by(VodDownload.created_at.desc())).all())

    def list_recordings(self, creator_id: Optional[str] = None) -> list[Recording]:
        with Session(self.engine) as session:
            statement = select(Recording)
            if creator_id:
                statement = statement.where(Recording.creator_id == creator_id)
            return list(session.exec(statement.order_by(Recording.created_at.desc())).all())

    def get_moment(self, moment_id: str) -> Optional[Moment]:
        with Session(self.engine) as session:
            return session.get(Moment, moment_id)

    def get_moment_by_stable_key(self, stable_key: str) -> Optional[Moment]:
        with Session(self.engine) as session:
            return session.exec(select(Moment).where(Moment.stable_key == stable_key)).first()

    def moment_has_product_references(self, moment_id: str) -> bool:
        with Session(self.engine) as session:
            clip = session.exec(select(Clip).where(Clip.moment_id == moment_id)).first()
            feedback = session.exec(select(Feedback).where(Feedback.moment_id == moment_id)).first()
            return clip is not None or feedback is not None

    def delete_moments(self, moment_ids: list[str]) -> int:
        if not moment_ids:
            return 0
        with Session(self.engine) as session:
            result = session.exec(delete(Moment).where(Moment.id.in_(moment_ids)))
            session.commit()
            return int(result.rowcount or 0)

    def list_moments(
        self,
        *,
        creator_id: Optional[str] = None,
        recording_id: Optional[str] = None,
        status: Optional[MomentStatus] = None,
    ) -> list[Moment]:
        with Session(self.engine) as session:
            statement = select(Moment)
            if creator_id:
                statement = statement.where(Moment.creator_id == creator_id)
            if recording_id:
                statement = statement.where(Moment.recording_id == recording_id)
            if status:
                statement = statement.where(Moment.status == status)
            return list(session.exec(statement.order_by(Moment.start_ms)).all())

    def get_clip(self, clip_id: str) -> Optional[Clip]:
        with Session(self.engine) as session:
            return session.get(Clip, clip_id)

    def list_clips(self, creator_id: Optional[str] = None) -> list[Clip]:
        with Session(self.engine) as session:
            statement = select(Clip)
            if creator_id:
                statement = statement.where(Clip.creator_id == creator_id)
            return list(session.exec(statement.order_by(Clip.created_at.desc())).all())

    def list_feedback(self, creator_id: Optional[str] = None) -> list[Feedback]:
        with Session(self.engine) as session:
            statement = select(Feedback)
            if creator_id:
                statement = statement.where(Feedback.creator_id == creator_id)
            return list(session.exec(statement.order_by(Feedback.created_at.desc())).all())

    def list_preferences(self, creator_id: Optional[str] = None) -> list[ExplicitPreference]:
        with Session(self.engine) as session:
            statement = select(ExplicitPreference)
            if creator_id:
                statement = statement.where(or_(ExplicitPreference.creator_id == creator_id, ExplicitPreference.creator_id.is_(None)))
            else:
                statement = statement.where(ExplicitPreference.creator_id.is_(None))
            return list(session.exec(statement.order_by(ExplicitPreference.created_at)).all())

    def delete_recording_moments_except(self, recording_id: str, keep_ids: list[str]) -> None:
        with Session(self.engine) as session:
            statement = delete(Moment).where(Moment.recording_id == recording_id)
            if keep_ids:
                statement = statement.where(Moment.id.not_in(keep_ids))
            session.exec(statement)
            session.commit()

    def get_folder_by_path(self, canonical_path: str) -> Optional[LibraryFolder]:
        with Session(self.engine) as session:
            return session.exec(
                select(LibraryFolder).where(LibraryFolder.canonical_path == canonical_path)
            ).first()

    def list_folders(self) -> list[LibraryFolder]:
        with Session(self.engine) as session:
            return list(session.exec(select(LibraryFolder).order_by(LibraryFolder.created_at)).all())
