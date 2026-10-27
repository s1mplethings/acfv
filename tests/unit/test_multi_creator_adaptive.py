from __future__ import annotations

from pathlib import Path

import pytest

from acfv.creator_adaptive import (
    CorpusRole,
    CorpusVod,
    assert_memory_eligible,
    split_payload,
    validate_vod_split,
    FinalHoldoutRecord,
    FinalHoldoutState,
    claim_final_holdout,
)
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.providers.lexical_acoustic import (
    LexicalAcousticExemplar,
    LexicalAcousticMemory,
)
from acfv.providers.download import discover_public_twitch_vods
from acfv.runtime.bulk_storage import (
    GIB,
    TIB,
    StorageVolume,
    bulk_media_root,
    persist_local_bulk_root,
    relative_bulk_locator,
    resolve_bulk_locator,
    safe_reserve,
    select_bulk_storage,
)
from acfv.voice_profile import CreatorVoiceProfileService, VoiceEvidenceState


def volume(letter: str, *, capacity: int = 2 * TIB, free: int = 600 * GIB,
           health: str = "Healthy", operational: str = "OK", media: str = "HDD",
           system: bool = False) -> StorageVolume:
    return StorageVolume(
        letter, capacity, free, health_status=health, operational_status=operational,
        media_type=media, is_system=system,
    )


def test_bulk_storage_prefers_valid_q_and_preserves_reserve() -> None:
    decision = select_bulk_storage([volume("E", free=900 * GIB), volume("Q", free=700 * GIB)], estimated_corpus_bytes=100 * GIB)
    assert decision.status == "BULK_STORAGE_READY"
    assert decision.selected_drive == "Q"
    assert decision.projected_free_bytes >= decision.reserve_bytes
    assert decision.reserve_bytes == safe_reserve(2 * TIB)


def test_bulk_storage_rejects_actual_small_q_and_reserve_breaches() -> None:
    decision = select_bulk_storage([
        volume("Q", capacity=256 * GIB, free=46 * GIB, media="SSD"),
        volume("E", free=90 * GIB),
        volume("F", free=226 * GIB, media="SSD"),
        volume("G", capacity=TIB, free=4 * GIB, health="Warning", operational="Full Repair Needed", media="SSD"),
    ])
    assert decision.status == "BULK_STORAGE_NOT_AVAILABLE"
    assert decision.selected_drive is None and decision.probe_allowed
    assert any("Q: capacity below" in reason for reason in decision.reasons)


def test_bulk_storage_falls_back_to_healthy_hdd_and_rejects_system() -> None:
    decision = select_bulk_storage([
        volume("Q", capacity=256 * GIB, free=100 * GIB, media="SSD"),
        volume("C", free=900 * GIB, media="SSD", system=True),
        volume("E", free=650 * GIB, media="HDD"),
    ])
    assert decision.selected_drive == "E"


def test_bulk_locator_is_portable_and_blocks_traversal(tmp_path: Path) -> None:
    locator = relative_bulk_locator("twitch", "raw", "saruei", "123", "source.mp4")
    assert locator == "BULK_MEDIA_ROOT/twitch/raw/saruei/123/source.mp4"
    assert resolve_bulk_locator(locator, root=tmp_path) == tmp_path / "twitch/raw/saruei/123/source.mp4"
    with pytest.raises(ValueError):
        relative_bulk_locator("..", "escape.mp4")


def test_bulk_root_mapping_survives_restart_without_shared_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACFV_BULK_MEDIA_ROOT", raising=False)
    root = tmp_path / "large media"
    config = tmp_path / "local" / "bulk_media_root.json"
    persist_local_bulk_root(root, config_path=config)
    assert bulk_media_root(config_path=config) == root.resolve()
    monkeypatch.setenv("ACFV_BULK_MEDIA_ROOT", str(tmp_path / "override"))
    assert bulk_media_root(config_path=config) == (tmp_path / "override").resolve()


def test_vod_split_is_frozen_at_vod_id_and_blocks_memory_leakage() -> None:
    rows = (
        CorpusVod("saruei", "100", CorpusRole.TRAIN),
        CorpusVod("saruei", "101", CorpusRole.VALIDATION),
        CorpusVod("saruei", "102", CorpusRole.HOLDOUT),
        CorpusVod("unknown", "200", CorpusRole.UNKNOWN, unknown_partition="HOLDOUT"),
    )
    payload = split_payload(rows, dataset_id="MULTI_CREATOR_TWITCH_V1", dataset_version="v1")
    assert payload["split_unit"] == "TWITCH_VOD_ID" and payload["sha256"]
    assert_memory_eligible("100", {row.vod_id: row.role for row in rows}, memory_kind="trusted_speech")
    assert_memory_eligible("101", {row.vod_id: row.role for row in rows}, memory_kind="threshold_tuning")
    for vod_id in ("101", "102", "200"):
        with pytest.raises(PermissionError):
            assert_memory_eligible(vod_id, {row.vod_id: row.role for row in rows}, memory_kind="trusted_speech")
    for vod_id in ("102", "200"):
        with pytest.raises(PermissionError):
            assert_memory_eligible(vod_id, {row.vod_id: row.role for row in rows}, memory_kind="threshold_tuning")
    with pytest.raises(ValueError, match="VOD-level leakage"):
        validate_vod_split((rows[0], CorpusVod("saruei", "100", CorpusRole.HOLDOUT)))


def test_v1_consumed_holdout_cannot_rerun_or_train(tmp_path: Path) -> None:
    v1 = (FinalHoldoutRecord(
        "MULTI_CREATOR_TWITCH_FINAL_HOLDOUT_V1", "2853235966",
        FinalHoldoutState.CONSUMED_LOCKED, 1, True,
    ),)
    events = tmp_path / "leakage.ndjson"
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_LEAKAGE_ATTEMPT"):
        assert_memory_eligible(
            "2853235966", {"2853235966": CorpusRole.TRAIN},
            memory_kind="visual_train", final_holdouts=v1,
            leakage_event_path=events,
        )
    assert "FINAL_HOLDOUT_LEAKAGE_ATTEMPT" in events.read_text(encoding="utf-8")
    with pytest.raises(PermissionError, match="already consumed"):
        claim_final_holdout(
            v1, dataset_id="MULTI_CREATOR_TWITCH_FINAL_HOLDOUT_V1",
            claim_path=tmp_path / "v1-claim.json", preflight_passed=True,
        )


def test_v2_reserved_cannot_leak_and_can_be_claimed_only_once(tmp_path: Path) -> None:
    v2 = tuple(
        FinalHoldoutRecord(
            "FINAL_FROZEN_HOLDOUT_V2", vod_id,
            FinalHoldoutState.RESERVED_UNOPENED, 0, False,
        )
        for vod_id in ("2904375027", "2901762827", "2903484569")
    )
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_LEAKAGE_ATTEMPT"):
        assert_memory_eligible(
            "2901762827", {"2901762827": CorpusRole.TRAIN},
            memory_kind="trusted_speech", final_holdouts=v2,
        )
    claim_path = tmp_path / "v2-claim.json"
    claim = claim_final_holdout(
        v2, dataset_id="FINAL_FROZEN_HOLDOUT_V2",
        claim_path=claim_path, preflight_passed=True,
    )
    assert claim["run_count"] == 1 and claim["rerun_allowed"] is False
    with pytest.raises(FileExistsError):
        claim_final_holdout(
            v2, dataset_id="FINAL_FROZEN_HOLDOUT_V2",
            claim_path=claim_path, preflight_passed=True,
        )


def test_corpus_bound_voice_service_blocks_reserved_v2_before_persistence(tmp_path: Path) -> None:
    v2 = (FinalHoldoutRecord(
        "FINAL_FROZEN_HOLDOUT_V2", "2901762827",
        FinalHoldoutState.RESERVED_UNOPENED, 0, False,
    ),)
    repository = CreatorAdaptiveRepository(tmp_path / "voice-guard.sqlite")
    service = CreatorVoiceProfileService(
        repository=repository,
        split_by_vod={"2901762827": CorpusRole.TRAIN},
        final_holdouts=v2,
    )
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_LEAKAGE_ATTEMPT"):
        service.add_exemplar(
            creator_id="snuffy", recording_id="r", start_ms=0, end_ms=1000,
            audio_locator="x.wav", embedding=[1.0, 0.0], speech_quality=1,
            identity_confidence=1, asr_confidence=1, overlap_status="CLEAN",
            music_status="NONE", trust_level="PSEUDO_TRUSTED", profile_version="v2",
            temporal_region="r1", source_vod_id="2901762827",
        )
    assert repository.rows("creator_voice_exemplars") == []


def test_voice_profile_builds_unnamed_subcenters(tmp_path: Path) -> None:
    service = CreatorVoiceProfileService(repository=CreatorAdaptiveRepository(tmp_path / "voice.sqlite"))
    for index in range(40):
        mode = index % 2
        embedding = [1.0, index / 10000, 0.0] if mode == 0 else [0.0, 1.0, index / 10000]
        service.add_exemplar(
            creator_id="a", recording_id=f"r{index % 4}", start_ms=index * 4000,
            end_ms=index * 4000 + 3000, audio_locator=f"{index}.wav", embedding=embedding,
            speech_quality=1, identity_confidence=1, asr_confidence=1, overlap_status="CLEAN",
            music_status="NONE", trust_level="PSEUDO_TRUSTED", profile_version="v1",
            temporal_region=f"region-{index % 4}",
        )
    profile = service.build("a", profile_version="v1", minimum_mode_improvement=.01)
    assert profile["mode_count"] == 2
    assert [mode["mode_id"] for mode in profile["modes"]] == ["MODE_0", "MODE_1"]
    assert all(mode["human_label"] is None for mode in profile["modes"])


def test_voice_shift_is_not_conflict_without_other_known_match() -> None:
    expected = {
        "creator_id": "a", "strong_threshold": .85, "centroid": [1.0, 0.0, 0.0],
        "modes": [{"mode_id": "MODE_0", "centroid": [1.0, 0.0, 0.0], "strong_threshold": .85}],
    }
    other = {
        "creator_id": "b", "strong_threshold": .85, "centroid": [-1.0, 0.0, 0.0],
        "modes": [{"mode_id": "MODE_0", "centroid": [-1.0, 0.0, 0.0], "strong_threshold": .85}],
    }
    shift = CreatorVoiceProfileService.classify_evidence(
        [0.0, 0.0, 1.0], expected, [other], visual_strong=True,
        recording_prior_same=True, sustained_mismatch=True,
    )
    assert shift["state"] == VoiceEvidenceState.MODE_SHIFT_CANDIDATE.value
    conflict = CreatorVoiceProfileService.classify_evidence(
        [-1.0, 0.0, 0.0], expected, [other], visual_strong=True,
        recording_prior_same=True, sustained_mismatch=True,
    )
    assert conflict["state"] == VoiceEvidenceState.IDENTITY_CONFLICT.value


class DummyLexicalEncoder:
    model_version = "hubert-test"
    representation_kind = "LEXICAL_HUBERT"

    def __init__(self, value: tuple[float, ...]) -> None:
        self.value = value

    def encode(self, audio_path: str, start_ms: int, end_ms: int) -> tuple[float, ...]:
        return self.value


def test_lexical_acoustic_is_creator_scoped_candidate_evidence() -> None:
    rows = (
        LexicalAcousticExemplar("a", "elden ring", "train-a", 0, 500, (1.0, 0.0), "v1", "MODE_1"),
        LexicalAcousticExemplar("a", "hello", "train-b", 0, 500, (0.0, 1.0), "v1"),
        LexicalAcousticExemplar("b", "poison", "train-c", 0, 500, (1.0, 0.0), "v1"),
    )
    result = LexicalAcousticMemory(DummyLexicalEncoder((1.0, 0.0)), rows).query(
        creator_id="a", profile_version="v1", audio_path="query.wav", start_ms=0,
        end_ms=500, voice_mode="MODE_1", limit=3,
    )
    assert result[0].text == "elden ring" and result[0].evidence_only
    assert all(item.text != "poison" for item in result)


def test_lexical_acoustic_rejects_holdout_and_speaker_embeddings() -> None:
    holdout = LexicalAcousticExemplar("a", "term", "h", 0, 1, (1.0,), "v1", split_role="HOLDOUT")
    with pytest.raises(ValueError, match="TRAIN"):
        LexicalAcousticMemory(DummyLexicalEncoder((1.0,)), (holdout,))
    encoder = DummyLexicalEncoder((1.0,))
    encoder.representation_kind = "SPEAKER_ECAPA"
    with pytest.raises(ValueError, match="speaker identity"):
        LexicalAcousticMemory(encoder, ())


def test_public_twitch_discovery_is_metadata_only_and_owner_scoped() -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": {"user": {
                "id": "42", "displayName": "Creator", "videos": {"edges": [
                    {"node": {"id": "123", "title": "Public", "createdAt": "2026-10-01T00:00:00Z",
                              "publishedAt": "2026-10-01T00:00:00Z", "lengthSeconds": 3600,
                              "broadcastType": "ARCHIVE", "viewCount": 7,
                              "owner": {"login": "creator", "displayName": "Creator"}}},
                    {"node": {"id": "999", "title": "Wrong owner", "lengthSeconds": 1,
                              "broadcastType": "ARCHIVE", "owner": {"login": "other"}}},
                ]}
            }}}

    calls = []

    def post(url: str, **kwargs):
        calls.append((url, kwargs))
        return Response()

    rows = discover_public_twitch_vods("Creator", limit=10, request_post=post)
    assert [row.vod_id for row in rows] == ["123"]
    assert rows[0].source_url == "https://www.twitch.tv/videos/123"
    assert calls[0][0] == "https://gql.twitch.tv/gql"
