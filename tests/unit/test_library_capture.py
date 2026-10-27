from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from acfv.library import LibraryService, RecordingStatus, StreamLibraryBridge, build_stream_library_bridge
from acfv.runtime.stream_monitor import StreamTarget


def _event(name: str, path: Path, *, message: str | None = None):
    return SimpleNamespace(
        timestamp=datetime.now(timezone.utc),
        target="alice-live",
        event=name,
        message=message,
        details={"output": str(path), "url": "https://live.example/alice.m3u8"},
    )


def test_twitch_capture_event_lifecycle(tmp_path: Path) -> None:
    service = LibraryService(tmp_path / "library.db")
    creator = service.create_creator("Alice")
    source = service.add_source(
        creator.id,
        platform="twitch",
        external_id="alice",
        channel_name="Alice",
        channel_url="https://twitch.tv/alice",
    )
    bridge = StreamLibraryBridge(service, {"alice-live": source.id})
    output = tmp_path / "alice-20261006.mp4"

    bridge(_event("live", output))
    assert service.list_recordings() == []

    bridge(_event("recording_started", output))
    recordings = service.list_recordings()
    assert len(recordings) == 1
    assert recordings[0].recording_status == RecordingStatus.RECORDING
    assert recordings[0].source_id == source.id
    assert recordings[0].local_path == str(output.resolve())

    output.touch()
    bridge(_event("recording_finished", output))
    completed = service.get_recording(recordings[0].id)
    assert completed is not None
    assert completed.recording_status == RecordingStatus.COMPLETE
    assert completed.ended_at is not None


def test_twitch_capture_failure_is_retryable_state(tmp_path: Path) -> None:
    service = LibraryService(tmp_path / "library.db")
    creator = service.create_creator("Alice")
    source = service.add_source(
        creator.id, platform="twitch", external_id="alice", channel_name="Alice"
    )
    bridge = StreamLibraryBridge(service, {"alice-live": source.id})
    output = tmp_path / "failed.mp4"

    bridge(_event("recording_started", output))
    bridge(_event("recording_failed", output, message="ffmpeg exited with 1"))

    failed = service.list_recordings()[0]
    assert failed.recording_status == RecordingStatus.FAILED
    assert failed.error_message == "ffmpeg exited with 1"


def test_monitor_config_targets_are_bound_to_library_sources(tmp_path: Path) -> None:
    service = LibraryService(tmp_path / "library.db")
    target = StreamTarget(
        name="alice-live",
        url="https://twitch.tv/alice",
        platform="twitch",
        quality="best",
        poll_interval=30,
        fmt="mp4",
        output_dir=tmp_path / "recordings",
    )
    config = SimpleNamespace(targets=[target])

    bridge = build_stream_library_bridge(config, service)
    bridge(_event("recording_started", tmp_path / "alice.mp4"))

    assert service.list_sources()[0].external_id == "alice"
    assert service.list_recordings()[0].recording_status == RecordingStatus.RECORDING


def test_segment_failure_cleans_active_session_before_next_capture(tmp_path: Path) -> None:
    service = LibraryService(tmp_path / "library.db")
    creator = service.create_creator("Alice")
    source = service.add_source(
        creator.id, platform="twitch", external_id="alice", channel_name="Alice"
    )

    class FailingLive:
        def close_segment(self, *_args):
            raise RuntimeError("ASR failed")

    bridge = StreamLibraryBridge(
        service,
        {"alice-live": source.id},
        live_factory=lambda *_args, **_kwargs: FailingLive(),
    )
    first = tmp_path / "first.mp4"
    bridge(_event("recording_started", first))
    segment = tmp_path / "segment_000000.ts"
    segment.write_bytes(b"media")
    bridge(
        SimpleNamespace(
            timestamp=datetime.now(timezone.utc),
            target="alice-live",
            event="segment_closed",
            message=None,
            details={
                "output": str(first),
                "segment_id": segment.stem,
                "path": str(segment),
                "start_ms": 0,
                "end_ms": 60_000,
            },
        )
    )

    try:
        bridge(_event("recording_failed", first, message="ffmpeg exited"))
    except RuntimeError as exc:
        assert "closed segment(s) failed processing" in str(exc)
    else:
        raise AssertionError("segment processing failure should be reported")

    assert bridge._active == {}
    assert bridge._live == {}
    assert bridge._segment_futures == {}
    assert service.list_recordings()[0].recording_status == RecordingStatus.FAILED

    second = tmp_path / "second.mp4"
    bridge(_event("recording_started", second))
    assert len(service.list_recordings()) == 2


def test_live_runtime_warms_before_first_closed_segment(tmp_path: Path) -> None:
    service = LibraryService(tmp_path / "library.db")
    creator = service.create_creator("Alice")
    source = service.add_source(
        creator.id, platform="twitch", external_id="alice", channel_name="Alice"
    )
    calls: list[str] = []

    class TrackingLive:
        def warmup(self) -> bool:
            calls.append("warmup")
            return True

        def close_segment(self, *_args) -> None:
            calls.append("segment")

        def finalize(self, *, final_source) -> None:
            calls.append("finalize")

    bridge = StreamLibraryBridge(
        service,
        {"alice-live": source.id},
        auto_process=True,
        live_factory=lambda *_args, **_kwargs: TrackingLive(),
    )
    output = tmp_path / "alice.mp4"
    bridge(_event("recording_started", output))
    segment = tmp_path / "segment_000000.ts"
    segment.write_bytes(b"media")
    bridge(
        SimpleNamespace(
            timestamp=datetime.now(timezone.utc),
            target="alice-live",
            event="segment_closed",
            message=None,
            details={
                "output": str(output),
                "segment_id": segment.stem,
                "path": str(segment),
                "start_ms": 0,
                "end_ms": 60_000,
            },
        )
    )
    output.write_bytes(b"media")
    bridge(_event("recording_finished", output))

    assert calls == ["warmup", "segment", "finalize"]
