from __future__ import annotations

import json
import sqlite3

import pytest

from acfv.library.models import IndexStatus, ProcessingStatus, RecordingStatus
from acfv.library.service import LibraryService


def test_creator_source_recording_persist_across_restart(tmp_path):
    db_path = tmp_path / "acfv.db"
    media = tmp_path / "stream.mp4"
    media.write_bytes(b"video")

    service = LibraryService(db_path)
    creator = service.create_creator("Example Creator")
    source = service.add_source(
        creator.id,
        platform="twitch",
        external_id="example_creator",
        channel_name="example_creator",
    )
    recording = service.register_recording(
        creator_id=creator.id,
        source_id=source.id,
        title="First stream",
        local_path=media,
        content_type="gaming",
        analysis_profile={"asr": True, "chat": True, "ocr": True},
    )

    reopened = LibraryService(db_path)
    assert reopened.list_creators()[0].id == creator.id
    assert reopened.list_sources(creator.id)[0].id == source.id
    persisted = reopened.get_recording(recording.id)
    assert persisted.local_path == str(media.resolve())
    assert json.loads(persisted.analysis_profile_json)["ocr"] is True


def test_creator_and_source_are_deduplicated(tmp_path):
    service = LibraryService(tmp_path / "acfv.db")
    first = service.create_creator("Example Creator")
    second = service.create_creator("Example Creator")
    assert first.id == second.id

    source_a = service.add_source(first.id, platform="twitch", external_id="Example", channel_name="Example")
    source_b = service.add_source(first.id, platform="twitch", external_id="example", channel_name="Example")
    assert source_a.id == source_b.id


def test_creator_update_validates_name_slug_and_preserves_unicode(tmp_path):
    service = LibraryService(tmp_path / "acfv.db")
    first = service.create_creator("第一位创作者", slug="first")
    service.create_creator("Second", slug="second")

    updated = service.update_creator(first.id, display_name="  中文 名称  ", slug="renamed")
    assert updated.display_name == "中文 名称"
    assert updated.slug == "renamed"
    with pytest.raises(ValueError, match="display name"):
        service.update_creator(first.id, display_name="   ")
    with pytest.raises(ValueError, match="already in use"):
        service.update_creator(first.id, slug="second")


def test_source_enable_disable_persists_across_restart(tmp_path):
    db_path = tmp_path / "acfv.db"
    service = LibraryService(db_path)
    creator = service.create_creator("Creator")
    source = service.add_source(
        creator.id,
        platform="twitch",
        external_id="creator_channel",
        channel_name="Creator Channel",
    )

    assert service.set_source_enabled(source.id, False).enabled is False
    reopened = LibraryService(db_path)
    assert reopened.list_sources(creator.id)[0].enabled is False
    assert reopened.set_source_enabled(source.id, True).enabled is True
    with pytest.raises(KeyError, match="Unknown source"):
        reopened.set_source_enabled("missing", True)


def test_recording_status_dimensions_are_independent(tmp_path):
    service = LibraryService(tmp_path / "acfv.db")
    creator = service.create_creator("Creator")
    recording = service.register_recording(
        creator_id=creator.id,
        title="Live",
        local_path=tmp_path / "future.ts",
        recording_status=RecordingStatus.RECORDING,
        require_file=False,
    )
    updated = service.update_recording_status(
        recording.id,
        recording_status=RecordingStatus.COMPLETE,
        processing_status=ProcessingStatus.READY,
        index_status=IndexStatus.NOT_INDEXED,
    )
    assert updated.recording_status == RecordingStatus.COMPLETE
    assert updated.processing_status == ProcessingStatus.READY
    assert updated.index_status == IndexStatus.NOT_INDEXED


def test_interrupted_states_become_retryable_failures(tmp_path):
    db_path = tmp_path / "acfv.db"
    service = LibraryService(db_path)
    creator = service.create_creator("Creator")
    recording = service.register_recording(
        creator_id=creator.id,
        title="Interrupted",
        recording_status=RecordingStatus.RECORDING,
        require_file=False,
    )
    service.update_recording_status(
        recording.id,
        processing_status=ProcessingStatus.PROCESSING,
        index_status=IndexStatus.INDEXING,
    )

    recovered = LibraryService(db_path).get_recording(recording.id)
    assert recovered.recording_status == RecordingStatus.FAILED
    assert recovered.processing_status == ProcessingStatus.FAILED
    assert recovered.index_status == IndexStatus.FAILED


def test_manual_recording_registration_deduplicates_path(tmp_path):
    media = tmp_path / "source.mkv"
    media.write_bytes(b"video")
    service = LibraryService(tmp_path / "acfv.db")
    creator = service.create_creator("Creator")
    first = service.add_video(media, creator_id=creator.id)
    second = service.add_video(media, creator_id=creator.id)
    assert first.id == second.id
    assert len(service.list_recordings()) == 1


def test_windows_unicode_and_space_media_path_survives_restart(tmp_path):
    media_dir = tmp_path / "含 空格的目录"
    media_dir.mkdir()
    media = media_dir / "片段 文件.mp4"
    media.write_bytes(b"video")
    db_path = tmp_path / "路径 数据库.db"
    service = LibraryService(db_path)
    creator = service.create_creator("路径测试")

    recording = service.add_video(media, creator_id=creator.id)
    reopened = LibraryService(db_path).get_recording(recording.id)

    assert reopened is not None
    assert reopened.local_path == str(media.resolve())
    assert reopened.canonical_path == str(media.resolve())
    case_alias = str(media.resolve()).swapcase()
    duplicate = service.add_video(case_alias, creator_id=creator.id)
    assert duplicate.id == recording.id
    assert len(service.list_recordings()) == 1


def test_recording_import_and_capture_completion_probe_media_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr("acfv.library.service.probe_duration_ms", lambda _path: 12_345)
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    service = LibraryService(tmp_path / "acfv.db")
    creator = service.create_creator("Creator")

    imported = service.add_video(media, creator_id=creator.id)
    assert imported.duration_ms == 12_345
    assert imported.file_size == 5

    output = tmp_path / "captured.mp4"
    recording = service.register_recording(
        creator_id=creator.id,
        title="Live",
        local_path=output,
        recording_status=RecordingStatus.RECORDING,
        require_file=False,
    )
    output.write_bytes(b"captured")
    completed = service.update_recording_status(
        recording.id,
        recording_status=RecordingStatus.COMPLETE,
        local_path=output,
    )
    assert completed.duration_ms == 12_345
    assert completed.file_size == 8


def test_legacy_creator_schema_bootstraps_without_database_deletion(tmp_path):
    db_path = tmp_path / "acfv.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE library_creators (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, created_at DATETIME, updated_at DATETIME)"
    )
    connection.execute(
        "INSERT INTO library_creators (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("legacy-1", "Legacy Creator", "2026-01-01", "2026-01-01"),
    )
    connection.commit()
    connection.close()

    service = LibraryService(db_path)
    creators = service.list_creators()
    assert creators[0].id == "legacy-1"
    assert creators[0].display_name == "Legacy Creator"
    assert creators[0].slug.startswith("creator-")


def test_process_recording_forwards_stable_run_directory(monkeypatch, tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    calls = []

    def create_job(**kwargs):
        calls.append(kwargs)
        return {"job_id": "stable-job", "run_dir": str(kwargs["run_dir"])}

    service = LibraryService(
        tmp_path / "library.db",
        job_create=create_job,
        job_wait=lambda _job_id: {"status": "failed", "error_summary": "test"},
        job_status=lambda _job_id: {"status": "failed"},
    )
    creator = service.create_creator("Creator")
    recording = service.add_video(media, creator_id=creator.id)
    run_dir = tmp_path / "stable-run"

    processed = service.process_recording(
        recording.id,
        run_dir=run_dir,
        output_clips_dir=run_dir / "clips",
    )

    assert processed.artifact_root == str(run_dir)
    assert calls[0]["run_dir"] == run_dir
    assert calls[0]["output_clips_dir"] == str(run_dir / "clips")


def test_process_recording_can_persist_terminal_state_before_return(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    service = LibraryService(
        tmp_path / "library.db",
        job_create=lambda **kwargs: {"job_id": "sync-job", "run_dir": str(kwargs["run_dir"])},
        job_wait=lambda _job_id: {
            "status": "failed",
            "error_summary": "expected terminal failure",
            "run_dir": str(tmp_path / "run"),
        },
        job_status=lambda _job_id: {"status": "failed"},
    )
    creator = service.create_creator("Creator")
    recording = service.add_video(media, creator_id=creator.id)

    completed = service.process_recording(
        recording.id,
        run_dir=tmp_path / "run",
        wait_for_completion=True,
    )

    assert completed.processing_status == ProcessingStatus.FAILED
    assert completed.error_message == "expected terminal failure"
