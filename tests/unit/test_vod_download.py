from __future__ import annotations

import threading
import subprocess
import json
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from acfv.library import (
    DownloadStatus,
    IndexStatus,
    LibraryService,
    ProcessingStatus,
    VodDownloadService,
    validate_downloaded_media,
)
from acfv.providers import download as download_provider
from acfv.providers.download import DownloadInterrupted, TwitchVodMetadata, normalize_twitch_vod_input


def test_slow_twitch_cli_version_probe_allows_windows_cold_start(monkeypatch) -> None:
    from acfv.utils import twitch_downloader_setup as setup

    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(returncode=1, stdout="", stderr="TwitchDownloaderCLI 1.56.5")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)

    assert setup._get_cli_version("TwitchDownloaderCLI.exe") == "1.56.5"
    assert observed["timeout"] == setup.VERSION_QUERY_TIMEOUT_SECONDS
    assert observed["timeout"] >= 30
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"


def test_explicit_twitch_cli_environment_override_precedes_persisted_config(monkeypatch) -> None:
    from acfv.utils import twitch_downloader_setup as setup

    monkeypatch.setenv("TWITCHDOWNLOADER_CLI", "explicit.exe")
    monkeypatch.setattr(setup.config_manager, "get", lambda key: "persisted.exe")

    assert setup._gather_candidate_paths()[:2] == ["explicit.exe", "persisted.exe"]


def _metadata(vod_id: str = "12345") -> TwitchVodMetadata:
    return TwitchVodMetadata(
        vod_id=vod_id,
        source_url=f"https://www.twitch.tv/videos/{vod_id}",
        creator_id="creator-remote-id",
        creator_login="test_creator",
        creator_name="Test Creator",
        title="Authorized Test VOD",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        duration_ms=900_000,
        category="Science & Technology",
        thumbnail_url="https://example.invalid/thumb.jpg",
        language="en",
        provider_metadata={"status": "RECORDED"},
    )


def _validator(path: Path) -> dict:
    assert path.name.endswith(".part.mp4")
    return {
        "file_size": path.stat().st_size,
        "duration_ms": 600_000,
        "video_codec": "h264",
        "audio_codec": "aac",
        "width": 1280,
        "height": 720,
        "frame_rate": "30/1",
        "sample_rate": 48000,
        "decode_errors": [],
        "has_suspected_muted_sections": False,
        "muted_intervals": [],
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("12345", "12345"),
        (" https://www.twitch.tv/videos/12345 ", "12345"),
        ("https://twitch.tv/videos/12345?filter=archives&t=1m", "12345"),
        ("https://m.twitch.tv/videos/12345/", "12345"),
    ],
)
def test_vod_url_normalization(source: str, expected: str) -> None:
    assert normalize_twitch_vod_input(source) == (
        "twitch", expected, f"https://www.twitch.tv/videos/{expected}"
    )


@pytest.mark.parametrize(
    "source",
    ["", "not-a-url", "https://www.twitch.tv/test_creator", "https://example.com/videos/123", "https://www.twitch.tv/directory"],
)
def test_invalid_or_channel_url_is_actionable_and_creates_no_rows(tmp_path: Path, source: str) -> None:
    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(library, media_root=tmp_path / "media", metadata_fetcher=lambda _: _metadata())
    with pytest.raises(ValueError, match="Twitch|VOD"):
        service.discover(source)
    assert service.list() == []
    assert library.list_recordings() == []


@pytest.mark.parametrize("message", ["404 VOD deleted", "403 permission denied", "DNS failure"])
def test_metadata_failure_creates_no_dirty_library_rows(tmp_path: Path, message: str) -> None:
    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(
        library,
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _source: (_ for _ in ()).throw(RuntimeError(message)),
    )

    with pytest.raises(RuntimeError, match=message):
        service.discover("12345")

    assert service.list() == []
    assert library.list_recordings() == []
    assert library.list_sources() == []


def test_metadata_maps_and_deduplicates_creator_source_recording_and_job(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(library, media_root=tmp_path / "媒体 库", metadata_fetcher=lambda _: _metadata())
    first = service.discover("https://twitch.tv/videos/12345?x=1", start_ms=60_000, end_ms=660_000)
    second = service.discover("12345")

    assert first.id == second.id
    assert len(library.list_creators()) == 1
    assert len(library.list_sources()) == 1
    assert len(library.list_recordings()) == 1
    recording = library.get_recording(first.recording_id)
    assert recording.external_vod_id == "12345"
    assert recording.source_start_offset_ms == 60_000
    assert recording.source_end_offset_ms == 660_000
    assert recording.is_partial_source is True
    assert "媒体 库" in first.final_path


def test_concurrent_duplicate_submission_creates_one_job(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(library, media_root=tmp_path / "media", metadata_fetcher=lambda _: _metadata())
    ids: list[str] = []

    def submit() -> None:
        ids.append(service.discover("12345").id)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(ids)) == 1
    assert len(service.list()) == 1


def test_failed_range_can_be_revised_without_creating_a_duplicate_job(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(library, media_root=tmp_path / "media", metadata_fetcher=lambda _: _metadata())
    first = service.discover("12345", start_ms=60_000, end_ms=660_000)
    first.status = DownloadStatus.FAILED
    first.error_message = "decode failed"
    library.repository.save(first)

    revised = service.discover("12345", start_ms=600_000, end_ms=1_200_000)

    assert revised.id == first.id
    assert revised.status == DownloadStatus.DISCOVERED
    assert revised.error_message is None
    assert revised.requested_start_ms == 600_000
    assert revised.requested_end_ms == 1_200_000
    assert len(service.list()) == 1
    recording = library.get_recording(revised.recording_id)
    assert recording.source_start_offset_ms == 600_000
    assert recording.source_end_offset_ms == 1_200_000


def test_atomic_download_completion_and_canonical_pipeline_handoff(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    handed_off = []
    monkeypatch.setattr(library, "process_recording", lambda recording_id, **kwargs: handed_off.append((recording_id, kwargs)))

    def downloader(_vod_id, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"validated-media")
        kwargs["progress_callback"]({"downloaded_bytes": 15, "percent": 100.0})
        return output_path

    service = VodDownloadService(
        library,
        media_root=tmp_path / "中文 path",
        metadata_fetcher=lambda _: _metadata(),
        downloader=downloader,
        media_validator=_validator,
    )
    job = service.discover("12345", start_ms=60_000, end_ms=660_000)
    job = service.download(job.id)

    assert job.status == DownloadStatus.PROCESSING
    assert Path(job.final_path).read_bytes() == b"validated-media"
    assert not Path(job.temp_path).exists()
    assert handed_off[0][0] == job.recording_id
    recording = library.get_recording(job.recording_id)
    assert recording.local_path == job.final_path
    assert recording.duration_ms == 600_000


def test_download_forwards_synchronous_processing_request(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    handed_off = []

    def process(recording_id, **kwargs):
        handed_off.append((recording_id, kwargs))
        return library.update_recording_status(
            recording_id,
            processing_status=ProcessingStatus.READY,
            index_status=IndexStatus.READY,
        )

    monkeypatch.setattr(library, "process_recording", process)

    def downloader(_vod_id, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"validated-media")
        return output_path

    service = VodDownloadService(
        library,
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _: _metadata(),
        downloader=downloader,
        media_validator=_validator,
    )
    job = service.discover("12345", start_ms=60_000, end_ms=660_000)
    completed = service.download(job.id, wait_for_processing=True)

    assert handed_off[0][1]["wait_for_completion"] is True
    assert completed.status == DownloadStatus.READY


def test_partial_download_is_interrupted_not_processed_and_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = LibraryService(db_path)

    def interrupted(_vod_id, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"partial")
        raise DownloadInterrupted("stopped for test")

    service = VodDownloadService(
        library,
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _: _metadata(),
        downloader=interrupted,
        media_validator=_validator,
    )
    job = service.discover("12345")
    with pytest.raises(DownloadInterrupted):
        service.download(job.id)
    interrupted_job = service.get(job.id)
    assert interrupted_job.status == DownloadStatus.INTERRUPTED
    assert Path(interrupted_job.temp_path).read_bytes() == b"partial"
    assert not Path(interrupted_job.final_path).exists()
    assert library.get_recording(job.recording_id).last_job_id is None

    reopened = VodDownloadService(LibraryService(db_path), media_root=tmp_path / "media")
    assert reopened.get(job.id).status == DownloadStatus.INTERRUPTED


def test_failed_validation_retains_partial_and_never_hands_off(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    monkeypatch.setattr(library, "process_recording", lambda *_args, **_kwargs: pytest.fail("must not process invalid media"))

    def downloader(_vod_id, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"invalid")
        return output_path

    service = VodDownloadService(
        library,
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _: _metadata(),
        downloader=downloader,
        media_validator=lambda _path: (_ for _ in ()).throw(ValueError("ffprobe failed")),
        sleep=lambda _seconds: None,
    )
    job = service.discover("12345")
    with pytest.raises(ValueError, match="ffprobe"):
        service.download(job.id, max_retries=0)
    failed = service.get(job.id)
    assert failed.status == DownloadStatus.FAILED
    assert Path(failed.temp_path).exists()
    assert library.get_recording(job.recording_id).local_path is None


def test_exit_zero_with_incomplete_media_requires_recovery(tmp_path: Path, monkeypatch) -> None:
    library = LibraryService(tmp_path / "library.db")
    monkeypatch.setattr(library, "process_recording", lambda *_args, **_kwargs: pytest.fail("must not ingest incomplete media"))

    def exited_zero(_vod_id, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"short-media-from-successful-transfer")
        return output_path

    service = VodDownloadService(
        library,
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _: _metadata(),
        downloader=exited_zero,
        media_validator=lambda path: {
            **_validator(path),
            "duration_ms": 600_000,
        },
        sleep=lambda _seconds: None,
    )
    job = service.discover("12345")

    with pytest.raises(ValueError, match="differs from expected"):
        service.download(job.id, max_retries=0)

    failed = service.get(job.id)
    metadata = json.loads(failed.metadata_json)
    assert failed.status == DownloadStatus.FAILED
    assert Path(failed.temp_path).exists()
    assert not Path(failed.final_path).exists()
    assert metadata["failure_code"] == "INCOMPLETE_MEDIA"
    assert metadata["download_lifecycle_state"] == "RECOVERY_REQUIRED"
    assert [event["state"] for event in metadata["download_lifecycle"]] == [
        "TRANSFER_IN_PROGRESS",
        "TRANSFER_COMPLETED",
        "MEDIA_INTEGRITY_VALIDATION",
        "RECOVERY_REQUIRED",
    ]
    assert metadata["last_media_validation"]["duration_ms"] == 600_000
    assert library.get_recording(job.recording_id).local_path is None


def test_successful_retry_preserves_recovery_lifecycle(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    validations = iter((600_000, 900_000))

    def exited_zero(_vod_id, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"media")
        return output_path

    service = VodDownloadService(
        library,
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _: _metadata(),
        downloader=exited_zero,
        media_validator=lambda path: {
            **_validator(path),
            "duration_ms": next(validations),
        },
        sleep=lambda _seconds: None,
    )
    job = service.discover("12345")

    completed = service.download(job.id, max_retries=1, auto_process=False)

    metadata = json.loads(completed.metadata_json)
    assert completed.status == DownloadStatus.DOWNLOADED
    assert [event["state"] for event in metadata["download_lifecycle"]] == [
        "TRANSFER_IN_PROGRESS",
        "TRANSFER_COMPLETED",
        "MEDIA_INTEGRITY_VALIDATION",
        "RECOVERY_REQUIRED",
        "TRANSFER_IN_PROGRESS",
        "TRANSFER_COMPLETED",
        "MEDIA_INTEGRITY_VALIDATION",
        "DOWNLOAD_READY",
        "INGEST_READY",
    ]


def test_provider_failure_has_bounded_retry_and_retains_partial(tmp_path: Path) -> None:
    attempts = []
    backoffs = []

    def crashing_downloader(_vod_id, output_path, **_kwargs):
        attempts.append(len(attempts) + 1)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(f"partial-{len(attempts)}".encode())
        raise RuntimeError("downloader process crashed")

    service = VodDownloadService(
        LibraryService(tmp_path / "library.db"),
        media_root=tmp_path / "media",
        metadata_fetcher=lambda _: _metadata(),
        downloader=crashing_downloader,
        media_validator=_validator,
        sleep=backoffs.append,
    )
    job = service.discover("12345")

    with pytest.raises(RuntimeError, match="crashed"):
        service.download(job.id, max_retries=2)

    failed = service.get(job.id)
    assert attempts == [1, 2, 3]
    assert backoffs == [1, 2]
    assert failed.retry_count == 2
    assert failed.status == DownloadStatus.FAILED
    assert Path(failed.temp_path).read_bytes() == b"partial-3"


def test_disk_full_failure_is_durable_and_never_promotes_partial(tmp_path: Path) -> None:
    def disk_full(_vod_id, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"partial-before-disk-full")
        raise OSError(28, "No space left on device")

    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(
        library, media_root=tmp_path / "media", metadata_fetcher=lambda _: _metadata(),
        downloader=disk_full, media_validator=_validator, sleep=lambda _seconds: None,
    )
    job = service.discover("12345")

    with pytest.raises(OSError, match="No space"):
        service.download(job.id, max_retries=0)

    failed = service.get(job.id)
    assert failed.status == DownloadStatus.FAILED
    assert Path(failed.temp_path).read_bytes() == b"partial-before-disk-full"
    assert not Path(failed.final_path).exists()
    assert library.get_recording(job.recording_id).local_path is None


def test_repository_recovers_downloading_job_as_interrupted(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    first = VodDownloadService(
        LibraryService(db_path), media_root=tmp_path / "media", metadata_fetcher=lambda _: _metadata()
    )
    job = first.discover("12345")
    job.status = DownloadStatus.DOWNLOADING
    first.repository.save(job)
    second = VodDownloadService(LibraryService(db_path), media_root=tmp_path / "media")
    assert second.get(job.id).status == DownloadStatus.INTERRUPTED


def test_real_ffprobe_validation_reports_streams_and_silence(sample_video_path: Path) -> None:
    result = validate_downloaded_media(sample_video_path)
    assert result["duration_ms"] > 0
    assert result["video_codec"]
    assert result["audio_codec"]
    assert result["width"] > 0
    assert result["sample_rate"] > 0


def test_real_ffprobe_validation_warns_on_long_silence(tmp_path: Path) -> None:
    media = tmp_path / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=11",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "11", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(media),
        ],
        check=True,
        timeout=60,
    )

    result = validate_downloaded_media(media)

    assert result["has_suspected_muted_sections"] is True
    assert result["muted_intervals"]


def test_progress_updates_never_reduce_persisted_percent(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    service = VodDownloadService(library, media_root=tmp_path / "media", metadata_fetcher=lambda _: _metadata())
    job = service.discover("12345")
    service._record_progress(job.id, {"percent": 50.0}, None)
    service._record_progress(job.id, {"percent": 25.0}, None)
    assert service.get(job.id).percent == 50.0


def test_provider_version_and_metadata_parsing(monkeypatch) -> None:
    video = {
        "id": "12345",
        "owner": {"id": "42", "login": "pilot", "displayName": "Pilot"},
        "title": "Flight",
        "createdAt": "2026-10-01T00:00:00Z",
        "lengthSeconds": 900,
        "game": {"displayName": "X-Plane 12"},
        "thumbnailURLs": ["https://example.invalid/thumb.jpg"],
        "language": "en",
        "viewCount": 3,
        "description": "test",
        "status": "RECORDED",
    }
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if "--version" in command:
            return SimpleNamespace(returncode=0, stdout="TwitchDownloaderCLI 1.2.3\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="banner\n" + json.dumps({"data": {"video": video}}), stderr="")

    monkeypatch.setattr(download_provider.subprocess, "run", run)
    assert download_provider.twitch_downloader_version("tool.exe") == "TwitchDownloaderCLI 1.2.3"
    metadata = download_provider.fetch_twitch_vod_metadata("12345", cli_path="tool.exe")
    assert metadata.creator_login == "pilot"
    assert metadata.duration_ms == 900_000
    assert metadata.category == "X-Plane 12"
    assert calls[-1][1:4] == ["info", "--id", "12345"]


@pytest.mark.parametrize(
    "result,error",
    [
        (SimpleNamespace(returncode=1, stdout="", stderr="403 forbidden"), RuntimeError),
        (SimpleNamespace(returncode=0, stdout="not json", stderr=""), FileNotFoundError),
    ],
)
def test_provider_metadata_errors_are_actionable(monkeypatch, result, error) -> None:
    monkeypatch.setattr(download_provider.subprocess, "run", lambda *_args, **_kwargs: result)
    with pytest.raises(error):
        download_provider.fetch_twitch_vod_metadata("12345", cli_path="tool.exe")


def test_provider_download_parses_phased_progress(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "source.part.mp4"
    commands = []

    class Stdout:
        def __init__(self):
            self.lines = iter(["100% 2 MiB/s\n", "0% 1 MB/s\n", "100% 1 MB/s\n", "0%\n", "100%\n"])

        def readline(self):
            return next(self.lines, "")

    class Process:
        returncode = 0

        def __init__(self, command, **_kwargs):
            commands.append(command)
            Path(command[command.index("--output") + 1]).write_bytes(b"media")
            self.stdout = Stdout()

        def poll(self):
            return self.returncode

    monkeypatch.setattr(download_provider.subprocess, "Popen", Process)
    updates = []
    result = download_provider.download_twitch_vod_to(
        "12345", output, start_ms=1_000, end_ms=2_000, cli_path="tool.exe",
        bandwidth_kib_s=8192, progress_callback=updates.append
    )
    assert result == output
    assert updates[-1]["percent"] == 100.0
    assert [item.get("current_state") for item in updates if item.get("current_state")][-1] == "media_mux"
    assert any(item.get("speed_bps") == 2 * 1024**2 for item in updates)
    assert commands[0][commands[0].index("--threads") + 1] == "4"
    assert commands[0][commands[0].index("--temp-path") + 1] == str(output.parent / ".twitch-download-temp")
    assert commands[0][commands[0].index("--trim-mode") + 1] == "Exact"
    assert commands[0][commands[0].index("--bandwidth") + 1] == "8192"


def test_provider_download_cancel_is_explicit(monkeypatch, tmp_path: Path) -> None:
    class Process:
        returncode = None
        stdout = SimpleNamespace(readline=lambda: "")

        def terminate(self):
            self.returncode = -1

        def wait(self, timeout):
            return self.returncode

    monkeypatch.setattr(download_provider.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadInterrupted):
        download_provider.download_twitch_vod_to("12345", tmp_path / "part.mp4", cli_path="tool.exe", cancel_event=cancel)


def test_legacy_provider_adapters_and_source_resolution(monkeypatch, tmp_path: Path) -> None:
    cached = tmp_path / "12345.mp4"
    cached.write_bytes(b"cached")
    assert download_provider.download_twitch_vod("12345", tmp_path) == cached

    local = tmp_path / "local.mp4"
    local.write_bytes(b"local")
    assert download_provider.resolve_video_source(str(local), str(tmp_path / "work")) == str(local)

    monkeypatch.setattr(download_provider, "provider_name", lambda *_args, **_kwargs: "streamlink")
    monkeypatch.setattr(download_provider, "download_with_streamlink", lambda *_args, **_kwargs: tmp_path / "stream.mp4")
    assert download_provider.resolve_video_source("https://www.twitch.tv/videos/12345", str(tmp_path / "work")) == str(tmp_path / "stream.mp4")
    with pytest.raises(FileNotFoundError):
        download_provider.resolve_video_source(str(tmp_path / "missing.mp4"), str(tmp_path / "work"))


def test_streamlink_adapter_success_and_failure(monkeypatch, tmp_path: Path) -> None:
    def success(command, **_kwargs):
        Path(command[-1]).write_bytes(b"stream")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(download_provider.subprocess, "run", success)
    assert download_provider.download_with_streamlink("https://example.invalid/live", tmp_path).is_file()

    (tmp_path / "streamlink_capture.mp4").unlink()
    monkeypatch.setattr(
        download_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="network failed"),
    )
    with pytest.raises(RuntimeError, match="network failed"):
        download_provider.download_with_streamlink("https://example.invalid/live", tmp_path)


@pytest.mark.parametrize(
    "probe_payload,expected",
    [
        ({"streams": [{"codec_type": "audio"}], "format": {"duration": "1"}}, "no video"),
        ({"streams": [{"codec_type": "video"}], "format": {"duration": "1"}}, "no audio"),
        ({"streams": [{"codec_type": "video"}, {"codec_type": "audio"}], "format": {"duration": "0"}}, "duration is zero"),
    ],
)
def test_media_validation_rejects_missing_streams_or_duration(monkeypatch, tmp_path: Path, probe_payload, expected) -> None:
    media = tmp_path / "bad.mp4"
    media.write_bytes(b"media")
    monkeypatch.setattr(
        download_provider.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(probe_payload), stderr=""),
    )
    with pytest.raises(ValueError, match=expected):
        validate_downloaded_media(media)


def test_media_validation_normalizes_null_muxer_timestamps(monkeypatch, tmp_path: Path) -> None:
    media = tmp_path / "recovered.mp4"
    media.write_bytes(b"media")
    commands = []
    probe_payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
             "avg_frame_rate": "60/1"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
        ],
        "format": {"duration": "10"},
    }

    def run(command, **_kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout=json.dumps(probe_payload), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(download_provider.subprocess, "run", run)

    assert validate_downloaded_media(media)["decode_errors"] == []
    decode_command = commands[1]
    assert decode_command[decode_command.index("-vf") + 1] == "setpts=N/(60*TB)"
    assert decode_command[decode_command.index("-af") + 1] == "asetpts=N/SR/TB"
