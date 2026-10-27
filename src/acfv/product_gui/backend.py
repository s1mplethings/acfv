"""Thin GUI adapter over the canonical ACFV product services."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

from acfv.app.gui_job_controller import GuiJobController
from acfv.clips import ClipService, GuiVariantWorkflowService
from acfv.config import ConfigManager
from acfv.conversation import GroundedConversationService
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService, VodDownloadService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope
from acfv.runtime.storage import storage_root
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.voice_profile import CreatorVoiceProfileService, VoiceProfileInsufficientData
from acfv.providers.avatar_identity import ExistingAvatarModelAdapter

from .viewmodels import ClipVM, CreatorVM, MomentVM, RecordingVM, VariantVM, media_exists


PROFILE_ORDER = ("SHORT", "STANDARD", "LONG", "FULL_EVENT")


class ProductBackend:
    """Presentation adapter; canonical services retain all domain ownership."""

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        index_root: Path | None = None,
        clip_root: Path | None = None,
        config_manager: Any | None = None,
    ) -> None:
        self.library = LibraryService(db_path, index_root=index_root)
        self.index_root = Path(index_root or storage_root() / "moment_index").resolve()
        self.clip_root = Path(clip_root or storage_root() / "clips").resolve()
        self.clip_root.mkdir(parents=True, exist_ok=True)
        self.config = config_manager or ConfigManager()
        self.index = PersistentMomentIndex(self.library.repository, self.index_root)
        self.retrieval = HybridRetrievalService(self.library.repository, self.index)
        self.conversation = GroundedConversationService(self.retrieval)
        self.clips = ClipService(self.library.repository)
        self.feedback = FeedbackService(self.library.repository)
        self.jobs = GuiJobController()
        self.vod = VodDownloadService(self.library)
        self.creator_adaptive = CreatorAdaptiveRepository(Path(db_path) if db_path else None)

    @classmethod
    def from_environment(cls, *, config_manager: Any | None = None) -> "ProductBackend":
        db = os.environ.get("ACFV_GUI_LIBRARY_DB", "").strip()
        index = os.environ.get("ACFV_GUI_INDEX_ROOT", "").strip()
        clips = os.environ.get("ACFV_GUI_CLIP_ROOT", "").strip()
        return cls(
            db_path=Path(db).expanduser() if db else None,
            index_root=Path(index).expanduser() if index else None,
            clip_root=Path(clips).expanduser() if clips else None,
            config_manager=config_manager,
        )

    def creators(self) -> list[CreatorVM]:
        recordings = self.library.list_recordings()
        sources = self.library.list_sources()
        rows: list[CreatorVM] = []
        for creator in self.library.list_creators():
            owned = [item for item in recordings if item.creator_id == creator.id]
            platforms = sorted({item.platform.title() for item in sources if item.creator_id == creator.id})
            profile = self.creator_adaptive.profile_summary(creator.id)
            rows.append(CreatorVM(
                id=creator.id,
                name=creator.display_name,
                platform=" / ".join(platforms) or "Local",
                recording_count=len(owned),
                processing_count=sum(str(item.processing_status.value) == "PROCESSING" for item in owned),
                avatar_url=creator.avatar_url or "",
                profile_status=str(profile.get("status", "NOT_BUILT")),
                profile_version=str(profile.get("profile_version", "")),
                visual_status=str(profile.get("visual_status", "NOT_BUILT")),
                adaptive_status="SHADOW",
                voice_exemplars=int(profile.get("voice_exemplars", 0)),
                trusted_speech_duration_ms=int(profile.get("trusted_speech_duration_ms", 0)),
                lexicon_entries=int(profile.get("lexicon_entries", 0)),
            ))
        return rows

    def recordings(self, creator_id: str | None) -> list[RecordingVM]:
        rows: list[RecordingVM] = []
        for item in self.library.list_recordings(creator_id):
            status = self._recording_status(item)
            date = item.started_at.astimezone().strftime("%Y-%m-%d") if item.started_at else item.created_at.astimezone().strftime("%Y-%m-%d")
            rows.append(RecordingVM(
                id=item.id,
                creator_id=item.creator_id,
                title=item.title,
                source_type=item.source_type,
                date=date,
                duration_ms=int(item.duration_ms or 0),
                language=self._recording_language(item),
                status=status,
                media_path=item.local_path or "",
                missing_media=bool(item.local_path and not media_exists(item.local_path)),
                error=item.error_message or "",
                media_revision=f"{item.file_size or 0}:{item.file_mtime_ns or 0}",
                job_id=item.last_job_id or "",
            ))
        return list(reversed(rows))

    def build_creator_profile(self, creator_id: str) -> dict[str, Any]:
        current = self.creator_adaptive.latest_profile(creator_id)
        version = str((current or {}).get("profile_version") or "creator_profile_v1")
        avatar = ExistingAvatarModelAdapter()
        visual_config = Path.cwd() / "config/creator_visual_identity.json"
        visual_ready = False
        if visual_config.is_file():
            payload = json.loads(visual_config.read_text(encoding="utf-8"))
            artifact = Path(str(payload.get("classifier_path", "")))
            visual_ready = (artifact if artifact.is_absolute() else Path.cwd() / artifact).is_file()
        if visual_ready and version != "creator_profile_v3":
            version = "creator_profile_v3"
        elif avatar.status == "READY" and version == "creator_profile_v1":
            version = "creator_profile_v2"
        visual_status = "READY" if visual_ready else ("CONFIGURED_NEEDS_BUILD" if avatar.status == "READY" else "REAL_MODEL_NOT_CONFIGURED")
        self.creator_adaptive.ensure_profile(creator_id, version, visual_status=visual_status)
        try:
            CreatorVoiceProfileService(repository=self.creator_adaptive).build(creator_id, profile_version=version)
        except VoiceProfileInsufficientData:
            pass
        return {**self.creator_adaptive.profile_summary(creator_id), "avatar_provider": avatar.audit(), "adaptive_status": "SHADOW"}

    def recording_thumbnail(self, recording: RecordingVM) -> tuple[str, str]:
        """Return a revision-aware cached thumbnail generated off the GUI thread."""
        if recording.missing_media or not recording.media_path:
            return recording.id, ""
        key = hashlib.sha256(f"{recording.id}:{recording.media_revision}".encode("utf-8")).hexdigest()[:24]
        target = storage_root() / "cache" / "gui-thumbnails" / f"{key}.jpg"
        if target.is_file():
            return recording.id, str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            import cv2

            capture = cv2.VideoCapture(recording.media_path)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if frame_count > 1:
                capture.set(cv2.CAP_PROP_POS_FRAMES, min(frame_count - 1, max(0, frame_count // 5)))
            ok, frame = capture.read()
            capture.release()
            if not ok or frame is None:
                return recording.id, ""
            height, width = frame.shape[:2]
            scale = min(1.0, 560 / max(1, width))
            if scale < 1:
                frame = cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
            if not cv2.imwrite(str(target), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82]):
                return recording.id, ""
            return recording.id, str(target)
        except Exception:
            return recording.id, ""

    def recording(self, recording_id: str) -> RecordingVM:
        item = self.library.get_recording(recording_id)
        if item is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        return next(row for row in self.recordings(item.creator_id) if row.id == recording_id)

    def moments(self, recording_id: str, *, limit: int = 200, offset: int = 0) -> list[MomentVM]:
        rows = self.library.repository.list_moments(recording_id=recording_id)
        recording = self.library.get_recording(recording_id)
        title = recording.title if recording else "Recording"
        return [self._moment_vm(item, title) for item in rows[offset:offset + limit]]

    def search(
        self,
        query: str,
        *,
        scope: str,
        creator_id: str | None,
        recording_id: str | None,
        limit: int = 20,
    ) -> list[MomentVM]:
        kind = SearchScope(scope)
        results = self.retrieval.search(
            query,
            top_k=limit,
            scope=kind,
            creator_id=creator_id if kind is SearchScope.CREATOR else None,
            recording_id=recording_id if kind in {SearchScope.RECORDING, SearchScope.LIVE_SESSION} else None,
        )
        return [MomentVM(
            id=item.moment_id,
            creator_id=item.creator_id,
            recording_id=item.recording_id,
            recording_title=item.recording_title,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            summary=item.summary or "Moment",
            excerpt=item.transcript_excerpt,
            relevance="最相关" if index < 3 else "相关",
            evidence=tuple(item.evidence),
        ) for index, item in enumerate(results)]

    def ask(
        self,
        query: str,
        *,
        scope: str,
        creator_id: str | None,
        recording_id: str | None,
    ) -> dict[str, Any]:
        kind = SearchScope(scope)
        answer = self.conversation.ask(
            query,
            scope=kind,
            creator_id=creator_id if kind is SearchScope.CREATOR else None,
            recording_id=recording_id if kind in {SearchScope.RECORDING, SearchScope.LIVE_SESSION} else None,
        )
        evidence = [MomentVM(
            id=item.moment_id, creator_id=item.creator_id, recording_id=item.recording_id,
            recording_title=item.recording_title, start_ms=item.start_ms, end_ms=item.end_ms,
            summary=item.summary or "Evidence", excerpt=item.transcript_excerpt,
            relevance="证据", evidence=tuple(item.evidence),
        ) for item in answer.evidence_cards]
        return {
            "answer": answer.answer,
            "grounded": answer.grounded,
            "confidence": answer.confidence,
            "runtime_mode": answer.runtime_mode.value,
            "evidence": evidence,
        }

    def create_clip(self, moment_id: str, query: str = "") -> ClipVM:
        clip = self.clips.create_proposal(moment_id, query=query)
        return self._clip_vm(clip)

    def clip_rows(self, creator_id: str | None = None) -> list[ClipVM]:
        return [self._clip_vm(item) for item in self.clips.list_clips(creator_id)]

    def import_local(self, path: str, creator_id: str, *, process: bool = True) -> RecordingVM:
        recording = self.library.add_video(path, creator_id=creator_id)
        if process:
            recording = self.library.process_recording(recording.id, config_manager=self.config)
        return self.recording(recording.id)

    def process_recording(self, recording_id: str) -> RecordingVM:
        self.library.retry_processing(recording_id, config_manager=self.config)
        return self.recording(recording_id)

    def relink_recording(self, recording_id: str, path: str) -> RecordingVM:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        recording = self.library.update_recording_status(recording_id, local_path=candidate)
        return self.recording(recording.id)

    def job_view(self, job_id: str) -> dict[str, Any]:
        return self.jobs.get_job_view(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return self.jobs.cancel_job(job_id)

    def download_vod(
        self,
        url: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        progress: Any | None = None,
    ) -> Any:
        discovered = self.vod.discover(url, start_ms=start_ms, end_ms=end_ms)
        return self.vod.download(discovered.id, config_manager=self.config, progress_callback=progress)

    def review_workflow(self, clip_id: str) -> GuiVariantWorkflowService:
        clip = self.library.repository.get_clip(clip_id)
        if clip is None:
            raise KeyError(f"Unknown clip: {clip_id}")
        output_root = self._clip_output_root(clip.id, clip.moment_id)
        plan_path = output_root / ".gui" / "event_plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._event_plan_payload(clip, output_root)
        plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return GuiVariantWorkflowService(
            plan_path,
            output_root,
            repository=self.library.repository,
        )

    def review_snapshot(self, clip_id: str) -> dict[str, Any]:
        workflow = self.review_workflow(clip_id)
        variants = []
        for row in workflow.variant_rows():
            variants.append(VariantVM(
                profile=str(row.get("profile") or ""),
                status=str(row.get("status") or "NOT_GENERATED"),
                duration_ms=int(row.get("duration_ms") or 0),
                start_ms=int(row.get("start_ms") or 0),
                end_ms=int(row.get("end_ms") or 0),
                output_path=str(row.get("latest_output_path") or row.get("base_output_path") or ""),
                revision=int(row.get("revision") or 0),
                warning_count=len(row.get("validation_warnings") or ()),
            ))
        selected = workflow.selected_profile
        ready = next((item for item in variants if item.profile == selected and item.status == "READY"), None)
        track = workflow.load_track(selected) if ready else None
        return {
            "workflow": workflow,
            "variants": variants,
            "selected": selected,
            "track": track,
            "warnings": self._language_warnings(workflow.output_root, selected),
            "decision": workflow.state.get("decision"),
            "similarity_warning": workflow.similarity_warning(),
        }

    def select_variant(self, workflow: GuiVariantWorkflowService, profile: str) -> dict[str, Any]:
        row = workflow.select_variant(profile)
        return {"row": row, "track": workflow.load_track(profile), "warnings": self._language_warnings(workflow.output_root, profile)}

    @staticmethod
    def save_cues(workflow: GuiVariantWorkflowService, profile: str, edits: Iterable[dict[str, str]]) -> list[str]:
        return workflow.save_cues(profile, edits)

    @staticmethod
    def rerender(
        workflow: GuiVariantWorkflowService,
        profile: str,
        *,
        start_ms: int,
        end_ms: int,
        progress: Any | None = None,
    ) -> dict[str, Any]:
        if progress:
            progress({"stage": "RENDERING", "message": "正在渲染新版本"})
        return workflow.rerender(profile, start_ms=start_ms, end_ms=end_ms)

    @staticmethod
    def generate_variant(
        workflow: GuiVariantWorkflowService,
        profile: str,
        *,
        progress: Any | None = None,
    ) -> Any:
        callback = None
        if progress:
            callback = lambda name, stage: progress({"profile": name, "stage": stage})
        return workflow.generate_selected(profile, progress=callback)

    @staticmethod
    def decide(workflow: GuiVariantWorkflowService, decision: str, reason: str = "") -> dict[str, Any]:
        return workflow.record_decision(decision, reason=reason)

    def _clip_output_root(self, clip_id: str, moment_id: str) -> Path:
        direct = self.clip_root / clip_id
        if direct.is_dir():
            return direct
        suffix = moment_id[:8].casefold()
        matches = [path for path in self.clip_root.iterdir() if path.is_dir() and path.name.casefold().endswith(suffix)]
        return sorted(matches)[0] if matches else direct

    def _event_plan_payload(self, clip: Any, output_root: Path) -> dict[str, Any]:
        moment = self.library.repository.get_moment(clip.moment_id)
        recording = self.library.get_recording(clip.recording_id)
        if moment is None or recording is None or not recording.local_path:
            raise ValueError("Clip is missing its Moment or Recording media")
        plan = self.clips._event_plan(moment, int(recording.duration_ms or 0))
        payload = asdict(plan)
        payload["clip_id"] = clip.id
        payload["recording_id"] = recording.id
        creator = self.library.repository.get_creator(clip.creator_id)
        payload["creator"] = creator.display_name if creator else ""
        payload["content_type"] = recording.content_type
        payload["words"] = self._recover_words(output_root, clip.final_start_ms)
        if payload["words"]:
            payload["source_language"] = payload["words"][0].get("language") or "en"
        return payload

    @staticmethod
    def _recover_words(output_root: Path, default_offset_ms: int) -> list[dict[str, Any]]:
        for profile in ("standard", "short", "long", "full_event"):
            track_path = output_root / profile / "bilingual_track.json"
            manifest_path = output_root / profile / "manifest.json"
            if not track_path.is_file():
                continue
            track = json.loads(track_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            offset = int(manifest.get("start_ms", default_offset_ms))
            language = str(track.get("source_language") or "en")
            words: list[dict[str, Any]] = []
            for cue_index, cue in enumerate(track.get("cues") or []):
                tokens = re.findall(r"\S+", str(cue.get("source_text") or ""))
                identifiers = list(cue.get("word_ids") or [])
                if not tokens:
                    continue
                start = offset + int(cue.get("start_ms") or 0)
                end = offset + int(cue.get("end_ms") or 0)
                span = max(len(tokens), end - start)
                for index, token in enumerate(tokens):
                    word_start = start + round(span * index / len(tokens))
                    word_end = start + round(span * (index + 1) / len(tokens))
                    words.append({
                        "word_id": identifiers[index] if index < len(identifiers) else f"gui-{cue_index:04d}-{index:03d}",
                        "text": token,
                        "start_ms": word_start,
                        "end_ms": max(word_start + 1, word_end),
                        "language": language,
                        "source": "RECOVERED_CANONICAL_TRACK",
                    })
            return words
        return []

    @staticmethod
    def _language_warnings(output_root: Path, profile: str) -> list[dict[str, Any]]:
        path = output_root / profile.casefold() / "final_language_quality.json"
        if not path.is_file():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        clusters = payload.get("clusters") or payload.get("issue_clusters") or payload.get("risk_clusters")
        if isinstance(clusters, list):
            return [dict(item) for item in clusters]
        findings = payload.get("issues") or payload.get("findings") or []
        grouped: dict[str, dict[str, Any]] = {}
        for item in findings:
            root = str(item.get("root_cause_key") or item.get("issue_id") or item.get("type") or "warning")
            row = grouped.setdefault(root, {"root_cause": root, "member_findings": [], "max_severity": "WARNING"})
            row["member_findings"].append(item)
            row["start_ms"] = min(int(row.get("start_ms", item.get("start_ms", 0))), int(item.get("start_ms", 0)))
        if grouped:
            return list(grouped.values())
        overall = str(payload.get("Overall") or payload.get("overall_language_quality_state") or "READY")
        if overall not in {"READY", "PASS"}:
            return [{
                "root_cause": f"Language Quality · {overall}",
                "max_severity": "WARNING" if overall == "READY_WITH_WARNINGS" else "HIGH",
                "start_ms": 0,
                "member_findings": [{
                    "ASR": payload.get("ASR"),
                    "Translation": payload.get("Translation"),
                    "Timeline": payload.get("Timeline"),
                }],
                "recommended_action": "Review subtitle quality before accepting.",
            }]
        return []

    def _moment_vm(self, item: Any, title: str) -> MomentVM:
        return MomentVM(
            id=item.id,
            creator_id=item.creator_id,
            recording_id=item.recording_id,
            recording_title=title,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            summary=item.summary or "Moment",
            excerpt=item.transcript_text or item.chat_text or item.visual_text or "",
        )

    def _clip_vm(self, item: Any) -> ClipVM:
        moment = self.library.repository.get_moment(item.moment_id)
        return ClipVM(
            id=item.id,
            creator_id=item.creator_id,
            recording_id=item.recording_id,
            moment_id=item.moment_id,
            title=(moment.summary if moment else "") or item.query or "Clip",
            start_ms=item.final_start_ms,
            end_ms=item.final_end_ms,
            render_status=item.render_status.value,
            review_status=item.review_status.value,
            output_path=item.output_path or "",
            error=item.error_message or "",
        )

    @staticmethod
    def _recording_status(item: Any) -> str:
        if item.error_message or item.processing_status.value == "FAILED" or item.recording_status.value == "FAILED":
            return "失败"
        if item.recording_status.value == "RECORDING":
            return "录制中"
        if item.processing_status.value == "PROCESSING" or item.index_status.value == "INDEXING":
            return "处理中"
        if item.processing_status.value == "READY" and item.index_status.value == "READY":
            return "可用"
        return "需要检查"

    @staticmethod
    def _recording_language(item: Any) -> str:
        try:
            payload = json.loads(item.analysis_profile_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        return str(payload.get("language") or payload.get("source_language") or "自动")

