from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3

import pytest

from acfv.human_review.analysis import HumanReviewAnalysis, error_rate
from acfv.human_review.dataset import HumanReviewDatasetBuilder
from acfv.human_review.export import HumanReviewExporter
from acfv.human_review.models import ReviewSample, ReviewTask
from acfv.human_review.repository import HumanReviewRepository


def samples() -> list[ReviewSample]:
    return [
        ReviewSample("asr:1", ReviewTask.ASR, prompt={"current_asr": "hello word"}, private={"confidence": 0.2}),
        ReviewSample("translation:1", ReviewTask.TRANSLATION, prompt={"source": "hi", "a": "甲", "b": "乙"}, private={"pair_id": "tr-1", "provider_a": "qwen", "provider_b": "argos"}),
        ReviewSample("boundary:1", ReviewTask.BOUNDARY, private={"strategy": "moment"}),
        ReviewSample("watch:1", ReviewTask.WATCHABILITY, private={"pair_id": "watch-1", "strategy_a": "old", "strategy_b": "new"}),
        ReviewSample("subtitle:1", ReviewTask.SUBTITLE, prompt={"mode": "cue", "english": "Hi", "chinese": "嗨"}, private={"cps": 22}),
        ReviewSample("publish:1", ReviewTask.PUBLISHABILITY),
    ]


def repository(tmp_path: Path) -> HumanReviewRepository:
    repo = HumanReviewRepository(tmp_path / "human_review_test.sqlite")
    repo.replace_dataset(samples(), {"dataset_version": "test", "fixed37_hash": "abc"})
    return repo


def test_repository_autosave_revision_resume_progress_and_backup(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.save("asr:1", {"choice": "wrong", "current_asr": "hello word", "human_transcript": "hello world"})
    repo.save("asr:1", {"choice": "minor", "current_asr": "hello word", "human_transcript": "hello world"})
    annotation = repo.annotation("asr:1")
    assert annotation and annotation["answer"]["choice"] == "minor"
    assert repo.resume_state() == (ReviewTask.ASR, "asr:1")
    assert repo.progress()[0].completed == 1
    with sqlite3.connect(repo.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM annotation_revisions WHERE sample_id='asr:1'").fetchone()[0] == 2
    backup = repo.backup(reason="test")
    assert backup.is_file()
    assert repo.integrity_check() == "ok"


def test_save_can_advance_resume_state_in_same_transaction(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.save("asr:1", {"choice": "correct"}, resume_sample_id="translation:1")
    assert repo.resume_state() == (ReviewTask.TRANSLATION, "translation:1")


def test_blind_presentation_and_duplicate_guards(tmp_path: Path) -> None:
    translation = samples()[1]
    assert "provider_a" not in json.dumps(translation.presentation())
    assert translation.presentation(reveal=True)["reveal"]["provider_a"] == "qwen"
    repo = HumanReviewRepository(tmp_path / "test.sqlite")
    with pytest.raises(ValueError, match="duplicate sample id"):
        repo.replace_dataset([translation, translation], {})
    with pytest.raises(ValueError, match="duplicate formal A/B pair"):
        repo.replace_dataset([translation, ReviewSample("translation:2", ReviewTask.TRANSLATION, private={"pair_id": "tr-1"})], {})


def test_analysis_and_export_are_human_annotation_only(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.save("asr:1", {"choice": "wrong", "current_asr": "hello word", "human_transcript": "hello world"})
    repo.save("translation:1", {"choice": "a", "details": {"accuracy": "5"}})
    repo.save("boundary:1", {"start": "good", "end": "too_late", "length": "too_long", "preferred_profile": "SHORT"})
    repo.save("watch:1", {"choice": "b", "details": {"better_hook": True}})
    repo.save("subtitle:1", {"choice": "bad_break"})
    repo.save("publish:1", {"choice": "reject", "reject_reasons": ["boring"], "details": {"rating_content": "2"}})
    report = HumanReviewAnalysis(repo).calculate()
    assert report["asr"]["wer"] == pytest.approx(0.5)
    assert report["translation"]["labels"] == {"a": 1}
    assert report["translation"]["provider_wins"] == {"qwen": 1}
    assert report["watchability"]["reasons"] == {"better_hook": 1}
    assert report["subtitle"]["cps_readability"]["fast"]["good_rate"] == 0
    assert report["boundary"]["start"] == {"good": 1}
    assert report["publishability"]["reject_reasons"] == {"boring": 1}
    assert report["publishability"]["ratings"]["content"] == 2
    paths = HumanReviewExporter(repo).export(tmp_path / "exports")
    assert paths["csv"].is_file() and paths["json"].is_file() and paths["analysis"].is_file()
    assert "Human Review Analysis" in paths["analysis"].read_text(encoding="utf-8")


def test_error_rate() -> None:
    assert error_rate("hello world", "hello word") == pytest.approx(0.5)
    assert error_rate("", "anything") is None


def test_dataset_builder_reads_canonical_blind_and_fixed_sources(tmp_path: Path) -> None:
    manual = tmp_path / "generation-quality-repair-fixed37" / "manual-review"
    asr = manual / "asr-human-ground-truth-pack" / "asr-001"
    asr.mkdir(parents=True)
    (asr / "metadata.json").write_text(json.dumps({"sample_id": "asr-001", "creator": "anny", "word": {"text": "hello", "confidence": 0.2}}), encoding="utf-8")
    (asr / "audio.wav").write_bytes(b"RIFF")
    translations = manual / "translation-human-review-pack"; translations.mkdir()
    with (translations / "translation-blind-review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["group_id", "source", "context", "A", "B"]); writer.writeheader(); writer.writerow({"group_id": "tr-1", "source": "hi", "context": "", "A": "甲", "B": "乙"})
    with (translations / "translation-provider-evidence.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["group_id", "blind_A_provider", "blind_B_provider"]); writer.writeheader(); writer.writerow({"group_id": "tr-1", "blind_A_provider": "QWEN", "blind_B_provider": "ARGOS"})
    with (manual / "boundary-manual-review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_id"]); writer.writeheader(); writer.writerow({"event_id": "event-1"})
    with (manual / "watchability-pairwise-review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_id", "content_type", "candidate_A", "candidate_B"]); writer.writeheader(); writer.writerow({"event_id": "event-1", "content_type": "reaction", "candidate_A": "a.mp4", "candidate_B": "b.mp4"})
    result = HumanReviewDatasetBuilder(tmp_path, seed=7).build()
    assert result.counts["asr"] == 1
    assert result.counts["translation"] == 2  # one formal pair plus one swapped consistency control
    assert result.counts["boundary"] == 1
    assert result.counts["watchability"] == 2  # one formal pair plus one swapped consistency control
    translation = next(item for item in result.samples if item.task == ReviewTask.TRANSLATION)
    assert "provider" not in json.dumps(translation.presentation())
    assert translation.private["provider_a"] == "QWEN"


def test_test_and_production_database_names_are_distinct(tmp_path: Path) -> None:
    production = HumanReviewRepository(tmp_path / "human_review.sqlite")
    test = HumanReviewRepository(tmp_path / "human_review_test.sqlite")
    test.replace_dataset(samples(), {})
    test.save("asr:1", {"choice": "correct"})
    assert production.annotation_rows() == []
    assert len(test.annotation_rows()) == 1


def test_v4_creator_adaptive_review_is_loaded_without_overwriting_annotations(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence" / "validation"
    evidence.mkdir(parents=True)
    payload = {
        "schema_version": 4,
        "identity": [{"id": "visual-1", "creator": "anny", "predicted_creator": "anny"}],
        "trusted_speech": [{"id": "speech-1", "creator": "anny", "transcript": "hello"}],
        "adaptive_asr": [{"id": "asr-1", "creator": "anny", "generic_text": "hello", "adaptive_text": "hullo"}],
    }
    (evidence / "human-review-v4.json").write_text(json.dumps(payload), encoding="utf-8")
    result = HumanReviewDatasetBuilder(tmp_path, seed=7).build()
    assert result.counts["identity"] == 1
    assert result.counts["trusted_speech"] == 1
    assert result.counts["adaptive_asr"] == 1
    assert all(":v4:" in item.sample_id for item in result.samples)

    repo = HumanReviewRepository(tmp_path / "human_review.sqlite")
    repo.replace_dataset(result.samples, result.metadata)
    first = result.samples[0]
    repo.save(first.sample_id, {"choice": "correct"})
    repo.merge_dataset(result.samples, result.metadata)
    assert repo.annotation(first.sample_id)["answer"]["choice"] == "correct"
