from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from acfv.creator_adaptive.models import (
    AdaptiveAction, AdaptiveTranscriptDecision, CreatorIdentityDecision, IdentityState,
)
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository


class CreatorAdaptiveASRService:
    """Evidence-gated shadow layer; the generic transcript remains immutable."""

    def __init__(self, db_path: Path | None = None, *, repository: CreatorAdaptiveRepository | None = None) -> None:
        self.repository = repository or CreatorAdaptiveRepository(db_path)

    @property
    def production_enabled(self) -> bool:
        return bool(self.repository.setting("creator_adaptation_enabled", False))

    def shadow_decide(
        self, *, recording_id: str, start_ms: int, end_ms: int, generic_text: str,
        identity: CreatorIdentityDecision, profile_version: str, base_confidence: float,
        candidate_terms: Iterable[str] = (), historical_evidence: Mapping[str, int] | None = None,
        redecode: Callable[[list[str]], tuple[str, float]] | None = None,
    ) -> AdaptiveTranscriptDecision:
        history = dict(historical_evidence or {})
        candidates = list(dict.fromkeys(term.strip() for term in candidate_terms if term.strip()))
        candidates.sort(key=lambda term: (-int(history.get(term, 0)), term.casefold()))
        candidates = candidates[:30]
        evidence: dict[str, Any] = {"base_confidence": base_confidence, "hotwords": candidates, "historical": history}
        if identity.profile_version and identity.profile_version != profile_version:
            result = AdaptiveTranscriptDecision(
                recording_id, start_ms, end_ms, generic_text, generic_text, AdaptiveAction.GENERIC_FALLBACK,
                None, identity.state, {**evidence, "reason": "profile version mismatch", "comparison": "CONFLICT"}, profile_version,
            )
            return self._persist(result)
        if not identity.allows_creator_memory:
            result = AdaptiveTranscriptDecision(
                recording_id, start_ms, end_ms, generic_text, generic_text, AdaptiveAction.GENERIC_FALLBACK,
                None, identity.state, {**evidence, "reason": "identity does not permit creator memory", "comparison": "CONFLICT"}, profile_version,
            )
            return self._persist(result)
        if redecode is None or not candidates:
            result = AdaptiveTranscriptDecision(
                recording_id, start_ms, end_ms, generic_text, generic_text, AdaptiveAction.UNCHANGED_UNCERTAIN,
                identity.creator_id, identity.state, {**evidence, "reason": "no local redecode or candidates", "comparison": "UNRESOLVED"}, profile_version,
            )
            return self._persist(result)
        try:
            adaptive_text, adaptive_confidence = redecode(candidates)
        except Exception as exc:
            result = AdaptiveTranscriptDecision(
                recording_id, start_ms, end_ms, generic_text, generic_text, AdaptiveAction.GENERIC_FALLBACK,
                identity.creator_id, identity.state, {**evidence, "reason": f"adaptive redecode failed: {type(exc).__name__}", "comparison": "CONFLICT"}, profile_version,
            )
            return self._persist(result)
        evidence["adaptive_confidence"] = adaptive_confidence
        supporting_terms = [term for term in candidates if term.casefold() in adaptive_text.casefold() and history.get(term, 0) >= 2]
        if adaptive_text.strip() == generic_text.strip():
            action = AdaptiveAction.KEEP
            evidence["comparison"] = "SAME"
        elif adaptive_confidence >= max(0.75, base_confidence + 0.05) and supporting_terms:
            action = AdaptiveAction.CORRECT
            evidence["independent_support"] = supporting_terms
            evidence["comparison"] = "ADAPTIVE_CANDIDATE_BETTER"
        else:
            action = AdaptiveAction.REVIEW
            evidence["comparison"] = "UNRESOLVED"
        result = AdaptiveTranscriptDecision(
            recording_id, start_ms, end_ms, generic_text, adaptive_text, action,
            identity.creator_id, identity.state, evidence, profile_version,
        )
        return self._persist(result)

    def _persist(self, result: AdaptiveTranscriptDecision) -> AdaptiveTranscriptDecision:
        identifier = self.repository.add_row("adaptive_transcript_decisions", {
            "id": result.id or None, "recording_id": result.recording_id, "start_ms": result.start_ms,
            "end_ms": result.end_ms, "creator_id": result.creator_id, "identity_state": result.identity_state.value,
            "generic_text": result.generic_text, "adaptive_text": result.adaptive_text, "action": result.action.value,
            "evidence_json": json.dumps(dict(result.evidence), ensure_ascii=False, sort_keys=True),
            "profile_version": result.profile_version, "shadow": 1,
        })
        return AdaptiveTranscriptDecision(**{**result.__dict__, "id": identifier})
