from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from acfv.providers.download import (
    DownloadInterrupted,
    TwitchVodMetadata,
    download_twitch_vod_to,
    fetch_twitch_vod_metadata,
    normalize_twitch_vod_input,
    validate_downloaded_media,
)
from acfv.runtime.storage import storage_root

from .models import DownloadStatus, RecordingStatus, VodDownload, utc_now
from .service import LibraryService, _slugify


ProgressCallback = Callable[[dict[str, Any]], None]
MetadataFetcher = Callable[[str], TwitchVodMetadata]
Downloader = Callable[..., Path]
MediaValidator = Callable[[Path], dict[str, Any]]


class VodDownloadService:
    """Canonical durable owner for Twitch VOD discovery and download lifecycle."""

    _submit_lock = threading.RLock()

    def __init__(
        self,
        library: LibraryService | None = None,
        *,
        media_root: Path | str | None = None,
        metadata_fetcher: MetadataFetcher = fetch_twitch_vod_metadata,
        downloader: Downloader = download_twitch_vod_to,
        media_validator: MediaValidator = validate_downloaded_media,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.library = library or LibraryService()
        self.repository = self.library.repository
        self.media_root = Path(media_root or storage_root() / "library").resolve()
        self.metadata_fetcher = metadata_fetcher
        self.downloader = downloader
        self.media_validator = media_validator
        self.sleep = sleep

    def discover(
        self,
        source: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        provider: str = "twitch-downloader",
    ) -> VodDownload:
        platform, vod_id, source_url = normalize_twitch_vod_input(source)
        self._validate_range(start_ms, end_ms)
        with self._submit_lock:
            existing = self.repository.get_vod_download_by_external(platform, vod_id)
            if existing is not None:
                if (
                    existing.status in {DownloadStatus.FAILED, DownloadStatus.INTERRUPTED}
                    and (start_ms is not None or end_ms is not None)
                    and (
                        existing.requested_start_ms != start_ms
                        or existing.requested_end_ms != end_ms
                    )
                ):
                    existing.requested_start_ms = start_ms
                    existing.requested_end_ms = end_ms
                    existing.status = DownloadStatus.DISCOVERED
                    existing.error_message = None
                    existing.percent = 0.0
                    existing.downloaded_bytes = 0
                    existing.retry_count = 0
                    metadata = json.loads(existing.metadata_json or "{}")
                    metadata.update({
                        "is_range_download": True,
                        "requested_start_ms": start_ms,
                        "requested_end_ms": end_ms,
                        "range_revision_reason": "retry_after_failed_or_interrupted_download",
                    })
                    existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
                    existing.updated_at = utc_now()
                    existing = self.repository.save(existing)
                    if existing.recording_id:
                        recording = self.library.get_recording(str(existing.recording_id))
                        if recording is not None:
                            recording.is_partial_source = True
                            recording.source_start_offset_ms = start_ms
                            recording.source_end_offset_ms = end_ms
                            recording.download_metadata_json = existing.metadata_json
                            self.repository.save(recording)
                return existing
            metadata = self.metadata_fetcher(source_url)
            creator = self.library.create_creator(metadata.creator_name, slug=metadata.creator_login)
            channel_external = metadata.creator_id or metadata.creator_login
            source_row = self.library.add_source(
                creator.id,
                platform=platform,
                external_id=channel_external,
                channel_name=metadata.creator_name,
                source_type="vod_channel",
                channel_url=f"https://www.twitch.tv/{metadata.creator_login}",
                metadata={"login": metadata.creator_login},
            )
            recording = self.repository.get_recording_by_external_vod_id(vod_id)
            if recording is None:
                recording = self.library.register_recording(
                    creator_id=creator.id,
                    source_id=source_row.id,
                    title=metadata.title,
                    source_type="vod_download",
                    source_url=source_url,
                    started_at=metadata.created_at,
                    recording_status=RecordingStatus.DISCOVERED,
                    content_type=(metadata.category or "other").casefold(),
                    require_file=False,
                )
                recording.external_vod_id = vod_id
                recording.provider = provider
                recording.is_partial_source = start_ms is not None or end_ms is not None
                recording.source_start_offset_ms = start_ms
                recording.source_end_offset_ms = end_ms
                recording.download_metadata_json = json.dumps(self._metadata_payload(metadata), ensure_ascii=False)
                recording = self.repository.save(recording)
            directory = self.media_root / _slugify(metadata.creator_login) / recording.id
            final_path = directory / "source.mp4"
            temp_path = directory / "source.part.mp4"
            payload = self._metadata_payload(metadata)
            payload.update({
                "is_range_download": start_ms is not None or end_ms is not None,
                "requested_start_ms": start_ms,
                "requested_end_ms": end_ms,
                "resume_strategy": "SAFE_RESTART_ONLY",
            })
            return self.repository.save(VodDownload(
                platform=platform,
                external_vod_id=vod_id,
                recording_id=recording.id,
                source_url=source_url,
                provider=provider,
                status=DownloadStatus.DISCOVERED,
                requested_start_ms=start_ms,
                requested_end_ms=end_ms,
                temp_path=str(temp_path),
                final_path=str(final_path),
                metadata_json=json.dumps(payload, ensure_ascii=False),
            ))

    def download(
        self,
        download_id: str,
        *,
        auto_process: bool = True,
        wait_for_processing: bool = False,
        config_manager: Any = None,
        run_dir: Path | str | None = None,
        output_clips_dir: Path | str | None = None,
        max_retries: int = 2,
        cancel_event: threading.Event | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> VodDownload:
        job = self._require(download_id)
        if job.status in {DownloadStatus.DOWNLOADED, DownloadStatus.PROCESSING, DownloadStatus.READY}:
            return job
        temp_path = Path(job.temp_path or "")
        final_path = Path(job.final_path or "")
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        job.status = DownloadStatus.DOWNLOAD_PENDING
        job.error_message = None
        job.updated_at = utc_now()
        job = self.repository.save(job)
        attempts = max(1, int(max_retries) + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            job.status = DownloadStatus.DOWNLOADING
            job.retry_count = attempt
            job.updated_at = utc_now()
            job = self.repository.save(job)
            phase = "TRANSFER_IN_PROGRESS"
            validation: dict[str, Any] | None = None
            job = self._set_lifecycle(job.id, phase, attempt=attempt)
            try:
                self.downloader(
                    job.external_vod_id,
                    temp_path,
                    start_ms=job.requested_start_ms,
                    end_ms=job.requested_end_ms,
                    progress_callback=lambda update: self._record_progress(job.id, update, progress_callback),
                    cancel_event=cancel_event,
                )
                phase = "TRANSFER_COMPLETED"
                job = self._set_lifecycle(job.id, phase, attempt=attempt)
                expected_ms = self._expected_duration(job)
                phase = "MEDIA_INTEGRITY_VALIDATION"
                job = self._set_lifecycle(
                    job.id,
                    phase,
                    attempt=attempt,
                    expected_duration_ms=expected_ms,
                )
                validation = self.media_validator(temp_path)
                if expected_ms is not None and abs(int(validation["duration_ms"]) - expected_ms) > 5000:
                    raise ValueError(
                        f"Downloaded duration {validation['duration_ms']} ms differs from expected {expected_ms} ms by more than 5000 ms"
                    )
                phase = "DOWNLOAD_READY"
                job = self._set_lifecycle(
                    job.id,
                    phase,
                    attempt=attempt,
                    media_validation=validation,
                )
                os.replace(temp_path, final_path)
                job = self._require(job.id)
                metadata = json.loads(job.metadata_json or "{}")
                metadata["media_validation"] = validation
                job.metadata_json = json.dumps(metadata, ensure_ascii=False)
                job.downloaded_bytes = final_path.stat().st_size
                job.total_bytes = job.downloaded_bytes
                job.percent = 100.0
                job.status = DownloadStatus.DOWNLOADED
                job.final_path = str(final_path)
                job.error_message = None
                job.updated_at = utc_now()
                job = self.repository.save(job)
                recording = self.library.update_recording_status(
                    str(job.recording_id),
                    recording_status=RecordingStatus.COMPLETE,
                    local_path=final_path,
                    error_message=None,
                )
                recording.download_metadata_json = job.metadata_json
                recording.duration_ms = int(validation["duration_ms"])
                recording.file_size = int(validation["file_size"])
                recording.is_partial_source = job.requested_start_ms is not None or job.requested_end_ms is not None
                recording.source_start_offset_ms = job.requested_start_ms
                recording.source_end_offset_ms = job.requested_end_ms
                self.repository.save(recording)
                phase = "INGEST_READY"
                job = self._set_lifecycle(job.id, phase, attempt=attempt)
                recording.download_metadata_json = job.metadata_json
                self.repository.save(recording)
                if auto_process:
                    job.status = DownloadStatus.PROCESSING
                    job.updated_at = utc_now()
                    job = self.repository.save(job)
                    self.library.process_recording(
                        str(job.recording_id),
                        config_manager=config_manager,
                        run_dir=run_dir,
                        output_clips_dir=output_clips_dir,
                        wait_for_completion=wait_for_processing,
                    )
                    if wait_for_processing:
                        job = self.refresh_processing_status(job.id)
                return job
            except DownloadInterrupted as exc:
                job = self._mark_failure(
                    job.id,
                    DownloadStatus.INTERRUPTED,
                    exc,
                    failure_code="TRANSFER_INTERRUPTED",
                    lifecycle_state="RECOVERY_REQUIRED",
                )
                raise
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    job = self._set_lifecycle(
                        job.id,
                        "RECOVERY_REQUIRED",
                        attempt=attempt,
                        failure_code=self._failure_code(phase),
                        media_validation=validation,
                        error=str(exc),
                    )
                    self.sleep(min(2**attempt, 4))
                    continue
                job = self._mark_failure(
                    job.id,
                    DownloadStatus.FAILED,
                    exc,
                    failure_code=self._failure_code(phase),
                    lifecycle_state="RECOVERY_REQUIRED",
                    media_validation=validation,
                )
                raise
        raise RuntimeError(str(last_error or "Download failed"))

    def refresh_processing_status(self, download_id: str) -> VodDownload:
        job = self._require(download_id)
        if not job.recording_id:
            return job
        recording = self.library.get_recording(job.recording_id)
        if recording and recording.processing_status.value == "READY":
            job.status = DownloadStatus.READY
            job.updated_at = utc_now()
            return self.repository.save(job)
        if recording and recording.processing_status.value == "FAILED":
            return self._mark_failure(job.id, DownloadStatus.FAILED, RuntimeError(recording.error_message or "Processing failed"))
        return job

    def get(self, download_id: str) -> VodDownload | None:
        return self.repository.get_vod_download(download_id)

    def list(self) -> list[VodDownload]:
        return self.repository.list_vod_downloads()

    def _record_progress(self, download_id: str, update: dict[str, Any], callback: ProgressCallback | None) -> None:
        job = self._require(download_id)
        for key in ("downloaded_bytes", "total_bytes", "percent", "speed_bps", "eta_seconds"):
            if key in update and update[key] is not None:
                if key in {"downloaded_bytes", "percent"}:
                    setattr(job, key, max(float(getattr(job, key) or 0), float(update[key])))
                else:
                    setattr(job, key, update[key])
        job.updated_at = utc_now()
        self.repository.save(job)
        if callback:
            callback(update)

    def _mark_failure(
        self,
        download_id: str,
        status: DownloadStatus,
        error: Exception,
        *,
        failure_code: str | None = None,
        lifecycle_state: str | None = None,
        media_validation: dict[str, Any] | None = None,
    ) -> VodDownload:
        job = self._require(download_id)
        job.status = status
        job.error_message = str(error)
        if job.temp_path and Path(job.temp_path).exists():
            job.downloaded_bytes = Path(job.temp_path).stat().st_size
        metadata = json.loads(job.metadata_json or "{}")
        if failure_code:
            metadata["failure_code"] = failure_code
        if media_validation is not None:
            metadata["last_media_validation"] = media_validation
        if lifecycle_state:
            self._append_lifecycle(metadata, lifecycle_state, failure_code=failure_code, error=str(error))
        job.metadata_json = json.dumps(metadata, ensure_ascii=False)
        job.updated_at = utc_now()
        return self.repository.save(job)

    def _set_lifecycle(self, download_id: str, state: str, **details: Any) -> VodDownload:
        job = self._require(download_id)
        metadata = json.loads(job.metadata_json or "{}")
        self._append_lifecycle(metadata, state, **details)
        job.metadata_json = json.dumps(metadata, ensure_ascii=False)
        job.updated_at = utc_now()
        return self.repository.save(job)

    @staticmethod
    def _append_lifecycle(metadata: dict[str, Any], state: str, **details: Any) -> None:
        history = metadata.setdefault("download_lifecycle", [])
        if not isinstance(history, list):
            history = []
            metadata["download_lifecycle"] = history
        event = {"state": state, "at": utc_now().isoformat()}
        event.update({key: value for key, value in details.items() if value is not None})
        history.append(event)
        metadata["download_lifecycle_state"] = state

    @staticmethod
    def _failure_code(phase: str) -> str:
        if phase == "MEDIA_INTEGRITY_VALIDATION":
            return "INCOMPLETE_MEDIA"
        if phase == "DOWNLOAD_READY":
            return "PROMOTION_FAILED"
        return "TRANSFER_FAILED"

    def _expected_duration(self, job: VodDownload) -> int | None:
        metadata = json.loads(job.metadata_json or "{}")
        remote_ms = int(metadata.get("duration_ms") or 0)
        start = int(job.requested_start_ms or 0)
        end = int(job.requested_end_ms) if job.requested_end_ms is not None else remote_ms
        return max(0, end - start) or None

    def _require(self, download_id: str) -> VodDownload:
        job = self.repository.get_vod_download(download_id)
        if job is None:
            raise KeyError(f"Unknown VOD download: {download_id}")
        return job

    @staticmethod
    def _validate_range(start_ms: int | None, end_ms: int | None) -> None:
        if start_ms is not None and start_ms < 0:
            raise ValueError("start_ms must be >= 0")
        if end_ms is not None and end_ms <= 0:
            raise ValueError("end_ms must be > 0")
        if start_ms is not None and end_ms is not None and end_ms <= start_ms:
            raise ValueError("end_ms must be greater than start_ms")

    @staticmethod
    def _metadata_payload(metadata: TwitchVodMetadata) -> dict[str, Any]:
        payload = asdict(metadata)
        payload["created_at"] = metadata.created_at.isoformat() if metadata.created_at else None
        return payload


__all__ = ["VodDownloadService", "validate_downloaded_media"]
