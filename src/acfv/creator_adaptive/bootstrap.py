from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from acfv.creator_adaptive.models import (
    CreatorIdentityDecision, LexiconScope, LexiconType, TrustLevel,
)
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive.corpus import CorpusRole
from acfv.creator_adaptive.final_holdout import FinalHoldoutRecord
from acfv.trusted_speech_memory import TrustedSpeechMemoryService
from acfv.trusted_speech_memory.service import normalize_text


@dataclass(frozen=True)
class TrustedSpeechCandidate:
    identity: CreatorIdentityDecision
    recording_id: str
    start_ms: int
    end_ms: int
    audio_locator: str
    raw_asr: str
    word_timestamps: tuple[Mapping[str, Any], ...] = ()
    asr_confidence: float = 0.0
    redecode_agreement: float = 0.0
    overlap_status: str = "UNKNOWN"
    music_status: str = "UNKNOWN"
    critical_flags: tuple[str, ...] = ()
    independent_evidence: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    source_vod_id: str = ""


class CreatorAdaptiveBootstrapService:
    """Strict, versioned bootstrap. Low-confidence rows remain derived evidence only."""

    def __init__(self, repository: CreatorAdaptiveRepository, *,
                 split_by_vod: Mapping[str, CorpusRole | str] | None = None,
                 final_holdouts: Iterable[FinalHoldoutRecord] = (),
                 leakage_event_path=None) -> None:
        self.repository = repository
        self.memory = TrustedSpeechMemoryService(
            repository=repository, split_by_vod=split_by_vod,
            final_holdouts=final_holdouts, leakage_event_path=leakage_event_path,
        )

    def bootstrap_trusted_speech(
        self, creator_id: str, candidates: Iterable[TrustedSpeechCandidate], *, profile_version: str,
    ) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        recordings: set[str] = set()
        duration_ms = 0
        for candidate in candidates:
            counts["candidates"] += 1
            requested = TrustLevel.TRUSTED_PSEUDO_LABEL
            profile_match = candidate.identity.profile_version in {"", profile_version}
            identifier, trust = self.memory.store_unit(
                creator_id=creator_id, recording_id=candidate.recording_id,
                start_ms=candidate.start_ms, end_ms=candidate.end_ms,
                audio_locator=candidate.audio_locator, raw_asr=candidate.raw_asr,
                word_timestamps=[dict(item) for item in candidate.word_timestamps],
                identity_state=candidate.identity.state,
                speaker_identity_confidence=candidate.identity.voice_score,
                visual_identity_confidence=candidate.identity.visual_score,
                asr_confidence=candidate.asr_confidence,
                redecode_agreement=candidate.redecode_agreement,
                requested_trust=requested,
                provenance={**dict(candidate.provenance), "identity_decision_id": candidate.identity.id},
                profile_version=profile_version,
                independent_evidence=candidate.independent_evidence,
                overlap_status=candidate.overlap_status, music_status=candidate.music_status,
                critical_flags=candidate.critical_flags, profile_compatible=profile_match,
                source_vod_id=candidate.source_vod_id,
            )
            counts[trust.value.lower()] += 1
            if trust is TrustLevel.TRUSTED_PSEUDO_LABEL:
                recordings.add(candidate.recording_id)
                duration_ms += max(0, candidate.end_ms - candidate.start_ms)
            if not identifier:
                raise RuntimeError("trusted speech persistence did not return an identifier")
        return {
            "creator_id": creator_id, "profile_version": profile_version,
            "candidates": counts["candidates"],
            "pseudo_trusted": counts[TrustLevel.TRUSTED_PSEUDO_LABEL.value.lower()],
            "human_confirmed": counts[TrustLevel.HUMAN_CONFIRMED.value.lower()],
            "rejected": counts[TrustLevel.REJECTED.value.lower()],
            "auto_high_confidence": counts[TrustLevel.AUTO_HIGH_CONFIDENCE.value.lower()],
            "duration_ms": duration_ms, "recordings": len(recordings),
        }

    def bootstrap_lexicon(self, creator_id: str, *, profile_version: str) -> dict[str, Any]:
        rows = self.repository.rows(
            "trusted_speech_units",
            where="creator_id=? AND profile_version=? AND trust_level IN ('TRUSTED_PSEUDO_LABEL','HUMAN_CONFIRMED')",
            params=(creator_id, profile_version),
        )
        occurrences: Counter[str] = Counter()
        human: Counter[str] = Counter()
        sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            terms = {
                token for token in normalize_text(str(row["raw_asr"])).split()
                if len(token) >= 5 and token not in ENGLISH_STOP_WORDS
            }
            for term in terms:
                occurrences[term] += 1
                human[term] += int(row["trust_level"] == TrustLevel.HUMAN_CONFIRMED.value)
                sources[term].append(row)
        promoted = 0
        acoustic = 0
        for term, count in sorted(occurrences.items()):
            if count < 2 and human[term] < 1:
                continue
            self.memory.promote_lexicon(
                creator_id=creator_id, text=term, entry_type=LexiconType.OTHER,
                scope=LexiconScope.CREATOR, scope_key="", trusted_occurrences=count,
                human_confirmed_occurrences=human[term], confidence=min(1.0, 0.6 + count * 0.05),
                profile_version=profile_version,
                provenance={"trusted_speech_ids": [row["id"] for row in sources[term]], "bootstrap": "phase2"},
            )
            promoted += 1
            for row in sources[term]:
                words = json.loads(str(row["word_timestamps_json"]))
                match = next((word for word in words if normalize_text(str(word.get("word", word.get("text", "")))) == term), None)
                if not match:
                    continue
                self.memory.add_acoustic_exemplar(
                    creator_id=creator_id, text=term, audio_locator=str(row["audio_locator"]),
                    start_ms=int(row["start_ms"]), end_ms=int(row["end_ms"]),
                    word_start_ms=int(match.get("start_ms", row["start_ms"])),
                    word_end_ms=int(match.get("end_ms", row["end_ms"])),
                    source_recording=str(row["recording_id"]), trust_level=TrustLevel(str(row["trust_level"])),
                    asr_confidence=float(row["asr_confidence"]),
                    human_confirmed=row["trust_level"] == TrustLevel.HUMAN_CONFIRMED.value,
                    context=str(row["raw_asr"]), game_scope="", profile_version=profile_version,
                )
                acoustic += 1
                break
        return {
            "creator_id": creator_id, "profile_version": profile_version,
            "trusted_units": len(rows), "candidates": len(occurrences),
            "promoted": promoted, "human_confirmed_terms": sum(value > 0 for value in human.values()),
            "acoustic_exemplars": acoustic,
        }
