from __future__ import annotations

import json
from pathlib import Path

import pytest

from acfv.creator_adaptive.models import (
    AdaptiveAction, AvatarIdentityObservation, CreatorIdentityDecision, IdentityObservation,
    IdentitySource, IdentityState, LexiconScope, LexiconType, TrustLevel, VisualIdentityLevel,
)
from acfv.creator_adaptive import CreatorAdaptiveBootstrapService, TrustedSpeechCandidate
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive_asr import CreatorAdaptiveASRService
from acfv.creator_identity import CreatorIdentityService
from acfv.providers.avatar_identity import AvatarProviderUnavailable, ExistingAvatarModelAdapter
from acfv.providers.avatar_discovery import discover_avatar_models
from acfv.providers.speaker_embedding import SpeechBrainECAPASpeakerEmbeddingProvider
from acfv.trusted_speech_memory import TrustedSpeechMemoryService
from acfv.voice_profile import CreatorVoiceProfileService, VoiceProfileInsufficientData


@pytest.fixture()
def repository(tmp_path: Path) -> CreatorAdaptiveRepository:
    return CreatorAdaptiveRepository(tmp_path / "library.sqlite")


def observation(source: IdentitySource, creator: str, confidence: float = 0.9) -> IdentityObservation:
    return IdentityObservation("recording", 100, 500, creator, source, confidence, "test", "v1")


def test_migration_is_idempotent_restart_safe_and_default_disabled(tmp_path: Path) -> None:
    first = CreatorAdaptiveRepository(tmp_path / "library.sqlite")
    first.ensure_profile("creator", "creator_profile_v1")
    second = CreatorAdaptiveRepository(tmp_path / "library.sqlite")
    assert second.setting("creator_adaptation_enabled") is False
    assert second.latest_profile("creator")["profile_version"] == "creator_profile_v1"


def test_avatar_python_adapter_normalizes_provider_output(tmp_path: Path) -> None:
    adapter = tmp_path / "avatar_adapter.py"
    adapter.write_text(
        "def identify_frame(frame, timestamp_ms):\n"
        "    return [{'label':'saruei','confidence':1.2,'frame_quality':.8,'bbox':[1,2,3,4]}]\n",
        encoding="utf-8",
    )
    provider = ExistingAvatarModelAdapter(adapter)
    result = provider.identify_frame(object(), 123)
    assert provider.status == "READY"
    assert result[0].creator_external_id == "saruei"
    assert result[0].confidence == 1.0
    assert result[0].timestamp_ms == 123


def test_avatar_unconfigured_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACFV_AVATAR_MODEL_PATH", raising=False)
    provider = ExistingAvatarModelAdapter()
    assert provider.status == "NOT_CONFIGURED"
    with pytest.raises(AvatarProviderUnavailable):
        provider.identify_frame(object(), 0)


def test_visual_voice_agreement_conflict_and_human_priority(repository: CreatorAdaptiveRepository) -> None:
    service = CreatorIdentityService(repository=repository)
    agreed = service.fuse("r", 0, 100, [
        observation(IdentitySource.VISUAL, "a"), observation(IdentitySource.VOICE, "a"),
        observation(IdentitySource.RECORDING_PRIOR, "a"),
    ])
    assert agreed.state is IdentityState.CONFIRMED and agreed.creator_id == "a"
    conflict = service.fuse("r", 100, 200, [observation(IdentitySource.VISUAL, "a"), observation(IdentitySource.VOICE, "b")])
    assert conflict.state is IdentityState.CONFLICT and not conflict.allows_creator_memory
    human = service.fuse("r", 200, 300, [observation(IdentitySource.VISUAL, "a"), observation(IdentitySource.HUMAN, "b", 1)])
    assert human.state is IdentityState.CONFIRMED and human.creator_id == "b" and human.human_evidence


def test_visual_presence_alone_does_not_confirm_active_speaker(repository: CreatorAdaptiveRepository) -> None:
    decision = CreatorIdentityService(repository=repository).fuse("r", 0, 100, [observation(IdentitySource.VISUAL, "a")])
    assert decision.state is IdentityState.UNKNOWN
    assert not decision.allows_creator_memory


def test_voice_profile_requires_sufficient_segments_duration_and_regions(repository: CreatorAdaptiveRepository) -> None:
    service = CreatorVoiceProfileService(repository=repository)
    service.add_exemplar(
        creator_id="a", recording_id="r", start_ms=0, end_ms=2000, audio_locator="a.wav",
        embedding=[1.0, 0.0], speech_quality=1, identity_confidence=1, asr_confidence=1,
        overlap_status="CLEAN", music_status="NONE", trust_level="PSEUDO_TRUSTED",
        profile_version="v1", temporal_region="one",
    )
    with pytest.raises(VoiceProfileInsufficientData):
        service.build("a", profile_version="v1")


def test_voice_profile_robust_medoid_removes_outlier(repository: CreatorAdaptiveRepository) -> None:
    service = CreatorVoiceProfileService(repository=repository)
    for index in range(20):
        vector = [-1.0, 0.0] if index == 19 else [1.0, index / 1000]
        service.add_exemplar(
            creator_id="a", recording_id=f"r{index % 2}", start_ms=index * 4000, end_ms=index * 4000 + 3500,
            audio_locator="a.wav", embedding=vector, speech_quality=1, identity_confidence=1, asr_confidence=1,
            overlap_status="CLEAN", music_status="NONE", trust_level="PSEUDO_TRUSTED", profile_version="v1",
            temporal_region=f"region-{index % 2}",
        )
    profile = service.build("a", profile_version="v1")
    assert profile["outliers"] == 1
    assert profile["score_kind"] == "cosine_similarity_not_probability"


def test_ambiguous_identity_never_creates_trusted_speech(repository: CreatorAdaptiveRepository) -> None:
    service = TrustedSpeechMemoryService(repository=repository)
    _, trust = service.store_unit(
        creator_id="a", recording_id="r", start_ms=0, end_ms=1000, audio_locator="a.wav", raw_asr="hello",
        word_timestamps=[], identity_state=IdentityState.AMBIGUOUS, speaker_identity_confidence=.9,
        visual_identity_confidence=.9, asr_confidence=.99, redecode_agreement=1,
        requested_trust=TrustLevel.TRUSTED_PSEUDO_LABEL, provenance={}, profile_version="v1",
        independent_evidence=("base_asr",),
    )
    assert trust is TrustLevel.REJECTED


def test_borderline_asr_requires_two_independent_agreeing_decodes(repository: CreatorAdaptiveRepository) -> None:
    service = TrustedSpeechMemoryService(repository=repository)
    common = dict(
        creator_id="a", recording_id="r", start_ms=0, end_ms=1000, audio_locator="a.wav", raw_asr="hello",
        word_timestamps=[], identity_state=IdentityState.CONFIRMED, speaker_identity_confidence=.9,
        visual_identity_confidence=.9, asr_confidence=.75,
        requested_trust=TrustLevel.TRUSTED_PSEUDO_LABEL, provenance={}, profile_version="v1",
    )
    _, rejected = service.store_unit(**common, redecode_agreement=.89, independent_evidence=("one", "two"))
    _, accepted = service.store_unit(**common, redecode_agreement=.95, independent_evidence=("one", "two"))
    assert rejected is TrustLevel.AUTO_HIGH_CONFIDENCE
    assert accepted is TrustLevel.TRUSTED_PSEUDO_LABEL


def test_auto_corrected_text_cannot_self_promote(repository: CreatorAdaptiveRepository) -> None:
    service = TrustedSpeechMemoryService(repository=repository)
    _, trust = service.store_unit(
        creator_id="a", recording_id="r", start_ms=0, end_ms=1000, audio_locator="a.wav", raw_asr="sensitivity",
        word_timestamps=[], identity_state=IdentityState.CONFIRMED, speaker_identity_confidence=.99,
        visual_identity_confidence=.99, asr_confidence=.99, redecode_agreement=.99,
        requested_trust=TrustLevel.TRUSTED_PSEUDO_LABEL, provenance={}, profile_version="v1",
        adaptive_corrected=True, independent_evidence=("same_adaptive_result",),
    )
    assert trust is TrustLevel.AUTO_HIGH_CONFIDENCE


def test_human_confirmed_speech_has_priority(repository: CreatorAdaptiveRepository) -> None:
    _, trust = TrustedSpeechMemoryService(repository=repository).store_unit(
        creator_id="a", recording_id="r", start_ms=0, end_ms=1000, audio_locator="a.wav", raw_asr="truth",
        word_timestamps=[], identity_state=IdentityState.UNKNOWN, speaker_identity_confidence=0,
        visual_identity_confidence=0, asr_confidence=0, redecode_agreement=0,
        requested_trust=TrustLevel.HUMAN_CONFIRMED, provenance={"source": "human"}, profile_version="v1",
    )
    assert trust is TrustLevel.HUMAN_CONFIRMED


def test_lexicon_requires_repeated_trusted_evidence_and_is_creator_scoped(repository: CreatorAdaptiveRepository) -> None:
    service = TrustedSpeechMemoryService(repository=repository)
    with pytest.raises(ValueError):
        service.promote_lexicon(
            creator_id="saruei", text="sensitivity", entry_type=LexiconType.GAME,
            scope=LexiconScope.CREATOR, scope_key="", trusted_occurrences=1,
            human_confirmed_occurrences=0, confidence=.8, profile_version="v1", provenance={},
        )
    service.promote_lexicon(
        creator_id="saruei", text="sensitivity", entry_type=LexiconType.GAME,
        scope=LexiconScope.CREATOR, scope_key="", trusted_occurrences=2,
        human_confirmed_occurrences=0, confidence=.9, profile_version="v1", provenance={},
    )
    assert service.lookup_terms(creator_id="saruei", profile_version="v1")
    assert service.lookup_terms(creator_id="anny", profile_version="v1") == []


def test_shadow_fallback_on_identity_conflict(repository: CreatorAdaptiveRepository) -> None:
    identity = CreatorIdentityDecision("r", 0, 100, IdentityState.CONFLICT, None)
    result = CreatorAdaptiveASRService(repository=repository).shadow_decide(
        recording_id="r", start_ms=0, end_ms=100, generic_text="raw", identity=identity,
        profile_version="v1", base_confidence=.2, candidate_terms=("term",),
        historical_evidence={"term": 10}, redecode=lambda terms: ("term", .99),
    )
    assert result.action is AdaptiveAction.GENERIC_FALLBACK
    assert result.adaptive_text == result.generic_text == "raw"


def test_shadow_correction_requires_redecode_and_independent_history(repository: CreatorAdaptiveRepository) -> None:
    identity = CreatorIdentityDecision("r", 0, 100, IdentityState.CONFIRMED, "saruei")
    service = CreatorAdaptiveASRService(repository=repository)
    review = service.shadow_decide(
        recording_id="r", start_ms=0, end_ms=100, generic_text="sensitive", identity=identity,
        profile_version="v1", base_confidence=.4, candidate_terms=("sensitivity",),
        historical_evidence={"sensitivity": 1}, redecode=lambda terms: ("sensitivity", .95),
    )
    assert review.action is AdaptiveAction.REVIEW
    corrected = service.shadow_decide(
        recording_id="r", start_ms=100, end_ms=200, generic_text="sensitive", identity=identity,
        profile_version="v1", base_confidence=.4, candidate_terms=("sensitivity",),
        historical_evidence={"sensitivity": 12}, redecode=lambda terms: ("sensitivity", .95),
    )
    assert corrected.action is AdaptiveAction.CORRECT
    assert service.production_enabled is False


def test_raw_transcript_is_not_an_adaptive_persistence_column(repository: CreatorAdaptiveRepository) -> None:
    columns = repository._connect().execute("PRAGMA table_info(adaptive_transcript_decisions)").fetchall()
    names = {row[1] for row in columns}
    assert "generic_text" in names and "adaptive_text" in names
    assert "official_transcript" not in names and "raw_media" not in names


def test_review_dataset_v2_merge_preserves_existing_rows(tmp_path: Path) -> None:
    from acfv.human_review.models import ReviewSample, ReviewTask
    from acfv.human_review.repository import HumanReviewRepository

    reviews = HumanReviewRepository(tmp_path / "review.sqlite")
    reviews.replace_dataset((ReviewSample("v1", ReviewTask.ASR),), {"dataset_version": "v1"})
    reviews.save("v1", {"choice": "correct"})
    inserted = reviews.merge_dataset((ReviewSample("v2", ReviewTask.IDENTITY),), {"dataset_version": "v2"})
    assert inserted == 1
    assert reviews.sample("v1") is not None and reviews.annotation("v1") is not None
    assert reviews.sample("v2") is not None
    reviews.close()


def test_avatar_discovery_requires_explicit_config_entrypoint_and_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = tmp_path / "best.pt"; model.write_bytes(b"weights")
    entrypoint = tmp_path / "adapter.py"; entrypoint.write_text("def create_provider(path): return object()\n", encoding="utf-8")
    monkeypatch.delenv("ACFV_AVATAR_MODEL_PATH", raising=False)
    report = discover_avatar_models(tmp_path, search_roots=(tmp_path,), label_mapping={"saruei": "creator-a"})
    assert report["status"] == "BLOCKED_MODEL_PATH"
    monkeypatch.setenv("ACFV_AVATAR_MODEL_PATH", str(model))
    monkeypatch.setenv("ACFV_AVATAR_MODEL_ENTRYPOINT", str(entrypoint))
    selected = discover_avatar_models(tmp_path, label_mapping={"saruei": "creator-a"})
    assert selected["status"] == "SELECTED_IDENTITY"
    assert selected["selected"]["sha256"]


def test_avatar_discovery_selects_explicit_null_mapping_as_presence_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = tmp_path / "best.pt"; model.write_bytes(b"weights")
    entrypoint = tmp_path / "adapter.py"; entrypoint.write_text("def create_provider(path): return object()\n", encoding="utf-8")
    monkeypatch.setenv("ACFV_AVATAR_MODEL_PATH", str(model))
    monkeypatch.setenv("ACFV_AVATAR_MODEL_ENTRYPOINT", str(entrypoint))
    selected = discover_avatar_models(tmp_path, label_mapping={"vtuber": None})
    assert selected["status"] == "SELECTED_PRESENCE_ONLY"
    assert selected["selected"]["creator_coverage"] == []


def test_avatar_external_entrypoint_receives_model_path(tmp_path: Path) -> None:
    model = tmp_path / "avatar.pt"; model.write_bytes(b"weights")
    entrypoint = tmp_path / "adapter.py"
    entrypoint.write_text(
        "def create_provider(path):\n"
        " class Provider:\n"
        "  def identify_frame(self, frame, timestamp_ms): return [{'label':'anny','confidence':.9,'raw_metadata':{'path':path}}]\n"
        " return Provider()\n",
        encoding="utf-8",
    )
    provider = ExistingAvatarModelAdapter(model, entrypoint=entrypoint)
    assert provider.status == "READY"
    assert provider.identify_frame(None, 10)[0].raw_metadata["path"] == str(model)


def test_avatar_adapter_rejects_invalid_entrypoint_and_observation(tmp_path: Path) -> None:
    model = tmp_path / "avatar.pt"; model.write_bytes(b"weights")
    bad_entrypoint = tmp_path / "bad_adapter.py"; bad_entrypoint.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(AvatarProviderUnavailable):
        ExistingAvatarModelAdapter(model, entrypoint=bad_entrypoint)
    invalid = tmp_path / "invalid_adapter.py"
    invalid.write_text("def identify_frame(frame, timestamp_ms): return ['not-a-mapping']\n", encoding="utf-8")
    provider = ExistingAvatarModelAdapter(model, entrypoint=invalid)
    with pytest.raises(TypeError):
        provider.identify_frame(None, 10)


def test_avatar_adapter_preserves_multiple_detections_and_provider_failure(tmp_path: Path) -> None:
    model = tmp_path / "avatar.pt"; model.write_bytes(b"weights")
    multiple = tmp_path / "multiple.py"
    multiple.write_text(
        "def identify_frame(frame, timestamp_ms):\n"
        " return [{'label':'saruei','confidence':.9},{'label':'anny','confidence':.8}]\n",
        encoding="utf-8",
    )
    provider = ExistingAvatarModelAdapter(model, entrypoint=multiple)
    assert [item.creator_external_id for item in provider.identify_frame(None, 10)] == ["saruei", "anny"]
    failing = tmp_path / "failing.py"
    failing.write_text("def identify_frame(frame, timestamp_ms): raise RuntimeError('inference failed')\n", encoding="utf-8")
    failed_provider = ExistingAvatarModelAdapter(model, entrypoint=failing)
    with pytest.raises(RuntimeError, match="inference failed"):
        failed_provider.identify_frame(None, 10)


def test_visual_observations_preserve_unknown_and_aggregate_multiframe(repository: CreatorAdaptiveRepository) -> None:
    service = CreatorIdentityService(repository=repository)
    rows = [
        AvatarIdentityObservation("saruei", .95, offset, "avatar-v2", "test", .95)
        for offset in (0, 1000, 2000, 3000)
    ] + [AvatarIdentityObservation("unknown", .6, 3500, "avatar-v2", "test", 1.0)]
    service.record_avatar_observations("r", {"saruei": "creator-a"}, rows, mapping_version="map-v2")
    raw = repository.rows("avatar_identity_observations")
    assert len(raw) == 5 and any(row["candidate_creator_id"] is None for row in raw)
    spans = service.aggregate_visual("r", {"saruei": "creator-a"}, rows, mapping_version="map-v2")
    assert spans[0].level is VisualIdentityLevel.STRONG
    assert spans[0].support_frames == 4 and spans[0].creator_id == "creator-a"


def test_visual_first_fusion_conflict_and_voice_prior_support(repository: CreatorAdaptiveRepository) -> None:
    service = CreatorIdentityService(repository=repository)
    visual_prior = service.fuse("r", 0, 1, [
        observation(IdentitySource.VISUAL, "a", .9), observation(IdentitySource.RECORDING_PRIOR, "a", .9),
    ], profile_version="v2")
    assert visual_prior.state is IdentityState.PROBABLE and visual_prior.creator_id == "a"
    voice_prior = service.fuse("r", 1, 2, [
        observation(IdentitySource.VOICE, "a", .8), observation(IdentitySource.RECORDING_PRIOR, "a", .9),
    ], profile_version="v2")
    assert voice_prior.state is IdentityState.PROBABLE
    prior_conflict = service.fuse("r", 2, 3, [
        observation(IdentitySource.VISUAL, "a", .9), observation(IdentitySource.RECORDING_PRIOR, "b", .9),
    ], profile_version="v2")
    assert prior_conflict.state is IdentityState.CONFLICT and not prior_conflict.allows_creator_memory


@pytest.mark.parametrize("overlap,music,compatible", [("OVERLAP", "NONE", True), ("CLEAN", "MUSIC", True), ("CLEAN", "NONE", False)])
def test_trusted_speech_strict_contamination_and_version_gates(
    repository: CreatorAdaptiveRepository, overlap: str, music: str, compatible: bool,
) -> None:
    _, trust = TrustedSpeechMemoryService(repository=repository).store_unit(
        creator_id="a", recording_id="r", start_ms=0, end_ms=1000, audio_locator="a.wav", raw_asr="hello",
        word_timestamps=[], identity_state=IdentityState.CONFIRMED, speaker_identity_confidence=.99,
        visual_identity_confidence=.99, asr_confidence=.99, redecode_agreement=.99,
        requested_trust=TrustLevel.TRUSTED_PSEUDO_LABEL, provenance={}, profile_version="v2",
        independent_evidence=("generic_asr",), overlap_status=overlap, music_status=music,
        profile_compatible=compatible,
    )
    assert trust is TrustLevel.REJECTED


def test_bootstrap_promotes_repeated_trusted_terms_and_acoustic_exemplar(repository: CreatorAdaptiveRepository) -> None:
    identity = CreatorIdentityDecision("r", 0, 1000, IdentityState.CONFIRMED, "a", .95, .9, .9, profile_version="v2")
    candidates = [
        TrustedSpeechCandidate(
            identity=identity, recording_id=f"r{i}", start_ms=0, end_ms=1000,
            audio_locator=f"a{i}.wav", raw_asr="hello sensitivity",
            word_timestamps=({"word": "sensitivity", "start_ms": 100, "end_ms": 500},),
            asr_confidence=.95, redecode_agreement=.95, overlap_status="CLEAN", music_status="NONE",
            independent_evidence=("generic_asr",),
        ) for i in range(2)
    ]
    service = CreatorAdaptiveBootstrapService(repository)
    report = service.bootstrap_trusted_speech("a", candidates, profile_version="v2")
    lexicon = service.bootstrap_lexicon("a", profile_version="v2")
    assert report["pseudo_trusted"] == 2
    assert lexicon["promoted"] >= 2 and lexicon["acoustic_exemplars"] >= 1


def test_human_trusted_speech_requires_both_checks(repository: CreatorAdaptiveRepository) -> None:
    memory = TrustedSpeechMemoryService(repository=repository)
    unit_id, _ = memory.store_unit(
        creator_id="a", recording_id="r", start_ms=0, end_ms=1, audio_locator="a.wav", raw_asr="hello",
        word_timestamps=[], identity_state=IdentityState.CONFIRMED, speaker_identity_confidence=1,
        visual_identity_confidence=1, asr_confidence=1, redecode_agreement=1,
        requested_trust=TrustLevel.TRUSTED_PSEUDO_LABEL, provenance={}, profile_version="v2",
        independent_evidence=("generic",),
    )
    assert memory.confirm_unit(unit_id, speaker_correct=True, transcript_correct=False, review_sample_id="review") is False
    assert memory.confirm_unit(unit_id, speaker_correct=True, transcript_correct=True, review_sample_id="review") is True
    assert repository.rows("trusted_speech_units", where="id=?", params=(unit_id,))[0]["trust_level"] == "HUMAN_CONFIRMED"


def test_adaptive_profile_mismatch_and_hotword_limit_fall_back_safely(repository: CreatorAdaptiveRepository) -> None:
    identity = CreatorIdentityDecision("r", 0, 1, IdentityState.CONFIRMED, "a", profile_version="v1")
    result = CreatorAdaptiveASRService(repository=repository).shadow_decide(
        recording_id="r", start_ms=0, end_ms=1, generic_text="raw", identity=identity,
        profile_version="v2", base_confidence=.1, candidate_terms=(str(i) for i in range(100)),
        historical_evidence={str(i): i for i in range(100)}, redecode=lambda terms: ("changed", .99),
    )
    assert result.action is AdaptiveAction.GENERIC_FALLBACK
    assert len(result.evidence["hotwords"]) == 30


def test_ecapa_provider_is_who_only_and_lazy(tmp_path: Path) -> None:
    provider = SpeechBrainECAPASpeakerEmbeddingProvider(device="cpu", cache_dir=tmp_path / "ecapa")
    assert provider.lexical_evidence_supported is False
    assert provider.license == "Apache-2.0"
    assert provider.model_version == "speechbrain-ecapa:speechbrain/spkrec-ecapa-voxceleb"
    assert provider._classifier is None

