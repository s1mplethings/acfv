from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from acfv.library import LibraryService
from acfv.moments import MomentService, MomentStatus
from acfv.retrieval import PersistentMomentIndex


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_real_library.py"
SPEC = importlib.util.spec_from_file_location("build_real_library", SCRIPT)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_python_resolver_prefers_explicit_path_over_environment(monkeypatch, tmp_path: Path):
    explicit = tmp_path / "explicit python.exe"
    explicit.write_bytes(b"python")
    monkeypatch.setenv("ACFV_PYTHON", str(tmp_path / "missing-python.exe"))

    assert builder.resolve_python_executable(explicit) == explicit.resolve()


def test_python_resolver_rejects_invalid_explicit_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ACFV_PYTHON", sys.executable)

    with pytest.raises(FileNotFoundError, match="explicit Python executable"):
        builder.resolve_python_executable(tmp_path / "missing-python.exe")


def test_python_resolver_uses_valid_environment_path(monkeypatch, tmp_path: Path):
    environment_python = tmp_path / "environment python.exe"
    environment_python.write_bytes(b"python")
    monkeypatch.setenv("ACFV_PYTHON", str(environment_python))

    assert builder.resolve_python_executable() == environment_python.resolve()


def test_python_resolver_rejects_invalid_environment_path(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ACFV_PYTHON", str(tmp_path / "missing-python.exe"))

    with pytest.raises(FileNotFoundError, match="ACFV_PYTHON"):
        builder.resolve_python_executable()


def test_python_resolver_defaults_to_current_interpreter(monkeypatch):
    monkeypatch.delenv("ACFV_PYTHON", raising=False)

    assert builder.resolve_python_executable() == Path(sys.executable).resolve()


def test_python_resolver_expands_environment_variables(monkeypatch, tmp_path: Path):
    environment_python = tmp_path / "python with spaces.exe"
    environment_python.write_bytes(b"python")
    monkeypatch.setenv("ACFV_TEST_PYTHON_ROOT", str(tmp_path))

    assert builder.resolve_python_executable(os.path.join("%ACFV_TEST_PYTHON_ROOT%", environment_python.name)) == environment_python.resolve()


def test_validate_transcript_reports_coverage_and_language(tmp_path: Path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "language": "en",
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "one"},
                    {"start": 4.0, "end": 10.0, "text": "two"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = builder.validate_transcript(transcript, 20_000)

    assert result["valid"] is True
    assert result["spoken_seconds"] == 10.0
    assert result["spoken_coverage"] == 0.5
    assert result["overlap_count"] == 1
    assert result["language"] == "en"


def test_validate_transcript_rejects_non_monotonic_and_out_of_bounds_entries(tmp_path: Path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {"start": 8.0, "end": 9.0, "text": "late"},
                    {"start": -1.0, "end": 20.0, "text": "invalid"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = builder.validate_transcript(transcript, 10_000)

    assert result["valid"] is False
    assert any("out of bounds" in error for error in result["errors"])
    assert any("not monotonic" in error for error in result["errors"])


def test_validate_transcript_rejects_subsecond_tail_overshoot(tmp_path: Path):
    transcript = tmp_path / "transcript.json"
    transcript.write_text(
        json.dumps({"segments": [{"start": 9.0, "end": 10.001, "text": "tail"}]}),
        encoding="utf-8",
    )

    result = builder.validate_transcript(transcript, 10_000)

    assert result["valid"] is False
    assert any("out of bounds" in error for error in result["errors"])


def test_real_library_build_uses_transcript_first_analysis_profile():
    config = builder.build_config()

    assert config.get("ENABLE_AUDIO_FEATURES") is False


def test_audit_resumes_complete_chunks_when_merged_tail_is_out_of_bounds(tmp_path: Path):
    media = tmp_path / "recording.mp4"
    media.write_bytes(b"media")
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(
        creator_id=creator.id,
        title="Tail padding",
        local_path=media,
        require_file=False,
    )
    recording.duration_ms = 10_000
    artifact_root = tmp_path / "runs" / recording.id
    chunks = artifact_root / "work" / "chunks" / "chunk_0000"
    chunks.mkdir(parents=True)
    (chunks / "transcript.json").write_text(json.dumps({"segments": [{"start": 9.0, "end": 12.0, "text": "tail"}]}), encoding="utf-8")
    (artifact_root / "work" / "transcript_merged.json").write_text(
        json.dumps({"segments": [{"start": 9.0, "end": 16.0, "text": "tail"}]}), encoding="utf-8"
    )
    recording.artifact_root = str(artifact_root)
    library.repository.save(recording)

    audit = builder.audit_library(library, tmp_path / "runs", tmp_path / "index")

    assert audit["recordings"][0]["action"] == "RESUME"
    assert audit["recordings"][0]["existing_transcript"]["validation"]["valid"] is False


def test_audit_prefers_explicit_build_root_after_run_relocation(tmp_path: Path):
    media = tmp_path / "recording.mp4"
    media.write_bytes(b"media")
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(
        creator_id=creator.id,
        title="Relocated run",
        local_path=media,
        require_file=False,
    )
    recording.duration_ms = 10_000
    stale_root = tmp_path / "stale" / recording.id
    stale_root.mkdir(parents=True)
    recording.artifact_root = str(stale_root)
    library.repository.save(recording)

    build_root = tmp_path / "build"
    stable_root = build_root / "runs" / recording.id
    chunks = stable_root / "work" / "chunks" / "chunk_0000"
    chunks.mkdir(parents=True)
    transcript = stable_root / "work" / "transcript_merged.json"
    transcript.write_text(
        json.dumps({"segments": [{"start": 1.0, "end": 4.0, "text": "relocated"}]}),
        encoding="utf-8",
    )
    (chunks / "transcript.json").write_text(transcript.read_text(encoding="utf-8"), encoding="utf-8")

    audit = builder.audit_library(library, build_root, tmp_path / "index")

    assert audit["recordings"][0]["action"] == "REBUILD_DOWNSTREAM"
    assert audit["recordings"][0]["existing_transcript"]["path"] == str(transcript)


def test_audit_rebuilds_downstream_for_out_of_bounds_final_moment(tmp_path: Path):
    media = tmp_path / "recording.mp4"
    media.write_bytes(b"media")
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Bounded", local_path=media, require_file=False)
    recording.duration_ms = 10_000
    library.repository.save(recording)
    build_root = tmp_path / "build"
    transcript = build_root / "runs" / recording.id / "work" / "transcript_merged.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"segments": [{"start": 8, "end": 10, "text": "tail"}]}), encoding="utf-8")
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 8, "end": 11, "text": "tail"}]}
    )[0]
    moment.status = MomentStatus.FINAL
    library.repository.save(moment)
    PersistentMomentIndex(
        library.repository,
        tmp_path / "index",
        encoder=lambda texts: np.asarray([[float(len(text)), 1.0] for text in texts], dtype=np.float32),
    ).rebuild()

    audit = builder.audit_library(library, build_root, tmp_path / "index")

    assert audit["recordings"][0]["action"] == "REBUILD_DOWNSTREAM"
    assert audit["recordings"][0]["existing_moment_validation"]["valid"] is False


def test_audit_only_does_not_reset_existing_progress(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = LibraryService(db_path)
    library.repository.engine.dispose()
    progress_path = tmp_path / "progress.json"
    progress_path.write_text('{"status":"READY"}', encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "DEFAULT_MATRIX", tmp_path / "matrix.md")
    monkeypatch.setattr(
        builder,
        "parse_args",
        lambda: SimpleNamespace(
            db=db_path,
            build_root=tmp_path / "build",
            progress=progress_path,
            audit_only=True,
            max_recordings=None,
            recording_id=None,
        ),
    )

    assert builder.main() == 0
    assert json.loads(progress_path.read_text(encoding="utf-8")) == {"status": "READY"}


