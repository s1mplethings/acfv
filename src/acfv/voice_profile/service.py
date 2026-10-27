from __future__ import annotations

import json
import math
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from acfv.creator_adaptive.corpus import CorpusRole, assert_memory_eligible
from acfv.creator_adaptive.final_holdout import FinalHoldoutRecord
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository


class VoiceProfileInsufficientData(ValueError):
    pass


class VoiceEvidenceState(str, Enum):
    SUPPORT = "VOICE_SUPPORT"
    INSUFFICIENT = "VOICE_INSUFFICIENT"
    MODE_SHIFT_CANDIDATE = "VOICE_MODE_SHIFT_CANDIDATE"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("voice embeddings must have equal non-zero dimensions")
    dot = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / denominator if denominator else 0.0


def _centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    return [sum(values) / len(vectors) for values in zip(*vectors)]


def _cluster(vectors: list[list[float]], count: int) -> list[list[list[float]]]:
    """Small deterministic cosine k-means used inside one Creator profile."""
    first = max(vectors, key=lambda candidate: median(cosine(candidate, other) for other in vectors))
    centers = [list(first)]
    while len(centers) < count:
        centers.append(list(min(vectors, key=lambda value: max(cosine(value, center) for center in centers))))
    groups: list[list[list[float]]] = []
    for _ in range(12):
        groups = [[] for _ in centers]
        for value in vectors:
            index = max(range(len(centers)), key=lambda item: cosine(value, centers[item]))
            groups[index].append(value)
        if any(not group for group in groups):
            return []
        updated = [_centroid(group) for group in groups]
        if all(cosine(left, right) > 0.999999 for left, right in zip(centers, updated)):
            break
        centers = updated
    return groups


def _mode_quality(groups: Sequence[Sequence[Sequence[float]]]) -> float:
    centers = [_centroid(group) for group in groups]
    scores = [cosine(value, center) for group, center in zip(groups, centers) for value in group]
    return sum(scores) / len(scores) if scores else 0.0


def _build_voice_modes(
    vectors: list[list[float]], *, maximum_modes: int,
    minimum_mode_segments: int, minimum_improvement: float,
) -> list[dict[str, Any]]:
    selected = [vectors]
    quality = _mode_quality(selected)
    for count in range(2, min(maximum_modes, len(vectors) // minimum_mode_segments) + 1):
        candidate = _cluster(vectors, count)
        if not candidate or min(len(group) for group in candidate) < minimum_mode_segments:
            break
        candidate_quality = _mode_quality(candidate)
        if candidate_quality - quality < minimum_improvement:
            break
        selected, quality = candidate, candidate_quality
    ordered = sorted(selected, key=lambda group: (-len(group), tuple(_centroid(group))))
    modes: list[dict[str, Any]] = []
    for index, group in enumerate(ordered):
        center = _centroid(group)
        medoid = max(group, key=lambda value: median(cosine(value, other) for other in group))
        scores = [cosine(center, value) for value in group]
        modes.append({
            "mode_id": f"MODE_{index}",
            "human_label": None,
            "segments": len(group),
            "centroid": center,
            "medoid": medoid,
            "strong_threshold": median(scores) - 0.08,
            "score_min": min(scores),
            "score_median": median(scores),
            "score_max": max(scores),
        })
    return modes


class CreatorVoiceProfileService:
    """Builds robust WHO profiles. It never performs word recognition."""

    def __init__(self, db_path: Path | None = None, *, repository: CreatorAdaptiveRepository | None = None,
                 split_by_vod: Mapping[str, CorpusRole | str] | None = None,
                 final_holdouts: Iterable[FinalHoldoutRecord] = (),
                 leakage_event_path: Path | None = None) -> None:
        self.repository = repository or CreatorAdaptiveRepository(db_path)
        self.split_by_vod = dict(split_by_vod or {})
        self.final_holdouts = tuple(final_holdouts)
        self.leakage_event_path = leakage_event_path

    def add_exemplar(self, *, creator_id: str, recording_id: str, start_ms: int, end_ms: int,
                     audio_locator: str, embedding: Sequence[float], speech_quality: float,
                     identity_confidence: float, asr_confidence: float, overlap_status: str,
                     music_status: str, trust_level: str, profile_version: str,
                     temporal_region: str, source_vod_id: str = "") -> str:
        if self.split_by_vod or self.final_holdouts:
            if not source_vod_id:
                raise ValueError("source_vod_id is required for corpus-bound voice exemplars")
            assert_memory_eligible(
                source_vod_id, self.split_by_vod, memory_kind="voice_train",
                final_holdouts=self.final_holdouts,
                leakage_event_path=self.leakage_event_path,
            )
        if trust_level not in {"RAW", "PSEUDO_TRUSTED", "HUMAN_CONFIRMED", "REJECTED"}:
            raise ValueError("invalid voice trust level")
        return self.repository.add_row("creator_voice_exemplars", {
            "creator_id": creator_id, "recording_id": recording_id, "start_ms": int(start_ms), "end_ms": int(end_ms),
            "audio_locator": audio_locator, "embedding_json": json.dumps([float(value) for value in embedding]),
            "duration_ms": max(0, int(end_ms) - int(start_ms)), "speech_quality": float(speech_quality),
            "identity_confidence": float(identity_confidence), "asr_confidence": float(asr_confidence),
            "overlap_status": overlap_status, "music_status": music_status, "trust_level": trust_level,
            "profile_version": profile_version, "temporal_region": temporal_region,
        })

    def build(self, creator_id: str, *, profile_version: str, minimum_segments: int = 20,
              minimum_duration_ms: int = 60_000, minimum_regions: int = 2,
              maximum_modes: int = 3, minimum_mode_segments: int = 4,
              minimum_mode_improvement: float = 0.025) -> dict[str, Any]:
        rows = self.repository.rows(
            "creator_voice_exemplars",
            where="creator_id=? AND profile_version=? AND trust_level IN ('PSEUDO_TRUSTED','HUMAN_CONFIRMED')",
            params=(creator_id, profile_version),
        )
        duration = sum(int(row["duration_ms"]) for row in rows)
        regions = {str(row["temporal_region"]) for row in rows}
        self.repository.ensure_profile(creator_id, profile_version)
        if len(rows) < minimum_segments or duration < minimum_duration_ms or len(regions) < minimum_regions:
            self.repository.ensure_profile(creator_id, profile_version, voice_status="INSUFFICIENT_DATA")
            raise VoiceProfileInsufficientData(
                f"VOICE_PROFILE_INSUFFICIENT_DATA segments={len(rows)} duration_ms={duration} regions={len(regions)}"
            )
        embeddings = [json.loads(str(row["embedding_json"])) for row in rows]
        medoid = max(embeddings, key=lambda candidate: median(cosine(candidate, other) for other in embeddings))
        scores = [cosine(medoid, value) for value in embeddings]
        threshold = median(scores) - 0.08
        retained = [value for value, score in zip(embeddings, scores) if score >= threshold]
        centroid = [sum(values) / len(retained) for values in zip(*retained)]
        modes = _build_voice_modes(
            embeddings, maximum_modes=max(1, int(maximum_modes)),
            minimum_mode_segments=max(2, int(minimum_mode_segments)),
            minimum_improvement=max(0.0, float(minimum_mode_improvement)),
        )
        if len(modes) == 1 and len(retained) < len(embeddings):
            modes = _build_voice_modes(
                retained, maximum_modes=max(1, int(maximum_modes)),
                minimum_mode_segments=max(2, int(minimum_mode_segments)),
                minimum_improvement=max(0.0, float(minimum_mode_improvement)),
            )
        self.repository.ensure_profile(creator_id, profile_version, voice_status="READY")
        return {
            "creator_id": creator_id, "profile_version": profile_version, "segments": len(rows),
            "duration_ms": duration, "temporal_regions": len(regions), "retained": len(retained),
            "outliers": len(rows) - len(retained), "centroid": centroid, "medoid": medoid,
            "strong_threshold": threshold,
            "modes": modes,
            "mode_count": len(modes),
            "mode_labels": "UNNAMED_AUTOMATIC_CLUSTERS",
            "score_min": min(scores), "score_median": median(scores), "score_max": max(scores),
            "score_kind": "cosine_similarity_not_probability",
        }

    @staticmethod
    def match(embedding: Sequence[float], profile: dict[str, Any]) -> dict[str, Any]:
        modes = list(profile.get("modes") or [])
        if modes:
            winner = max(modes, key=lambda mode: cosine(embedding, mode["centroid"]))
            score = cosine(embedding, winner["centroid"])
            mode_id = str(winner["mode_id"])
            threshold = float(winner.get("strong_threshold", profile.get("strong_threshold", 1.0)))
        else:
            score = cosine(embedding, profile["centroid"])
            mode_id = "MODE_0"
            threshold = float(profile.get("strong_threshold", 1.0))
        return {
            "score": score,
            "score_kind": "cosine_similarity_not_probability",
            "creator_id": profile["creator_id"],
            "voice_mode": mode_id,
            "strong_threshold": threshold,
            "strong": score >= threshold,
        }

    @staticmethod
    def classify_evidence(
        embedding: Sequence[float], expected_profile: dict[str, Any],
        other_profiles: Iterable[dict[str, Any]] = (), *, visual_strong: bool,
        recording_prior_same: bool, sustained_mismatch: bool,
        other_creator_margin: float = 0.03,
    ) -> dict[str, Any]:
        """Distinguish a same-Creator voice-mode shift from true identity conflict."""
        expected = CreatorVoiceProfileService.match(embedding, expected_profile)
        others = [CreatorVoiceProfileService.match(embedding, profile) for profile in other_profiles]
        best_other = max(others, key=lambda row: float(row["score"]), default=None)
        if expected["strong"]:
            state = VoiceEvidenceState.SUPPORT
        elif (
            best_other is not None and best_other["strong"]
            and float(best_other["score"]) >= float(expected["score"]) + other_creator_margin
        ):
            state = VoiceEvidenceState.IDENTITY_CONFLICT
        elif visual_strong and recording_prior_same and sustained_mismatch:
            state = VoiceEvidenceState.MODE_SHIFT_CANDIDATE
        else:
            state = VoiceEvidenceState.INSUFFICIENT
        return {
            "state": state.value,
            "expected_creator": expected_profile["creator_id"],
            "expected": expected,
            "best_other": best_other,
            "support_only": True,
        }

