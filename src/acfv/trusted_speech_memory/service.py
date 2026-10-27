from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from acfv.creator_adaptive.corpus import CorpusRole, assert_memory_eligible
from acfv.creator_adaptive.final_holdout import FinalHoldoutRecord
from acfv.creator_adaptive.models import IdentityState, LexiconScope, LexiconType, TrustLevel
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository


def normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[\w'-]+", value.casefold(), flags=re.UNICODE)).strip()


class TrustedSpeechMemoryService:
    def __init__(self, db_path: Path | None = None, *, repository: CreatorAdaptiveRepository | None = None,
                 split_by_vod: Mapping[str, CorpusRole | str] | None = None,
                 final_holdouts: Iterable[FinalHoldoutRecord] = (),
                 leakage_event_path: Path | None = None) -> None:
        self.repository = repository or CreatorAdaptiveRepository(db_path)
        self.split_by_vod = dict(split_by_vod or {})
        self.final_holdouts = tuple(final_holdouts)
        self.leakage_event_path = leakage_event_path

    def store_unit(
        self, *, creator_id: str, recording_id: str, start_ms: int, end_ms: int,
        audio_locator: str, raw_asr: str, word_timestamps: list[dict[str, Any]],
        identity_state: IdentityState, speaker_identity_confidence: float,
        visual_identity_confidence: float, asr_confidence: float, redecode_agreement: float,
        requested_trust: TrustLevel, provenance: Mapping[str, Any], profile_version: str,
        adaptive_corrected: bool = False, independent_evidence: Iterable[str] = (),
        overlap_status: str = "CLEAN", music_status: str = "NONE",
        critical_flags: Iterable[str] = (), profile_compatible: bool = True,
        source_vod_id: str = "",
    ) -> tuple[str, TrustLevel]:
        if self.split_by_vod or self.final_holdouts:
            if not source_vod_id:
                raise ValueError("source_vod_id is required for corpus-bound trusted speech")
            assert_memory_eligible(
                source_vod_id, self.split_by_vod, memory_kind="trusted_speech",
                final_holdouts=self.final_holdouts,
                leakage_event_path=self.leakage_event_path,
            )
        independent = {str(item) for item in independent_evidence if str(item)}
        flags = {str(item) for item in critical_flags if str(item)}
        trust = requested_trust
        if requested_trust is TrustLevel.HUMAN_CONFIRMED:
            trust = TrustLevel.HUMAN_CONFIRMED
        elif not profile_compatible:
            trust = TrustLevel.REJECTED
        elif identity_state not in {IdentityState.CONFIRMED, IdentityState.PROBABLE}:
            trust = TrustLevel.REJECTED
        elif overlap_status.upper() != "CLEAN" or music_status.upper() not in {"NONE", "CLEAN"} or flags:
            trust = TrustLevel.REJECTED
        elif adaptive_corrected and len(independent) < 2:
            trust = TrustLevel.AUTO_HIGH_CONFIDENCE
        elif requested_trust is TrustLevel.TRUSTED_PSEUDO_LABEL:
            asr_safe = asr_confidence >= 0.85 or (
                asr_confidence >= 0.70 and redecode_agreement >= 0.90 and len(independent) >= 2
            )
            complete_gate = (
                speaker_identity_confidence >= 0.8 and asr_safe
                and redecode_agreement >= 0.8 and len(independent) >= 1
            )
            trust = TrustLevel.TRUSTED_PSEUDO_LABEL if complete_gate else TrustLevel.AUTO_HIGH_CONFIDENCE
        identifier = self.repository.add_row("trusted_speech_units", {
            "creator_id": creator_id, "recording_id": recording_id, "start_ms": int(start_ms), "end_ms": int(end_ms),
            "audio_locator": audio_locator, "raw_asr": raw_asr, "normalized_text": normalize_text(raw_asr),
            "word_timestamps_json": json.dumps(word_timestamps, ensure_ascii=False),
            "speaker_identity_confidence": float(speaker_identity_confidence),
            "visual_identity_confidence": float(visual_identity_confidence), "asr_confidence": float(asr_confidence),
            "redecode_agreement": float(redecode_agreement), "trust_level": trust.value,
            "provenance_json": json.dumps({
                **dict(provenance), "source_vod_id": source_vod_id,
                "independent_evidence": sorted(independent),
                "overlap_status": overlap_status, "music_status": music_status,
                "critical_flags": sorted(flags), "profile_compatible": profile_compatible,
            }, ensure_ascii=False, sort_keys=True),
            "profile_version": profile_version,
        })
        return identifier, trust

    def add_acoustic_exemplar(self, *, creator_id: str, text: str, audio_locator: str,
                              start_ms: int, end_ms: int, word_start_ms: int, word_end_ms: int,
                              source_recording: str, trust_level: TrustLevel, asr_confidence: float,
                              human_confirmed: bool, context: str, game_scope: str, profile_version: str) -> str:
        if trust_level not in {TrustLevel.TRUSTED_PSEUDO_LABEL, TrustLevel.HUMAN_CONFIRMED}:
            raise ValueError("acoustic exemplars require trusted speech")
        return self.repository.add_row("creator_acoustic_exemplars", {
            "creator_id": creator_id, "text": text, "normalized_text": normalize_text(text),
            "audio_locator": audio_locator, "start_ms": start_ms, "end_ms": end_ms,
            "word_start_ms": word_start_ms, "word_end_ms": word_end_ms,
            "source_recording": source_recording, "trust_level": trust_level.value,
            "asr_confidence": asr_confidence, "human_confirmed": int(human_confirmed),
            "context": context, "game_scope": game_scope, "profile_version": profile_version,
        })

    def confirm_unit(self, unit_id: str, *, speaker_correct: bool, transcript_correct: bool,
                     review_sample_id: str) -> bool:
        """Human review may upgrade a unit only when both independent checks pass."""
        if not unit_id:
            raise ValueError("trusted speech unit id is required")
        rows = self.repository.rows("trusted_speech_units", where="id=?", params=(unit_id,))
        if not rows:
            raise KeyError(unit_id)
        if not (speaker_correct and transcript_correct):
            return False
        provenance = json.loads(str(rows[0]["provenance_json"]))
        provenance["human_review"] = {"sample_id": review_sample_id, "speaker_correct": True, "transcript_correct": True}
        with self.repository.transaction() as connection:
            connection.execute(
                "UPDATE trusted_speech_units SET trust_level=?,provenance_json=? WHERE id=?",
                (TrustLevel.HUMAN_CONFIRMED.value, json.dumps(provenance, ensure_ascii=False, sort_keys=True), unit_id),
            )
        return True

    def promote_lexicon(self, *, creator_id: str | None, text: str, entry_type: LexiconType,
                        scope: LexiconScope, scope_key: str, trusted_occurrences: int,
                        human_confirmed_occurrences: int, confidence: float,
                        profile_version: str, provenance: Mapping[str, Any]) -> str:
        if scope is not LexiconScope.GLOBAL and not creator_id:
            raise ValueError("non-global lexicon entries require creator_id")
        if entry_type is LexiconType.CREATOR_CATCHPHRASE and not creator_id:
            raise ValueError("catchphrases require creator identity")
        if trusted_occurrences < 2 and human_confirmed_occurrences < 1:
            raise ValueError("lexicon promotion requires repeated trusted or human-confirmed evidence")
        normalized = normalize_text(text)
        try:
            return self.repository.add_row("creator_lexicon_entries", {
                "creator_id": creator_id, "text": text, "normalized_text": normalized, "type": entry_type.value,
                "frequency": trusted_occurrences + human_confirmed_occurrences,
                "trusted_occurrences": trusted_occurrences, "human_confirmed_occurrences": human_confirmed_occurrences,
                "confidence": confidence, "last_seen": provenance.get("last_seen", ""), "scope": scope.value,
                "scope_key": scope_key, "profile_version": profile_version,
                "provenance_json": json.dumps(dict(provenance), ensure_ascii=False, sort_keys=True),
            })
        except Exception as exc:
            if "UNIQUE constraint" not in str(exc):
                raise
            rows = self.repository.rows(
                "creator_lexicon_entries",
                where="creator_id IS ? AND normalized_text=? AND scope=? AND scope_key=? AND profile_version=?",
                params=(creator_id, normalized, scope.value, scope_key, profile_version),
            )
            return str(rows[0]["id"])

    def lookup_terms(self, *, creator_id: str | None, profile_version: str,
                     game_scope: str = "", recording_scope: str = "", limit: int = 50) -> list[dict[str, Any]]:
        rows = self.repository.rows("creator_lexicon_entries", where="profile_version=?", params=(profile_version,))
        permitted = []
        for row in rows:
            scope = row["scope"]
            if scope == LexiconScope.GLOBAL.value:
                permitted.append(row)
            elif creator_id and row["creator_id"] == creator_id:
                if scope == LexiconScope.CREATOR.value:
                    permitted.append(row)
                elif scope == LexiconScope.GAME.value and row["scope_key"] == game_scope:
                    permitted.append(row)
                elif scope == LexiconScope.RECORDING.value and row["scope_key"] == recording_scope:
                    permitted.append(row)
        priority = {"RECORDING": 0, "GAME": 1, "CREATOR": 2, "GLOBAL": 3}
        return sorted(permitted, key=lambda row: (priority[row["scope"]], -float(row["confidence"])))[:limit]

