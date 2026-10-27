from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, String, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RecordingStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    RECORDING = "RECORDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class DownloadStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    DOWNLOAD_PENDING = "DOWNLOAD_PENDING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    PROCESSING = "PROCESSING"
    READY = "READY"


class ProcessingStatus(str, Enum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class IndexStatus(str, Enum):
    NOT_INDEXED = "NOT_INDEXED"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"


class ClipRenderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RENDERING = "RENDERING"
    READY = "READY"
    FAILED = "FAILED"


class ClipReviewStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class FeedbackDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Creator(SQLModel, table=True):
    __tablename__ = "library_creators"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    legacy_name: Optional[str] = Field(default=None, sa_column=Column("name", String, nullable=True))
    display_name: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    avatar_url: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Source(SQLModel, table=True):
    __tablename__ = "library_sources"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_library_source_platform_external"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    creator_id: str = Field(foreign_key="library_creators.id", index=True)
    platform: str = Field(default="twitch", index=True)
    source_type: str = Field(default="live_channel", index=True)
    external_id: str = Field(index=True)
    channel_name: str
    channel_url: Optional[str] = None
    enabled: bool = True
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Recording(SQLModel, table=True):
    __tablename__ = "library_recordings"
    __table_args__ = (UniqueConstraint("canonical_path", name="uq_library_recording_path"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    creator_id: str = Field(foreign_key="library_creators.id", index=True)
    source_id: Optional[str] = Field(default=None, foreign_key="library_sources.id", index=True)
    title: str
    source_type: str = Field(default="local", index=True)
    source_url: Optional[str] = None
    external_vod_id: Optional[str] = Field(default=None, index=True)
    provider: Optional[str] = None
    download_metadata_json: str = "{}"
    is_partial_source: bool = False
    source_start_offset_ms: Optional[int] = None
    source_end_offset_ms: Optional[int] = None
    local_path: Optional[str] = None
    canonical_path: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    recording_status: RecordingStatus = Field(default=RecordingStatus.DISCOVERED, index=True)
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.NEW, index=True)
    index_status: IndexStatus = Field(default=IndexStatus.NOT_INDEXED, index=True)
    content_type: str = Field(default="other", index=True)
    analysis_profile_json: str = "{}"
    profile_source: str = "automatic"
    artifact_root: Optional[str] = None
    last_job_id: Optional[str] = None
    file_size: Optional[int] = None
    file_mtime_ns: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class VodDownload(SQLModel, table=True):
    __tablename__ = "library_vod_downloads"
    __table_args__ = (
        UniqueConstraint("platform", "external_vod_id", name="uq_vod_download_platform_external"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    platform: str = Field(default="twitch", index=True)
    external_vod_id: str = Field(index=True)
    recording_id: Optional[str] = Field(default=None, foreign_key="library_recordings.id", index=True)
    source_url: str
    provider: str = "twitch-downloader"
    status: DownloadStatus = Field(default=DownloadStatus.DISCOVERED, index=True)
    requested_start_ms: Optional[int] = None
    requested_end_ms: Optional[int] = None
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    percent: Optional[float] = None
    speed_bps: Optional[float] = None
    eta_seconds: Optional[float] = None
    retry_count: int = 0
    temp_path: Optional[str] = None
    final_path: Optional[str] = None
    metadata_json: str = "{}"
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class LibraryFolder(SQLModel, table=True):
    __tablename__ = "library_folders"
    __table_args__ = (UniqueConstraint("canonical_path", name="uq_library_folder_path"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    creator_id: str = Field(foreign_key="library_creators.id", index=True)
    path: str
    canonical_path: str = Field(index=True)
    enabled: bool = True
    watch_enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Clip(SQLModel, table=True):
    __tablename__ = "library_clips"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    creator_id: str = Field(foreign_key="library_creators.id", index=True)
    recording_id: str = Field(foreign_key="library_recordings.id", index=True)
    moment_id: str = Field(foreign_key="library_moments.id", index=True)
    query: str = ""
    original_start_ms: int
    original_end_ms: int
    proposed_start_ms: int
    proposed_end_ms: int
    final_start_ms: int
    final_end_ms: int
    reason: str = ""
    subtitle_text: str = ""
    subtitle_style_json: str = "{}"
    render_status: ClipRenderStatus = Field(default=ClipRenderStatus.PROPOSED, index=True)
    output_path: Optional[str] = None
    review_status: ClipReviewStatus = Field(default=ClipReviewStatus.PENDING, index=True)
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Feedback(SQLModel, table=True):
    __tablename__ = "library_feedback"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    clip_id: str = Field(foreign_key="library_clips.id", index=True)
    moment_id: str = Field(foreign_key="library_moments.id", index=True)
    creator_id: str = Field(foreign_key="library_creators.id", index=True)
    query: str = ""
    decision: FeedbackDecision = Field(index=True)
    original_start_ms: int
    original_end_ms: int
    final_start_ms: int
    final_end_ms: int
    boundary_delta_start: int
    boundary_delta_end: int
    subtitle_edit: str = ""
    reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ExplicitPreference(SQLModel, table=True):
    __tablename__ = "library_explicit_preferences"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    creator_id: Optional[str] = Field(default=None, foreign_key="library_creators.id", index=True)
    text: str
    source: str = "USER_EXPLICIT"
    created_at: datetime = Field(default_factory=utc_now)


class LibrarySchemaState(SQLModel, table=True):
    __tablename__ = "library_schema_state"

    id: int = Field(default=1, primary_key=True)
    version: int = Field(default=7)
    updated_at: datetime = Field(default_factory=utc_now)
