from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Iterable

from acfv.creator_adaptive.models import (
    AvatarIdentityObservation,
    CreatorIdentityDecision,
    IdentityObservation,
    IdentitySource,
    IdentityState,
    VisualIdentityLevel,
    VisualIdentitySpan,
)
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository


class CreatorIdentityService:
    def __init__(self, db_path: Path | None = None, *, repository: CreatorAdaptiveRepository | None = None) -> None:
        self.repository = repository or CreatorAdaptiveRepository(db_path)

    def record_observation(self, observation: IdentityObservation) -> IdentityObservation:
        identifier = self.repository.add_row("creator_identity_observations", {
            "id": observation.id or None,
            "recording_id": observation.recording_id, "start_ms": observation.start_ms, "end_ms": observation.end_ms,
            "candidate_creator_id": observation.candidate_creator_id, "source": observation.source.value,
            "confidence": observation.confidence, "provider": observation.provider,
            "model_version": observation.model_version, "evidence_ref": observation.evidence_ref,
            "raw_metadata_json": json.dumps(dict(observation.raw_metadata), ensure_ascii=False, sort_keys=True),
        })
        return IdentityObservation(**{**observation.__dict__, "id": identifier})

    def register_label_mapping(
        self, *, mapping_version: str, model_version: str,
        labels: dict[str, str | None], provenance: dict[str, object] | None = None,
    ) -> None:
        """Persist only explicit mappings; unknown labels remain auditable and unmapped."""
        for external_label, creator_id in labels.items():
            existing = self.repository.rows(
                "avatar_label_mappings",
                where="mapping_version=? AND model_version=? AND external_label=?",
                params=(mapping_version, model_version, str(external_label)),
            )
            if existing:
                continue
            self.repository.add_row("avatar_label_mappings", {
                "mapping_version": mapping_version, "model_version": model_version,
                "external_label": str(external_label), "creator_id": creator_id,
                "status": "MAPPED" if creator_id else "UNKNOWN",
                "provenance_json": json.dumps(dict(provenance or {}), ensure_ascii=False, sort_keys=True),
            })

    def record_avatar_observations(
        self, recording_id: str, creator_map: dict[str, str], rows: Iterable[AvatarIdentityObservation],
        *, mapping_version: str,
    ) -> list[str]:
        identifiers: list[str] = []
        for row in rows:
            identifiers.append(self.repository.add_row("avatar_identity_observations", {
                "recording_id": recording_id, "timestamp_ms": row.timestamp_ms,
                "external_label": row.creator_external_id,
                "candidate_creator_id": creator_map.get(row.creator_external_id),
                "confidence": row.confidence, "frame_quality": row.frame_quality,
                "bbox_json": json.dumps(list(row.bbox) if row.bbox else []), "track_id": row.track_id,
                "provider": row.provider, "model_version": row.model_version,
                "mapping_version": mapping_version,
                "raw_metadata_json": json.dumps(dict(row.raw_metadata), ensure_ascii=False, sort_keys=True),
            }))
        return identifiers

    def ingest_visual(self, recording_id: str, creator_map: dict[str, str], rows: Iterable[AvatarIdentityObservation], *, frame_span_ms: int = 1000, mapping_version: str = "avatar_mapping_v1") -> list[IdentityObservation]:
        rows = list(rows)
        self.record_avatar_observations(recording_id, creator_map, rows, mapping_version=mapping_version)
        persisted = []
        for row in rows:
            creator_id = creator_map.get(row.creator_external_id)
            if not creator_id:
                continue
            persisted.append(self.record_observation(IdentityObservation(
                recording_id=recording_id, start_ms=row.timestamp_ms, end_ms=row.timestamp_ms + frame_span_ms,
                candidate_creator_id=creator_id, source=IdentitySource.VISUAL,
                confidence=row.confidence * row.frame_quality, provider=row.provider,
                model_version=row.model_version, raw_metadata=row.raw_metadata,
            )))
        return persisted

    def aggregate_visual(
        self, recording_id: str, creator_map: dict[str, str], rows: Iterable[AvatarIdentityObservation],
        *, mapping_version: str, max_gap_ms: int = 2500, minimum_support_frames: int = 3,
    ) -> list[VisualIdentitySpan]:
        """Aggregate multi-frame presence evidence; this never asserts active speech."""
        ordered = sorted(rows, key=lambda item: item.timestamp_ms)
        if not ordered:
            return []
        groups: list[list[AvatarIdentityObservation]] = []
        for row in ordered:
            if not groups or row.timestamp_ms - groups[-1][-1].timestamp_ms > max_gap_ms:
                groups.append([row])
            else:
                groups[-1].append(row)
        spans: list[VisualIdentitySpan] = []
        for group in groups:
            by_label: dict[str, list[AvatarIdentityObservation]] = {}
            for row in group:
                by_label.setdefault(row.creator_external_id, []).append(row)
            label, support = max(by_label.items(), key=lambda item: (len(item[1]), median(x.confidence * x.frame_quality for x in item[1])))
            creator_id = creator_map.get(label)
            conflict_frames = len(group) - len(support)
            coverage = len(support) / len(group)
            score = float(median(row.confidence * row.frame_quality for row in support))
            if not creator_id:
                level = VisualIdentityLevel.UNKNOWN
            elif conflict_frames and coverage < 0.75:
                level = VisualIdentityLevel.AMBIGUOUS
            elif len(support) >= minimum_support_frames and coverage >= 0.8 and score >= 0.85:
                level = VisualIdentityLevel.STRONG
            elif len(support) >= 2 and coverage >= 0.6 and score >= 0.7:
                level = VisualIdentityLevel.PROBABLE
            else:
                level = VisualIdentityLevel.UNKNOWN
            span = VisualIdentitySpan(
                recording_id=recording_id, start_ms=group[0].timestamp_ms,
                end_ms=group[-1].timestamp_ms + max(1, min(max_gap_ms, 1000)), creator_id=creator_id,
                external_label=label, level=level, median_confidence=score,
                support_frames=len(support), conflict_frames=conflict_frames, coverage=coverage,
                model_version=support[0].model_version, mapping_version=mapping_version,
            )
            identifier = self.repository.add_row("creator_visual_identity_spans", {
                "recording_id": span.recording_id, "start_ms": span.start_ms, "end_ms": span.end_ms,
                "creator_id": span.creator_id, "external_label": span.external_label, "level": span.level.value,
                "median_confidence": span.median_confidence, "support_frames": span.support_frames,
                "conflict_frames": span.conflict_frames, "coverage": span.coverage,
                "model_version": span.model_version, "mapping_version": span.mapping_version,
            })
            spans.append(VisualIdentitySpan(**{**span.__dict__, "id": identifier}))
        return spans

    def fuse(self, recording_id: str, start_ms: int, end_ms: int, observations: Iterable[IdentityObservation], *, profile_version: str = "creator_profile_v1") -> CreatorIdentityDecision:
        rows = list(observations)
        human = [row for row in rows if row.source is IdentitySource.HUMAN]
        if human:
            winner = max(human, key=lambda row: row.confidence)
            decision = CreatorIdentityDecision(recording_id, start_ms, end_ms, IdentityState.CONFIRMED, winner.candidate_creator_id,
                                               human_evidence=True, reason="human confirmation has priority",
                                               profile_version=profile_version, evidence_ids=tuple(row.id for row in human if row.id))
            return self._persist(decision)

        def best(source: IdentitySource):
            candidates = [row for row in rows if row.source is source]
            return max(candidates, key=lambda row: row.confidence) if candidates else None

        visual, voice, prior = best(IdentitySource.VISUAL), best(IdentitySource.VOICE), best(IdentitySource.RECORDING_PRIOR)
        vscore, sscore, pscore = (visual.confidence if visual else 0.0), (voice.confidence if voice else 0.0), (prior.confidence if prior else 0.0)
        state, creator_id, reason = IdentityState.UNKNOWN, None, "no strong identity evidence"
        strong_visual = bool(visual and vscore >= 0.85)
        strong_voice = bool(voice and sscore >= 0.75)
        compatible_prior = bool(prior and pscore >= 0.7)
        if strong_visual and compatible_prior and visual.candidate_creator_id != prior.candidate_creator_id:
            state, reason = IdentityState.CONFLICT, "visual and recording prior conflict; creator memory blocked"
        elif strong_visual and strong_voice:
            if visual.candidate_creator_id == voice.candidate_creator_id:
                if compatible_prior and prior.candidate_creator_id == visual.candidate_creator_id:
                    state, creator_id, reason = IdentityState.CONFIRMED, visual.candidate_creator_id, "visual, recording prior, and voice agree"
                else:
                    state, creator_id, reason = IdentityState.PROBABLE, visual.candidate_creator_id, "visual and voice agree without compatible recording prior"
            else:
                state, reason = IdentityState.CONFLICT, "visual and voice conflict; creator memory blocked"
        elif strong_visual and compatible_prior and prior.candidate_creator_id == visual.candidate_creator_id:
            state, creator_id, reason = IdentityState.PROBABLE, visual.candidate_creator_id, "visual plus compatible recording prior"
        elif strong_voice and compatible_prior and prior.candidate_creator_id == voice.candidate_creator_id:
            state, creator_id, reason = IdentityState.PROBABLE, voice.candidate_creator_id, "voice supports compatible recording prior"
        else:
            ranked = sorted((row for row in rows if row.confidence >= 0.55), key=lambda row: row.confidence, reverse=True)
            if len(ranked) > 1 and ranked[0].candidate_creator_id != ranked[1].candidate_creator_id and ranked[0].confidence - ranked[1].confidence < 0.08:
                state, reason = IdentityState.AMBIGUOUS, "candidate scores are too close"
        decision = CreatorIdentityDecision(
            recording_id, start_ms, end_ms, state, creator_id, vscore, sscore, pscore, False, reason,
            profile_version, tuple(row.id for row in rows if row.id),
        )
        return self._persist(decision)

    def _persist(self, decision: CreatorIdentityDecision) -> CreatorIdentityDecision:
        identifier = self.repository.add_row("creator_identity_decisions", {
            "id": decision.id or None, "recording_id": decision.recording_id, "start_ms": decision.start_ms,
            "end_ms": decision.end_ms, "state": decision.state.value, "creator_id": decision.creator_id,
            "visual_score": decision.visual_score, "voice_score": decision.voice_score,
            "recording_prior": decision.recording_prior, "human_evidence": int(decision.human_evidence),
            "reason": decision.reason, "profile_version": decision.profile_version,
            "evidence_ids_json": json.dumps(list(decision.evidence_ids)),
        })
        return CreatorIdentityDecision(**{**decision.__dict__, "id": identifier})
