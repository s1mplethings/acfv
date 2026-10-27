import asyncio
from pathlib import Path
from types import SimpleNamespace

from acfv.runtime.stream_monitor import StreamMonitorConfig, StreamMonitorService, StreamTarget


def test_stream_monitor_uses_segment_muxer_and_emits_five_closed_segments(monkeypatch, tmp_path: Path) -> None:
    events = []
    commands = []
    target = StreamTarget(
        name="alice-live",
        url="https://twitch.tv/alice",
        platform="twitch",
        quality="best",
        poll_interval=30,
        fmt="mp4",
        output_dir=tmp_path / "captures",
    )
    config = StreamMonitorConfig(
        ffmpeg_path="ffmpeg",
        default_quality="best",
        default_poll_interval=30,
        default_format="mp4",
        output_root=tmp_path / "captures",
        targets=[target],
        segment_duration=60,
    )

    class FakeProcess:
        def __init__(self, command, recording):
            self.command = command
            self.recording = recording
            self.returncode = None

        async def communicate(self):
            if self.recording:
                pattern = Path(self.command[-1])
                for number in range(5):
                    Path(str(pattern).replace("%06d", f"{number:06d}")).write_bytes(b"segment")
                await asyncio.sleep(0)
            else:
                Path(self.command[-1]).write_bytes(b"final")
            self.returncode = 0
            return b"", b""

    async def fake_subprocess(*command, **_kwargs):
        commands.append(command)
        return FakeProcess(command, recording=len(commands) == 1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    service = StreamMonitorService(config, event_hook=events.append)
    data = SimpleNamespace(
        record_url="https://example.test/live.m3u8",
        m3u8_url=None,
        flv_url=None,
        anchor_name="Alice",
    )
    asyncio.run(service._record_once(target, data))

    assert "segment" in commands[0]
    assert "-segment_time" in commands[0]
    closed = [event for event in events if event.event == "segment_closed"]
    assert len(closed) == 5
    assert all(event.timestamp.utcoffset().total_seconds() == 0 for event in events)
    assert [event.details["start_ms"] for event in closed] == [0, 60_000, 120_000, 180_000, 240_000]
    assert [event.details["end_ms"] for event in closed] == [60_000, 120_000, 180_000, 240_000, 300_000]
    assert any(event.event == "recording_finished" for event in events)


def test_controlled_stop_finishes_recording_instead_of_reporting_failure(monkeypatch, tmp_path: Path) -> None:
    events = []
    commands = []
    target = StreamTarget(
        name="alice-live",
        url="https://twitch.tv/alice",
        platform="twitch",
        quality="best",
        poll_interval=30,
        fmt="mp4",
        output_dir=tmp_path / "captures",
    )
    config = StreamMonitorConfig(
        ffmpeg_path="ffmpeg",
        default_quality="best",
        default_poll_interval=30,
        default_format="mp4",
        output_root=tmp_path / "captures",
        targets=[target],
        segment_duration=60,
    )

    class FakeProcess:
        def __init__(self, command, recording):
            self.command = command
            self.recording = recording
            self.returncode = None

        async def communicate(self):
            if self.recording:
                pattern = Path(self.command[-1])
                Path(str(pattern).replace("%06d", "000000")).write_bytes(b"segment")
                self.returncode = 1
            else:
                Path(self.command[-1]).write_bytes(b"final")
                self.returncode = 0
            return b"", b""

    async def fake_subprocess(*command, **_kwargs):
        commands.append(command)
        return FakeProcess(command, recording=len(commands) == 1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    service = StreamMonitorService(config, event_hook=events.append)
    service._stop_event.set()
    data = SimpleNamespace(
        record_url="https://example.test/live.m3u8",
        m3u8_url=None,
        flv_url=None,
        anchor_name="Alice",
    )
    asyncio.run(service._record_once(target, data))

    finished = [event for event in events if event.event == "recording_finished"]
    assert len(finished) == 1
    assert finished[0].details["controlled_stop"] is True
    assert not [event for event in events if event.event == "recording_failed"]


def test_run_waits_for_slow_controlled_finalization_before_shutdown(tmp_path: Path) -> None:
    events = []
    target = StreamTarget(
        name="alice-live",
        url="https://twitch.tv/alice",
        platform="twitch",
        quality="best",
        poll_interval=30,
        fmt="mp4",
        output_dir=tmp_path / "captures",
    )
    config = StreamMonitorConfig(
        ffmpeg_path="ffmpeg",
        default_quality="best",
        default_poll_interval=30,
        default_format="mp4",
        output_root=tmp_path / "captures",
        targets=[target],
        segment_duration=60,
    )
    service = StreamMonitorService(config, event_hook=events.append)

    async def slow_finalization(_target, _run_once):
        # Real GPU queue draining can exceed the old five-second shutdown grace.
        await asyncio.sleep(5.1)
        service._emit_event(_target, "recording_finished", "finished", output="final.mp4")

    service._watch_target = slow_finalization
    service._stop_event.set()
    asyncio.run(service.run())

    assert [event.event for event in events] == ["recording_finished", "shutdown"]


def test_segment_is_not_published_until_previous_file_is_stable(tmp_path: Path) -> None:
    events = []
    target = StreamTarget(
        name="alice-live",
        url="https://twitch.tv/alice",
        platform="twitch",
        quality="best",
        poll_interval=30,
        fmt="mp4",
        output_dir=tmp_path,
    )
    config = StreamMonitorConfig(
        ffmpeg_path="ffmpeg",
        default_quality="best",
        default_poll_interval=30,
        default_format="mp4",
        output_root=tmp_path,
        targets=[target],
        segment_duration=60,
    )
    service = StreamMonitorService(config, event_hook=events.append)
    process = SimpleNamespace(returncode=None)
    first = tmp_path / "segment_000000.ts"
    second = tmp_path / "segment_000001.ts"
    first.write_bytes(b"partial")
    second.write_bytes(b"open")

    async def exercise():
        watcher = asyncio.create_task(service._watch_segment_files(target, process, tmp_path))
        await asyncio.sleep(0.2)
        first.write_bytes(b"complete segment")
        await asyncio.sleep(1.2)
        assert not [event for event in events if event.event == "segment_closed"]
        await asyncio.sleep(1.0)
        process.returncode = 0
        await watcher

    asyncio.run(exercise())

    closed = [event for event in events if event.event == "segment_closed"]
    assert closed[0].details["path"] == str(first)
