from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from acfv.creator_adaptive.final_holdout import FinalHoldoutRecord, FinalHoldoutState
from acfv.creator_adaptive.models import AvatarIdentityObservation
from acfv.creator_visual_identity import (
    CreatorVisualDatasetBuilder, CreatorVisualIdentityService, PrototypeIdentityModel,
    LinearProbeIdentityModel, RecordingSource, TwoStageCreatorVisualIdentityProvider, VisualIdentityState,
)
from acfv.creator_visual_identity.provider import verify_file_sha256
from acfv.creator_visual_identity.dataset import difference_hash, hamming
from scripts.build_creator_visual_dataset import manifest_sources


class Encoder:
    model_version = "fake-encoder-v1"
    def encode(self, images): return np.asarray([[1.0, 0.0] for _ in images], dtype=np.float32)


def test_dataset_split_rejects_recording_and_path_leakage(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"; video.write_bytes(b"x")
    rows = [
        RecordingSource("a", "same", video, "train", True),
        RecordingSource("a", "same", video, "holdout", True),
    ]
    with pytest.raises(ValueError, match="recording leakage"):
        CreatorVisualDatasetBuilder.validate_sources(rows)


def test_model_dependency_hash_guard_fails_closed(tmp_path: Path) -> None:
    import hashlib

    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"audited")
    verify_file_sha256(artifact, hashlib.sha256(b"audited").hexdigest())
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify_file_sha256(artifact, "0" * 64)


def test_dataset_rejects_collab_or_unconfirmed_auto_label(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"; video.write_bytes(b"x")
    with pytest.raises(ValueError, match="unsafe auto-label"):
        CreatorVisualDatasetBuilder.validate_sources([RecordingSource("a", "r", video, "train")])
    with pytest.raises(ValueError, match="unsafe auto-label"):
        CreatorVisualDatasetBuilder.validate_sources([RecordingSource("a", "r", video, "train", True, True)])


def test_unknown_challenge_does_not_require_creator_autolabel_confirmation(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"; video.write_bytes(b"x")
    rows = CreatorVisualDatasetBuilder.validate_sources([
        RecordingSource(None, "unknown-r", video, "unknown", allow_full_frame_unknown=True)
    ])
    assert rows[0].creator_id is None


def test_dataset_bad_bbox_and_duplicate_crop_guards(tmp_path: Path) -> None:
    builder = CreatorVisualDatasetBuilder(SimpleNamespace(), tmp_path)
    frame = np.full((200, 200, 3), 127, dtype=np.uint8)
    assert builder._crop(frame, (10, 10, 10, 100)) is None
    assert builder._crop(frame, (0, 0, 4, 4)) is None
    first = difference_hash(frame)
    second = difference_hash(frame.copy())
    assert hamming(first, second) == 0


def test_dataset_blocks_final_holdout_before_opening_source(tmp_path: Path) -> None:
    events = tmp_path / "leakage.jsonl"
    record = FinalHoldoutRecord(
        dataset_id="MULTI_CREATOR_TWITCH_FINAL_HOLDOUT_V1",
        vod_id="2853235966",
        state=FinalHoldoutState.CONSUMED_LOCKED,
        run_count=1,
        ground_truth_opened=True,
    )
    builder = CreatorVisualDatasetBuilder(
        SimpleNamespace(), tmp_path / "dataset",
        final_holdouts=(record,), leakage_event_path=events,
    )
    missing_media = tmp_path / "must-not-be-opened.mp4"
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_LEAKAGE_ATTEMPT"):
        builder.build([
            RecordingSource("anny", "2853235966", missing_media, "train", True)
        ])
    assert "2853235966" in events.read_text(encoding="utf-8")
    assert not (tmp_path / "dataset").exists()


def test_prototype_model_known_unknown_ambiguous_and_roundtrip(tmp_path: Path) -> None:
    rows = np.asarray([[1, 0], [.98, .02], [0, 1], [.02, .98]], dtype=np.float32)
    model = PrototypeIdentityModel.fit(rows, ["saruei", "saruei", "anny", "anny"], encoder_version="test", prototypes_per_creator=1, strong_score=.8, strong_margin=.2, probable_score=.6, probable_margin=.05)
    assert model.predict(np.asarray([1, 0])).creator_id == "saruei"
    assert model.predict(np.asarray([0, 1])).creator_id == "anny"
    assert model.predict(np.asarray([.7, .7])).state is VisualIdentityState.AMBIGUOUS
    assert model.predict(np.asarray([-.7, -.7])).state is VisualIdentityState.UNKNOWN
    loaded = PrototypeIdentityModel.load(model.save(tmp_path / "model.json"))
    assert loaded.predict(np.asarray([1, 0])).creator_id == "saruei"


def test_two_stage_provider_never_maps_raw_vtuber_without_identity() -> None:
    presence = SimpleNamespace(
        model_version="yolo-v1",
        identify_frame=lambda frame, timestamp: [AvatarIdentityObservation("vtuber", .9, timestamp, "yolo-v1", "presence", bbox=(0, 0, 2, 2))],
    )
    model = PrototypeIdentityModel.fit(np.asarray([[1, 0], [0, 1]], dtype=np.float32), ["saruei", "anny"], encoder_version="fake", prototypes_per_creator=1, strong_score=.8, strong_margin=.2, probable_score=.6, probable_margin=.05)
    service = CreatorVisualIdentityService(Encoder(), model)
    result = TwoStageCreatorVisualIdentityProvider(presence, service).identify_frame(np.ones((3, 3, 2), dtype=np.float32), 10)
    assert result[0].creator_external_id == "saruei"
    assert result[0].raw_metadata["raw_presence_label"] == "vtuber"
    assert result[0].raw_metadata["identity_state"] == "STRONG"
    assert result[0].confidence >= .85


def test_multiple_prototypes_and_new_creator_extension() -> None:
    model = PrototypeIdentityModel.fit(
        np.asarray([[1, 0, 0], [.9, .1, 0], [0, 1, 0], [.1, .9, 0], [0, 0, 1]], dtype=np.float32),
        ["saruei", "saruei", "anny", "anny", "new"], encoder_version="test", prototypes_per_creator=2,
    )
    assert len(model.prototypes["saruei"]) == 2
    assert "new" in model.prototypes


def test_linear_probe_closed_set_and_open_set_rejection() -> None:
    model = LinearProbeIdentityModel.fit(
        np.asarray([[1, 0], [.9, .1], [0, 1], [.1, .9]], dtype=np.float32),
        ["saruei", "saruei", "anny", "anny"], encoder_version="frozen", strong_score=.55,
        strong_margin=.10, probable_score=.5, probable_margin=.02,
    )
    assert model.predict(np.asarray([1, 0])).creator_id == "saruei"
    ambiguous = LinearProbeIdentityModel.fit(
        np.asarray([[1, 0], [.9, .1], [0, 1], [.1, .9]], dtype=np.float32),
        ["saruei", "saruei", "anny", "anny"], encoder_version="frozen", strong_score=.99,
        strong_margin=.9, probable_score=.95, probable_margin=.8,
    )
    assert ambiguous.predict(np.asarray([.7, .7])).creator_id is None


def test_linear_probe_support_distance_rejects_softmax_overconfidence() -> None:
    model = LinearProbeIdentityModel.fit(
        np.asarray([[1, 0, 0], [.9, .1, 0], [0, 1, 0], [.1, .9, 0]], dtype=np.float32),
        ["saruei", "saruei", "anny", "anny"], encoder_version="frozen",
        strong_score=.50, strong_margin=0, probable_score=.50, probable_margin=0,
    )
    model.min_support = .7
    prediction = model.predict(np.asarray([0, 0, 1], dtype=np.float32))
    assert prediction.state is VisualIdentityState.UNKNOWN
    assert prediction.creator_id is None


def test_manifest_sources_accepts_v2_plan_and_receipt_directory(tmp_path: Path) -> None:
    media = tmp_path / "raw.mp4"
    media.write_bytes(b"media")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"rows": [{
        "creator": "creator-a", "vod_id": "1234567890", "role": "TRAIN",
    }]}), encoding="utf-8")
    receipts = tmp_path / "evidence"
    receipts.mkdir()
    (receipts / "v2-download-1234567890-receipt.json").write_text(json.dumps({
        "vod_id": "1234567890", "result": "PASS", "output_path": str(media),
    }), encoding="utf-8")

    rows = manifest_sources(plan, receipts, known_sample_fps=2.0, unknown_sample_fps=1.0)

    assert rows == [RecordingSource(
        "creator-a", "1234567890", media, "train", True,
        collab=False, sample_fps=2.0, group_id="1234567890", allow_full_frame_unknown=False,
    )]
