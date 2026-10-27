import importlib.util
import json
from pathlib import Path

import numpy as np

from acfv.library import LibraryService
from acfv.moments import MomentService, MomentStatus
from acfv.retrieval import PersistentMomentIndex


def _module():
    path = Path("scripts/validate_real_library.py").resolve()
    spec = importlib.util.spec_from_file_location("validate_real_library", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _encoder(texts):
    return np.asarray([[float(len(text)), 1.0] for text in texts], dtype=np.float32)


def test_database_and_index_integrity_accept_consistent_library(tmp_path: Path) -> None:
    validation = _module()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Recording", require_file=False)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 1, "end": 6, "text": "hello real library"}]}
    )[0]
    moment.status = MomentStatus.FINAL
    library.repository.save(moment)
    index = PersistentMomentIndex(library.repository, tmp_path / "index", encoder=_encoder)
    index.rebuild()

    assert validation.database_integrity(tmp_path / "library.db")["pass"] is True
    assert validation.index_integrity(library.repository, index)["pass"] is True


def test_transcript_integrity_prefers_relocated_build_root(tmp_path: Path) -> None:
    validation = _module()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Relocated", require_file=False)
    recording.duration_ms = 10_000
    stale_root = tmp_path / "stale"
    stale_root.mkdir()
    recording.artifact_root = str(stale_root)
    library.repository.save(recording)
    transcript = tmp_path / "build" / "runs" / recording.id / "work" / "transcript_merged.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"language": "en", "segments": [{"start": 1, "end": 3, "text": "evidence"}]}), encoding="utf-8")

    result = validation.transcript_integrity(library.repository, tmp_path / "build")

    assert result["pass"] is True
    assert result["recordings"][0]["path"] == str(transcript)


def test_query_generation_supports_english_chinese_and_mixed() -> None:
    validation = _module()

    class Stub:
        summary = ""
        transcript_text = "测试 mixed language retrieval works"

    query = validation.query_from_moment(Stub())
    assert "测试" in query
    assert "mixed" in query
    assert validation.percentile([1, 2, 3, 4, 5], 0.9) == 5


def test_asr_runtime_metrics_reports_wall_rtf_and_retries(tmp_path: Path) -> None:
    validation = _module()
    runtime = tmp_path / "work" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "transcribe_runtime.json").write_text(json.dumps({"chunks": [
        {"started_at": "2026-10-08T00:00:00+00:00", "finished_at": "2026-10-08T00:00:10+00:00", "status": "succeeded", "attempt": 2},
        {"started_at": "2026-10-08T00:00:10+00:00", "finished_at": "2026-10-08T00:00:20+00:00", "status": "succeeded", "attempt": 1},
    ]}), encoding="utf-8")

    result = validation.asr_runtime_metrics(tmp_path, 100_000)

    assert result == {"elapsed_seconds": 20.0, "rtf": 0.2, "chunks": 2, "failed_chunks": 0, "retry_count": 1}


def test_parse_silence_fraction_uses_all_detected_intervals() -> None:
    validation = _module()
    log = "silence_end: 2 | silence_duration: 2\nsilence_end: 7 | silence_duration: 3"

    assert validation.parse_silence_fraction(log, 10.0) == 0.5


def test_silence_probe_uses_utf8_replacement_for_unicode_media(monkeypatch, tmp_path: Path) -> None:
    validation = _module()
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return type("Completed", (), {"stderr": None})()

    monkeypatch.setattr(validation.subprocess, "run", fake_run)

    assert validation.silence_fraction(tmp_path / "特殊字符.mp4", 10.0) == 0.0
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_library_engine_dispose_releases_sqlite_file(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "disposable.db")
    library.create_creator("Creator")
    library.repository.engine.dispose()

    (tmp_path / "disposable.db").unlink()

    assert not (tmp_path / "disposable.db").exists()


def test_moment_quality_reports_grounded_valid_final_moment(tmp_path: Path) -> None:
    validation = _module()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Recording", require_file=False)
    recording.duration_ms = 10_000
    library.repository.save(recording)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 1, "end": 6, "text": "grounded real evidence"}]}
    )[0]
    moment.status = MomentStatus.FINAL
    library.repository.save(moment)

    result = validation.moment_quality(library.repository)

    assert result["pass"] is True
    assert result["auto_pass"] == 1
    assert result["auto_suspect"] == 0
