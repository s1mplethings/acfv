from __future__ import annotations

from typing import Any

from acfv.library.models import utc_now
from acfv.library.repository import LibraryRepository

from .builder import ProvisionalMomentBuilder
from .models import Moment, MomentStatus


class MomentService:
    def __init__(self, repository: LibraryRepository, *, builder: ProvisionalMomentBuilder | None = None) -> None:
        self.repository = repository
        self.builder = builder or ProvisionalMomentBuilder()

    def ingest_incremental(self, recording_id: str, transcript_payload: dict[str, Any], chat_payload: dict[str, Any] | None = None, *, transcript_artifact: str | None = None, chat_artifact: str | None = None) -> list[Moment]:
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        results = []
        for draft in self.builder.build(
            transcript_payload,
            chat_payload,
            transcript_artifact=transcript_artifact,
            chat_artifact=chat_artifact,
            suppress_low_information=False,
        ):
            stable_key = f"{recording.id}:provisional:{draft.start_ms}"
            moment = self.repository.get_moment_by_stable_key(stable_key)
            if moment is None:
                moment = Moment(stable_key=stable_key, creator_id=recording.creator_id, recording_id=recording.id, start_ms=draft.start_ms, end_ms=draft.end_ms, status=MomentStatus.PROVISIONAL)
            else:
                moment.revision += 1
                moment.end_ms = draft.end_ms
            moment.transcript_text = draft.transcript_text
            moment.chat_text = draft.chat_text
            moment.summary = draft.transcript_text
            moment.evidence_json = draft.evidence_json
            moment.updated_at = utc_now()
            results.append(self.repository.save(moment))
        return results

    def list_moments(self, *, creator_id: str | None = None, recording_id: str | None = None) -> list[Moment]:
        return self.repository.list_moments(creator_id=creator_id, recording_id=recording_id)

    def search_live(self, query: str, *, creator_id: str | None = None, recording_id: str | None = None) -> list[Moment]:
        terms = [term.casefold() for term in query.split() if term.strip()]
        if not terms:
            return []
        candidates = self.repository.list_moments(creator_id=creator_id, recording_id=recording_id, status=MomentStatus.PROVISIONAL)
        return [moment for moment in candidates if all(term in f"{moment.summary} {moment.transcript_text} {moment.chat_text}".casefold() for term in terms)]
