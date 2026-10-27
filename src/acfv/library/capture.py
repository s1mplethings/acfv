from __future__ import annotations

from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
import json
from typing import Any, Mapping

from .models import Recording, RecordingStatus, utc_now
from .service import LibraryService


def _channel_from_url(url: str) -> str:
    return url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()


def ensure_twitch_monitor_target(source: Any, config_path: Path | str | None = None) -> None:
    from acfv.runtime.stream_monitor import StreamTarget, load_stream_monitor_config, save_stream_monitor_config

    config, path, _created = load_stream_monitor_config(config_path)
    external_id = source.external_id.lower()
    if any(target.platform == "twitch" and _channel_from_url(target.url) == external_id for target in config.targets):
        return
    config.targets.append(
        StreamTarget(
            name=source.channel_name,
            url=source.channel_url or f"https://twitch.tv/{external_id}",
            platform="twitch",
            quality=config.default_quality,
            poll_interval=config.default_poll_interval,
            fmt=config.default_format,
            output_dir=config.output_root / external_id,
        )
    )
    save_stream_monitor_config(config, path)


def build_stream_library_bridge(config: Any, service: LibraryService | None = None) -> "StreamLibraryBridge":
    library = service or LibraryService()
    bindings: dict[str, str] = {}
    for target in config.targets:
        if target.platform != "twitch":
            continue
        external_id = _channel_from_url(target.url)
        source = library.repository.get_source_by_external("twitch", external_id)
        if source is None:
            creator = library.create_creator(target.name)
            source = library.add_source(
                creator.id,
                platform="twitch",
                external_id=external_id,
                channel_name=target.name,
                channel_url=target.url,
            )
        bindings[target.name] = source.id
    return StreamLibraryBridge(library, bindings, auto_process=True)


class StreamLibraryBridge:
    """Persist stream-monitor recording events without coupling the recorder to SQL."""

    def __init__(
        self,
        service: LibraryService,
        target_sources: Mapping[str, str],
        *,
        auto_process: bool = False,
        live_factory: Any = None,
        executor: Any = None,
    ) -> None:
        self.service = service
        self.target_sources = dict(target_sources)
        self._active: dict[str, str] = {}
        self._live: dict[str, Any] = {}
        self._segment_futures: dict[str, list[Future]] = {}
        self.auto_process = auto_process
        self.live_factory = live_factory
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="acfv-live-asr")

    def __call__(self, event: Any) -> None:
        source_id = self.target_sources.get(event.target)
        if source_id is None or event.event not in {
            "recording_started",
            "segment_closed",
            "chat_message",
            "recording_finished",
            "recording_failed",
        }:
            return
        source = self.service.repository.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown capture source: {source_id}")
        output = event.details.get("output")
        recording = self._find_recording(event.target, output)
        if event.event == "recording_started":
            if recording is None:
                path = Path(output) if output else None
                recording = self.service.register_recording(
                    creator_id=source.creator_id,
                    source_id=source.id,
                    title=path.stem if path else f"{source.channel_name} live recording",
                    local_path=path,
                    source_type="twitch_capture",
                    source_url=event.details.get("url") or source.channel_url,
                    started_at=event.timestamp,
                    recording_status=RecordingStatus.RECORDING,
                    require_file=False,
                )
            else:
                recording = self.service.update_recording_status(
                    recording.id, recording_status=RecordingStatus.RECORDING
                )
            try:
                metadata = json.loads(source.metadata_json or "{}")
            except json.JSONDecodeError:
                metadata = {}
            recording = self.service.set_analysis_profile(
                recording.id,
                str(metadata.get("analysis_profile_override") or "auto"),
            )
            self._active[event.target] = recording.id
            live = self._create_live(recording.id, event.details.get("recording_root"))
            self._live[event.target] = live
            warmup = getattr(live, "warmup", None)
            if self.auto_process and callable(warmup):
                self._segment_futures.setdefault(event.target, []).append(
                    self.executor.submit(warmup)
                )
            return

        if event.event == "segment_closed":
            if recording is None:
                return
            live = self._live.get(event.target) or self._create_live(recording.id, None)
            self._live[event.target] = live
            future = self.executor.submit(
                live.close_segment,
                str(event.details["segment_id"]),
                event.details["path"],
                int(event.details["start_ms"]),
                int(event.details["end_ms"]),
            )
            self._segment_futures.setdefault(event.target, []).append(future)
            return
        if event.event == "chat_message":
            if recording is None:
                return
            live = self._live.get(event.target) or self._create_live(recording.id, None)
            self._live[event.target] = live
            timestamp_ms = event.details.get("timestamp_ms")
            if timestamp_ms is None and recording.started_at and event.timestamp:
                timestamp_ms = max(0, int((event.timestamp - recording.started_at).total_seconds() * 1000))
            live.append_chat(
                int(timestamp_ms or 0),
                str(event.details.get("username") or "unknown"),
                str(event.details.get("message") or ""),
                **dict(event.details.get("metadata") or {}),
            )
            return

        if recording is None:
            return
        status = (
            RecordingStatus.COMPLETE
            if event.event == "recording_finished"
            else RecordingStatus.FAILED
        )
        completed = self.service.update_recording_status(
            recording.id,
            recording_status=status,
            local_path=output,
            ended_at=event.timestamp or utc_now(),
            error_message=event.message if status == RecordingStatus.FAILED else None,
        )
        segment_errors: list[Exception] = []
        for future in self._segment_futures.pop(event.target, []):
            try:
                future.result()
            except Exception as exc:
                segment_errors.append(exc)
        live = self._live.pop(event.target, None)
        self._active.pop(event.target, None)
        if segment_errors:
            raise RuntimeError(
                f"{len(segment_errors)} closed segment(s) failed processing; first error: {segment_errors[0]}"
            ) from segment_errors[0]
        if status == RecordingStatus.COMPLETE and live is not None:
            live.finalize(final_source=output)
        if status == RecordingStatus.COMPLETE and live is None and self.auto_process and output:
            path = Path(output)
            if path.is_file() and path.stat().st_size > 0:
                self.service.process_recording(recording.id)

    def _create_live(self, recording_id: str, root: str | None):
        if self.live_factory is not None:
            return self.live_factory(recording_id, self.service.repository, root=root)
        from acfv.live import LiveProcessingService

        return LiveProcessingService(
            recording_id,
            self.service.repository,
            root=Path(root) if root else None,
        )

    def _find_recording(self, target: str, output: str | None) -> Recording | None:
        active_id = self._active.get(target)
        if active_id:
            return self.service.get_recording(active_id)
        if output:
            return self.service.repository.get_recording_by_path(str(Path(output).expanduser().resolve()))
        return None
