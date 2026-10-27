from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from acfv.backend import service as backend_service

from .models import Creator, IndexStatus, LibraryFolder, ProcessingStatus, Recording, RecordingStatus, Source, utc_now
from .repository import LibraryRepository
from .scanner import LibraryFolderWatcher, canonical_path, is_supported_video, iter_video_files, probe_duration_ms, wait_until_stable


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "creator"


class LibraryService:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        *,
        job_create: Callable[..., dict[str, Any]] = backend_service.create_job,
        job_wait: Callable[..., dict[str, Any]] = backend_service.wait_for_job,
        job_status: Callable[..., dict[str, Any]] = backend_service.get_job_status,
        index_root: Path | str | None = None,
    ) -> None:
        self.repository = LibraryRepository(db_path)
        self.repository.bootstrap()
        self._job_create = job_create
        self._job_wait = job_wait
        self._job_status = job_status
        self._index_root = Path(index_root).resolve() if index_root is not None else None
        self._watchers: dict[str, LibraryFolderWatcher] = {}

    def create_creator(self, display_name: str, *, slug: Optional[str] = None, avatar_url: Optional[str] = None) -> Creator:
        name = display_name.strip()
        if not name:
            raise ValueError("Creator display name is required")
        normalized = _slugify(slug or name)
        existing = self.repository.get_creator_by_slug(normalized)
        if existing:
            return existing
        return self.repository.save(
            Creator(display_name=name, slug=normalized, avatar_url=avatar_url, legacy_name=name)
        )

    def update_creator(self, creator_id: str, **changes: Any) -> Creator:
        creator = self._require_creator(creator_id)
        if "display_name" in changes:
            display_name = str(changes["display_name"] or "").strip()
            if not display_name:
                raise ValueError("Creator display name is required")
            creator.display_name = display_name
        if "avatar_url" in changes:
            creator.avatar_url = changes["avatar_url"]
        if "slug" in changes:
            slug = _slugify(str(changes["slug"] or ""))
            existing = self.repository.get_creator_by_slug(slug)
            if existing is not None and existing.id != creator.id:
                raise ValueError(f"Creator slug is already in use: {slug}")
            creator.slug = slug
        creator.legacy_name = creator.display_name
        creator.updated_at = utc_now()
        return self.repository.save(creator)

    def list_creators(self) -> list[Creator]:
        return self.repository.list_creators()

    def add_source(
        self,
        creator_id: str,
        *,
        platform: str,
        external_id: str,
        channel_name: str,
        source_type: str = "live_channel",
        channel_url: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Source:
        self._require_creator(creator_id)
        platform = platform.strip().lower()
        external_id = external_id.strip().lower()
        if not platform or not external_id or not channel_name.strip():
            raise ValueError("platform, external_id, and channel_name are required")
        existing = self.repository.get_source_by_external(platform, external_id)
        if existing:
            if existing.creator_id != creator_id:
                raise ValueError("Source is already assigned to another creator")
            return existing
        return self.repository.save(
            Source(
                creator_id=creator_id,
                platform=platform,
                source_type=source_type,
                external_id=external_id,
                channel_name=channel_name.strip(),
                channel_url=channel_url,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            )
        )

    def list_sources(self, creator_id: Optional[str] = None) -> list[Source]:
        return self.repository.list_sources(creator_id)

    def set_source_enabled(self, source_id: str, enabled: bool) -> Source:
        source = self.repository.get_source(source_id)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        source.enabled = bool(enabled)
        source.updated_at = utc_now()
        return self.repository.save(source)

    def register_recording(
        self,
        *,
        creator_id: str,
        title: str,
        source_id: Optional[str] = None,
        local_path: Optional[Path | str] = None,
        source_type: str = "local",
        source_url: Optional[str] = None,
        started_at: Optional[datetime] = None,
        recording_status: RecordingStatus = RecordingStatus.DISCOVERED,
        content_type: str = "other",
        analysis_profile: Optional[dict[str, bool]] = None,
        profile_source: str = "automatic",
        require_file: bool = True,
    ) -> Recording:
        self._require_creator(creator_id)
        if source_id:
            source = self.repository.get_source(source_id)
            if source is None or source.creator_id != creator_id:
                raise ValueError("Source does not belong to creator")
        resolved = None
        canonical = None
        file_size = None
        file_mtime_ns = None
        duration_ms = None
        if local_path is not None:
            resolved = Path(local_path).expanduser().resolve()
            if require_file and not resolved.is_file():
                raise ValueError(f"Recording file does not exist: {resolved}")
            if resolved.exists() and not is_supported_video(resolved):
                raise ValueError(f"Unsupported video extension: {resolved.suffix}")
            canonical = canonical_path(resolved)
            existing = self.repository.get_recording_by_path(canonical)
            if existing:
                return existing
            if resolved.is_file():
                stat = resolved.stat()
                file_size, file_mtime_ns = stat.st_size, stat.st_mtime_ns
                duration_ms = probe_duration_ms(resolved)
        return self.repository.save(
            Recording(
                creator_id=creator_id,
                source_id=source_id,
                title=title.strip() or (resolved.stem if resolved else "Untitled Recording"),
                source_type=source_type,
                source_url=source_url,
                local_path=str(resolved) if resolved else None,
                canonical_path=canonical,
                started_at=started_at,
                recording_status=recording_status,
                content_type=content_type,
                analysis_profile_json=json.dumps(analysis_profile or {}, ensure_ascii=False),
                profile_source=profile_source,
                file_size=file_size,
                file_mtime_ns=file_mtime_ns,
                duration_ms=duration_ms,
            )
        )

    def add_video(self, path: Path | str, *, creator_id: Optional[str] = None, source_type: str = "local", source_url: Optional[str] = None, title: Optional[str] = None) -> Recording:
        local = Path(path).expanduser().resolve()
        creator = creator_id or self.repository.default_creator().id
        return self.register_recording(
            creator_id=creator,
            title=title or local.stem,
            local_path=local,
            source_type=source_type,
            source_url=source_url,
        )

    def get_recording(self, recording_id: str) -> Optional[Recording]:
        return self.repository.get_recording(recording_id)

    def list_recordings(self, creator_id: Optional[str] = None) -> list[Recording]:
        return self.repository.list_recordings(creator_id)

    def set_analysis_profile(self, recording_id: str, profile: str = "auto") -> Recording:
        from acfv.live.profile import resolve_analysis_profile

        recording = self._require_recording(recording_id)
        resolved = resolve_analysis_profile(
            {"title": recording.title, "content_type": recording.content_type},
            override=profile,
        )
        recording.content_type = resolved.name
        recording.analysis_profile_json = json.dumps(resolved.to_dict(), ensure_ascii=False)
        recording.profile_source = "automatic" if profile.casefold() == "auto" else "user"
        recording.updated_at = utc_now()
        return self.repository.save(recording)

    def set_creator_analysis_profile(self, creator_id: str, profile: str = "auto") -> list[Recording]:
        from acfv.live.profile import resolve_analysis_profile

        creator = self._require_creator(creator_id)
        resolved = resolve_analysis_profile({"creator": creator.display_name}, override=profile)
        for source in self.repository.list_sources(creator_id):
            try:
                metadata = json.loads(source.metadata_json or "{}")
            except json.JSONDecodeError:
                metadata = {}
            metadata["analysis_profile_override"] = profile.casefold()
            source.metadata_json = json.dumps(metadata, ensure_ascii=False)
            source.updated_at = utc_now()
            self.repository.save(source)
        updated = []
        for recording in self.list_recordings(creator_id):
            recording.content_type = resolved.name
            recording.analysis_profile_json = json.dumps(resolved.to_dict(), ensure_ascii=False)
            recording.profile_source = "automatic" if profile.casefold() == "auto" else "creator"
            recording.updated_at = utc_now()
            updated.append(self.repository.save(recording))
        return updated

    def update_recording_status(self, recording_id: str, *, recording_status: Optional[RecordingStatus] = None, processing_status: Optional[ProcessingStatus] = None, index_status: Optional[IndexStatus] = None, error_message: Optional[str] = None, local_path: Optional[Path | str] = None, ended_at: Optional[datetime] = None) -> Recording:
        recording = self._require_recording(recording_id)
        if recording_status is not None:
            recording.recording_status = recording_status
        if processing_status is not None:
            recording.processing_status = processing_status
        if index_status is not None:
            recording.index_status = index_status
        if local_path is not None:
            local = Path(local_path).expanduser().resolve()
            recording.local_path = str(local)
            recording.canonical_path = canonical_path(local)
            if local.is_file():
                stat = local.stat()
                recording.file_size = stat.st_size
                recording.file_mtime_ns = stat.st_mtime_ns
                recording.duration_ms = probe_duration_ms(local)
        if ended_at is not None:
            recording.ended_at = ended_at
        recording.error_message = error_message
        recording.updated_at = utc_now()
        return self.repository.save(recording)

    def process_recording(
        self,
        recording_id: str,
        *,
        config_manager: Any = None,
        run_dir: Path | str | None = None,
        output_clips_dir: Path | str | None = None,
        wait_for_completion: bool = False,
    ) -> Recording:
        """Process a recording through the canonical backend pipeline.

        ``run_dir`` is optional for interactive callers. Long-running library
        builds should provide a stable directory so retries reuse completed
        pipeline artifacts and ASR chunk checkpoints instead of starting over.
        """
        recording = self._require_recording(recording_id)
        if not recording.local_path:
            raise ValueError("Recording has no local media path")
        recording = self.update_recording_status(
            recording_id,
            processing_status=ProcessingStatus.PROCESSING,
            index_status=IndexStatus.NOT_INDEXED,
            error_message=None,
        )
        try:
            snapshot = self._job_create(
                video_path=recording.local_path,
                chat_path=None,
                config_manager=config_manager,
                run_dir=run_dir,
                output_clips_dir=str(output_clips_dir) if output_clips_dir is not None else None,
                metadata={"library_recording_id": recording.id},
            )
            recording.last_job_id = str(snapshot["job_id"])
            recording.artifact_root = snapshot.get("run_dir")
            recording = self.repository.save(recording)
        except Exception as exc:
            self.update_recording_status(recording_id, processing_status=ProcessingStatus.FAILED, error_message=str(exc))
            raise
        if wait_for_completion:
            # CLI callers must not exit while the daemon persistence worker is
            # still finalizing Moments and the retrieval index.
            self._persist_terminal_job_state(recording.id, recording.last_job_id, recording.artifact_root)
            return self._require_recording(recording.id)
        threading.Thread(
            target=self._persist_terminal_job_state,
            args=(recording.id, recording.last_job_id, recording.artifact_root),
            daemon=True,
        ).start()
        return recording

    def retry_processing(self, recording_id: str, *, config_manager: Any = None) -> Recording:
        return self.process_recording(recording_id, config_manager=config_manager)

    def reindex_recording(self, recording_id: str) -> Recording:
        return self.update_recording_status(recording_id, index_status=IndexStatus.NOT_INDEXED)

    def add_folder(self, path: Path | str, *, creator_id: Optional[str] = None, stable_interval: float = 1.0, stable_checks: int = 2) -> tuple[LibraryFolder, list[Recording]]:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Library folder does not exist: {root}")
        owner = creator_id or self.repository.default_creator().id
        canonical = canonical_path(root)
        folder = self.repository.get_folder_by_path(canonical)
        if folder is None:
            folder = self.repository.save(LibraryFolder(creator_id=owner, path=str(root), canonical_path=canonical))
        recordings = []
        for candidate in iter_video_files(root):
            if wait_until_stable(candidate, interval=stable_interval, checks=stable_checks):
                recordings.append(self.add_video(candidate, creator_id=folder.creator_id, source_type="folder"))
        return folder, recordings

    def list_folders(self) -> list[LibraryFolder]:
        return self.repository.list_folders()

    def watch_folder(self, folder_id: str) -> None:
        folder = next((item for item in self.repository.list_folders() if item.id == folder_id), None)
        if folder is None:
            raise KeyError(f"Unknown library folder: {folder_id}")
        watcher = LibraryFolderWatcher()
        watcher.start(folder.path, lambda path: self.add_video(path, creator_id=folder.creator_id, source_type="folder"))
        previous = self._watchers.pop(folder_id, None)
        if previous:
            previous.stop()
        self._watchers[folder_id] = watcher

    def stop_watchers(self) -> None:
        for watcher in self._watchers.values():
            watcher.stop()
        self._watchers.clear()

    def _persist_terminal_job_state(self, recording_id: str, job_id: str, artifact_root: str | None) -> None:
        try:
            self._watch_incremental_artifacts(recording_id, job_id, artifact_root)
            snapshot = self._job_wait(job_id)
            recording = self._require_recording(recording_id)
            recording.artifact_root = snapshot.get("run_dir") or recording.artifact_root
            self.repository.save(recording)
            if snapshot.get("status") != "succeeded":
                self.update_recording_status(
                    recording_id,
                    processing_status=ProcessingStatus.FAILED,
                    error_message=str(snapshot.get("error_summary") or snapshot.get("status")),
                )
                return

            from acfv.moments import MomentFinalizer
            from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex

            moments = MomentFinalizer(self.repository).finalize_artifacts(
                recording_id, snapshot.get("run_dir") or artifact_root
            )
            if not moments:
                raise RuntimeError("Processing produced no FINAL Moments")
            self.update_recording_status(recording_id, index_status=IndexStatus.INDEXING)
            index = PersistentMomentIndex(self.repository, index_root=self._index_root)
            HybridRetrievalService(self.repository, index).rebuild()
            indexed = sum(row.recording_id == recording_id for row in index.rows())
            if indexed != len(moments):
                raise RuntimeError(
                    f"Moment index mismatch for {recording_id}: FINAL={len(moments)} indexed={indexed}"
                )
            self.update_recording_status(
                recording_id,
                processing_status=ProcessingStatus.READY,
                index_status=IndexStatus.READY,
                error_message=None,
            )
        except Exception as exc:
            self.update_recording_status(
                recording_id,
                processing_status=ProcessingStatus.FAILED,
                index_status=IndexStatus.FAILED,
                error_message=str(exc),
            )

    def _watch_incremental_artifacts(self, recording_id: str, job_id: str, artifact_root: str | None) -> None:
        if not artifact_root:
            return
        from acfv.moments.artifacts import sync_incremental_artifacts

        last_mtime = None
        while True:
            snapshot = self._job_status(job_id)
            transcript = Path(artifact_root) / "work" / "transcript_merged.json"
            if transcript.is_file():
                mtime = transcript.stat().st_mtime_ns
                if mtime != last_mtime:
                    sync_incremental_artifacts(self.repository, recording_id, artifact_root)
                    last_mtime = mtime
            if snapshot.get("status") in {"succeeded", "failed", "cancelled"}:
                return
            time.sleep(0.5)

    def _require_creator(self, creator_id: str) -> Creator:
        creator = self.repository.get_creator(creator_id)
        if creator is None:
            raise KeyError(f"Unknown creator: {creator_id}")
        return creator

    def _require_recording(self, recording_id: str) -> Recording:
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        return recording
