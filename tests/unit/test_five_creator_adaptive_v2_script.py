from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import scripts.download_active_creator_final_holdout_v1 as final_download
from scripts.build_creator_visual_dataset import sources
from scripts.prepare_active_creator_final_holdout_v1 import (
    ACTIVE_CREATORS,
    canonical_sha256,
    collect_vod_ids,
    validate_candidates,
)
from scripts.prepare_active_creator_v2_calibration import build_calibration
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from scripts.run_active_creator_final_holdout_v1 import _final_memory_safety, human_review_payload
from scripts.run_five_creator_adaptive_v2 import select_rows
from scripts.validate_five_creator_v2_gates import calibrate_gates, select_profiles


def prediction(state: str, creator: str):
    return SimpleNamespace(state=SimpleNamespace(value=state), creator_id=creator)


def test_select_rows_requires_strong_correct_and_separated_anchors() -> None:
    rows = [
        {"sample_id": "a", "recording_id": "1", "creator_id": "snuffy", "dataset_split": "train", "timestamp_ms": 0, "quality": .9},
        {"sample_id": "b", "recording_id": "1", "creator_id": "snuffy", "dataset_split": "train", "timestamp_ms": 1_000, "quality": .8},
        {"sample_id": "c", "recording_id": "1", "creator_id": "snuffy", "dataset_split": "train", "timestamp_ms": 20_000, "quality": .7},
        {"sample_id": "d", "recording_id": "2", "creator_id": "laphipi", "dataset_split": "validation", "timestamp_ms": 0, "quality": .9},
        {"sample_id": "e", "recording_id": "2", "creator_id": "laphipi", "dataset_split": "holdout", "timestamp_ms": 20_000, "quality": 1.0},
    ]
    predictions = [
        prediction("STRONG", "snuffy"), prediction("STRONG", "snuffy"),
        prediction("STRONG", "other"), prediction("STRONG", "laphipi"),
        prediction("STRONG", "laphipi"),
    ]

    selected = select_rows(rows, predictions, max_per_recording=2, minimum_gap_ms=10_000)

    assert [row["sample_id"] for row in selected] == ["a", "d"]


def test_cross_creator_calibration_raises_support_only_gates() -> None:
    profiles = {
        creator: {
            "creator_id": creator, "medoid": vector, "centroid": vector,
            "strong_threshold": .5, "modes": [],
        }
        for creator, vector in {"anny": [1.0, 0.0], "atelieranoko": [0.0, 1.0]}.items()
    }

    result = calibrate_gates(profiles, {"anny": [[1.0, 0.0]], "atelieranoko": [[0.0, 1.0]]})

    assert result["status"] == "PASS"
    assert result["cross_false_accepts"] == 0


def test_legacy_visual_sources_use_configured_roots() -> None:
    quality = Path("configured-quality")
    unknown = Path("configured-unknown")

    rows = sources(quality, unknown)

    assert rows[0].path == quality / "Saruei/01-8d310288/standard/clip_clean.mp4"
    assert rows[-1].path == unknown / "twitchplayspokemon/1f0cef20.mp4"


def test_gate_profile_scope_excludes_inactive_creator() -> None:
    old = {"saruei": {"creator_id": "saruei"}, "anny": {"creator_id": "anny"}}
    new = {
        creator: {"creator_id": creator}
        for creator in ("atelieranoko", "laphipi", "snuffy")
    }

    selected = select_profiles(
        old, new, ("saruei", "atelieranoko", "laphipi", "snuffy")
    )

    assert tuple(selected) == ("atelieranoko", "laphipi", "saruei", "snuffy")
    assert "anny" not in selected


def _final_candidates() -> list[dict[str, object]]:
    return [
        {
            "creator": creator, "vod_id": str(9000 + index),
            "url": f"https://www.twitch.tv/videos/{9000 + index}",
            "published_at": "2026-10-24T00:00:00Z", "duration_seconds": 3600,
            "title": f"Final {creator}",
        }
        for index, creator in enumerate(ACTIVE_CREATORS)
    ]


def test_final_candidate_freeze_requires_exact_active_scope_and_disjoint_vods() -> None:
    rows = validate_candidates(_final_candidates(), forbidden_vod_ids={"123"})

    assert [row["creator"] for row in rows] == list(ACTIVE_CREATORS)
    assert all(row["run_count"] == 0 and row["rerun_allowed"] is False for row in rows)
    assert canonical_sha256({"rows": rows}) == canonical_sha256({"rows": rows})

    forbidden = collect_vod_ids({"rows": [{"vod_id": "9001"}]})
    try:
        validate_candidates(_final_candidates(), forbidden_vod_ids=forbidden)
    except PermissionError as exc:
        assert "9001" in str(exc)
    else:
        raise AssertionError("prior-role overlap must block Final selection")


def test_final_download_serializes_metadata_time_and_probes_all_quartiles(
    tmp_path: Path, monkeypatch,
) -> None:
    media = tmp_path / "final.mp4"
    media.write_bytes(b"media")
    calls: list[list[str]] = []

    monkeypatch.setattr(
        final_download,
        "validate_downloaded_media",
        lambda _path: {"duration_ms": 100_000, "video_codec": "h264", "audio_codec": "aac"},
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(final_download.subprocess, "run", fake_run)

    receipt = final_download.strict_integrity(media, 100)

    assert final_download.json_timestamp(
        datetime(2026, 10, 24, tzinfo=timezone.utc)
    ) == "2026-10-24T00:00:00+00:00"
    assert [row["position_seconds"] for row in receipt["decode_probes"]] == [
        0.0, 25.0, 50.0, 75.0, 95.0,
    ]
    assert len(calls) == 6


def test_final_download_console_json_escapes_non_ascii() -> None:
    rendered = final_download.console_json({"title": "🎃"})

    assert rendered == '{"title": "\\ud83c\\udf83"}'


def test_final_human_review_is_created_only_as_unlabelled_pending_work() -> None:
    payload = human_review_payload({
        "dataset_id": "ACTIVE_CREATOR_FINAL_HOLDOUT_V1",
        "rows": {
            creator: [{"sample_id": f"{creator}:1:0"}]
            for creator in ACTIVE_CREATORS
        },
    })

    assert payload["status"] == "HUMAN_PENDING"
    assert payload["ground_truth_opened"] is False
    assert len(payload["tasks"]) == len(ACTIVE_CREATORS) * 3
    assert all(task.get("label") is None for task in payload["tasks"] if "label" in task)


def test_active_creator_calibration_uses_only_train_validation_and_no_final() -> None:
    visual_rows = []
    review = {"trusted_speech": [], "adaptive_asr": []}
    corpus_rows = [{
        "creator": "saruei", "vod_id": "100", "role": "VALIDATION",
        "duration_seconds": 3600, "raw_path": "saruei.mp4",
    }]
    for creator_index, creator in enumerate(ACTIVE_CREATORS[1:], start=1):
        recording_id = str(100 + creator_index)
        visual_rows.append({
            "creator_id": creator, "recording_id": recording_id,
            "dataset_split": "validation", "timestamp_ms": 1000,
            "crop_path": f"{creator}.jpg",
        })
        for key in ("trusted_speech", "adaptive_asr"):
            review[key].append({
                "creator_id": creator, "recording_id": recording_id,
                "start_ms": 1000, "end_ms": 2000, "media": f"{creator}.wav",
            })

    payload = build_calibration(
        visual_rows=visual_rows, adaptive_review=review, corpus_rows=corpus_rows,
    )

    assert payload["status"] == "HUMAN_PENDING"
    assert payload["final_holdout_used"] is False
    assert payload["ground_truth_opened"] is False
    assert {row["creator"] for row in payload["tasks"]} == set(ACTIVE_CREATORS)


def test_final_memory_safety_blocks_all_cross_creator_access(tmp_path: Path) -> None:
    rows = {
        creator: [{
            "start_ms": 0, "end_ms": 1000, "generic_text": f"safe {creator}",
            "generic_confidence": 0.9,
        }]
        for creator in ACTIVE_CREATORS
    }
    lexicons = {
        creator: {"entries": [{"text": f"term-{creator}"}]}
        for creator in ACTIVE_CREATORS
    }

    result = _final_memory_safety(
        rows, lexicons, CreatorAdaptiveRepository(tmp_path / "final-memory.sqlite")
    )

    assert result["status"] == "PASS"
    assert result["cases"] == 16
    assert result["cross_creator_attacks"] == 12
    assert result["blocked"] == 12
