from __future__ import annotations

import json

from acfv.library.models import (
    ClipReviewStatus,
    ExplicitPreference,
    Feedback,
    FeedbackDecision,
    utc_now,
)
from acfv.library.repository import LibraryRepository


class FeedbackService:
    def __init__(self, repository: LibraryRepository) -> None:
        self.repository = repository

    def decide(
        self,
        clip_id: str,
        decision: FeedbackDecision,
        *,
        reason: str = "",
        subtitle_edit: str | None = None,
    ) -> Feedback:
        clip = self.repository.get_clip(clip_id)
        if clip is None:
            raise KeyError(f"Unknown clip: {clip_id}")
        clip.review_status = (
            ClipReviewStatus.ACCEPTED
            if decision == FeedbackDecision.ACCEPTED
            else ClipReviewStatus.REJECTED
        )
        clip.updated_at = utc_now()
        self.repository.save(clip)
        return self.repository.save(
            Feedback(
                clip_id=clip.id,
                moment_id=clip.moment_id,
                creator_id=clip.creator_id,
                query=clip.query,
                decision=decision,
                original_start_ms=clip.original_start_ms,
                original_end_ms=clip.original_end_ms,
                final_start_ms=clip.final_start_ms,
                final_end_ms=clip.final_end_ms,
                boundary_delta_start=clip.final_start_ms - clip.original_start_ms,
                boundary_delta_end=clip.final_end_ms - clip.original_end_ms,
                subtitle_edit=clip.subtitle_text if subtitle_edit is None else subtitle_edit.strip(),
                reason=reason.strip(),
            )
        )

    def add_preference(self, text: str, *, creator_id: str | None = None) -> ExplicitPreference:
        value = text.strip()
        if not value:
            raise ValueError("Preference text is required")
        if creator_id and self.repository.get_creator(creator_id) is None:
            raise KeyError(f"Unknown creator: {creator_id}")
        return self.repository.save(
            ExplicitPreference(creator_id=creator_id, text=value, source="USER_EXPLICIT")
        )

    def add_translation_preference(self, source_phrase: str, preferred_translation: str, *,
                                   creator_id: str | None = None, game_scope: str = "",
                                   recording_scope: str = "") -> ExplicitPreference:
        source = source_phrase.strip()
        preferred = preferred_translation.strip()
        if not source or not preferred:
            raise ValueError("Source phrase and preferred translation are required")
        if creator_id and self.repository.get_creator(creator_id) is None:
            raise KeyError(f"Unknown creator: {creator_id}")
        payload = json.dumps({
            "source_phrase": source, "preferred_translation": preferred,
            "creator_scope": creator_id, "game_scope": game_scope.strip(),
            "recording_scope": recording_scope.strip(),
        }, ensure_ascii=False, sort_keys=True)
        return self.repository.save(ExplicitPreference(
            creator_id=creator_id, text=payload, source="USER_EXPLICIT_TRANSLATION_PREFERENCE",
        ))

    def translation_preferences(self, *, creator_id: str | None = None,
                                game_scope: str = "", recording_scope: str = "") -> dict[str, str]:
        matches: dict[str, tuple[int, str]] = {}
        for item in self.repository.list_preferences(creator_id):
            if item.source != "USER_EXPLICIT_TRANSLATION_PREFERENCE":
                continue
            try:
                payload = json.loads(item.text)
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("creator_scope") not in {None, creator_id}:
                continue
            if payload.get("game_scope") and payload.get("game_scope") != game_scope:
                continue
            if payload.get("recording_scope") and payload.get("recording_scope") != recording_scope:
                continue
            specificity = sum(bool(payload.get(key)) for key in ("creator_scope", "game_scope", "recording_scope"))
            source = str(payload.get("source_phrase") or "").strip()
            preferred = str(payload.get("preferred_translation") or "").strip()
            if source and preferred and specificity >= matches.get(source, (-1, ""))[0]:
                matches[source] = (specificity, preferred)
        return {source: value for source, (_, value) in matches.items()}

    def list_feedback(self, creator_id: str | None = None) -> list[Feedback]:
        return self.repository.list_feedback(creator_id)

    def list_preferences(self, creator_id: str | None = None) -> list[ExplicitPreference]:
        return self.repository.list_preferences(creator_id)
