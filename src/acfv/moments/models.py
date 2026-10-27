from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from acfv.library.models import utc_now


class MomentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZING = "FINALIZING"
    FINAL = "FINAL"


class Moment(SQLModel, table=True):
    __tablename__ = "library_moments"
    __table_args__ = (UniqueConstraint("stable_key", name="uq_library_moment_stable_key"),)

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    stable_key: str = Field(index=True)
    creator_id: str = Field(foreign_key="library_creators.id", index=True)
    recording_id: str = Field(foreign_key="library_recordings.id", index=True)
    start_ms: int = Field(index=True)
    end_ms: int = Field(index=True)
    status: MomentStatus = Field(default=MomentStatus.PROVISIONAL, index=True)
    title: str = ""
    summary: str = ""
    transcript_text: str = ""
    visual_text: str = ""
    ocr_text: str = ""
    chat_text: str = ""
    speaker_data_json: str = "{}"
    emotion_data_json: str = "{}"
    tags_json: str = "[]"
    evidence_json: str = "[]"
    revision: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finalized_at: Optional[datetime] = None
