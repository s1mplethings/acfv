from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from acfv.library.models import utc_now
from acfv.library.repository import LibraryRepository
from acfv.library.artifacts import resolve_artifact_root

from .builder import ProvisionalMomentBuilder
from .models import Moment, MomentStatus


class MomentFinalizer:
    def __init__(self, repository: LibraryRepository, *, builder: ProvisionalMomentBuilder | None = None) -> None:
        self.repository = repository
        self.builder = builder or ProvisionalMomentBuilder()

    def finalize(
        self,
        recording_id: str,
        transcript_payload: dict[str, Any],
        chat_payload: dict[str, Any] | None = None,
        *,
        transcript_artifact: str | None = None,
        chat_artifact: str | None = None,
        enrichment: list[dict[str, Any]] | None = None,
        replace_existing: bool = True,
    ) -> list[Moment]:
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        drafts = self.builder.build(
            transcript_payload,
            chat_payload,
            transcript_artifact=transcript_artifact,
            chat_artifact=chat_artifact,
        )
        final_ids: list[str] = []
        results: list[Moment] = []
        finalized_at = utc_now()
        for draft in drafts:
            start_ms = draft.start_ms
            end_ms = min(draft.end_ms, recording.duration_ms) if recording.duration_ms else draft.end_ms
            if end_ms <= start_ms:
                continue
            evidence_json = self._bounded_evidence(draft.evidence_json, end_ms)
            stable_key = f"{recording.id}:final:{start_ms}:{end_ms}"
            moment = self.repository.get_moment_by_stable_key(stable_key)
            if moment is None:
                moment = Moment(
                    stable_key=stable_key,
                    creator_id=recording.creator_id,
                    recording_id=recording.id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            before = (
                moment.transcript_text,
                moment.chat_text,
                moment.evidence_json,
                moment.visual_text,
                moment.ocr_text,
            )
            moment.status = MomentStatus.FINALIZING
            moment.transcript_text = draft.transcript_text
            moment.chat_text = draft.chat_text
            moment.summary = self._extractive_summary(draft.transcript_text)
            moment.evidence_json = evidence_json
            self._apply_enrichment(moment, enrichment or [])
            after = (
                moment.transcript_text,
                moment.chat_text,
                moment.evidence_json,
                moment.visual_text,
                moment.ocr_text,
            )
            if moment.id and before != ("", "", "[]", "", "") and before != after:
                moment.revision += 1
            moment.status = MomentStatus.FINAL
            moment.finalized_at = finalized_at
            moment.updated_at = finalized_at
            saved = self.repository.save(moment)
            final_ids.append(saved.id)
            results.append(saved)
        if replace_existing:
            self.repository.delete_recording_moments_except(recording_id, final_ids)
        return results

    def finalize_artifacts(
        self,
        recording_id: str,
        artifact_root: Path | str | None = None,
        *,
        replace_existing: bool = True,
    ) -> list[Moment]:
        recording = self.repository.get_recording(recording_id)
        if recording is None:
            raise KeyError(f"Unknown recording: {recording_id}")
        root = Path(artifact_root) if artifact_root is not None else resolve_artifact_root(recording)
        root = Path(root or "")
        if not root.is_dir():
            raise ValueError("Recording has no readable artifact root")
        transcript_path = self._first_existing(root, "work/transcript_merged.json", "work/transcription.json")
        if transcript_path is None:
            raise ValueError("Recording artifacts contain no transcript")
        chat_path = self._first_existing(root, "work/chat.json", "work/chat_with_emotes.json")
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        chat = json.loads(chat_path.read_text(encoding="utf-8")) if chat_path else None
        return self.finalize(
            recording_id,
            transcript,
            chat,
            transcript_artifact=str(transcript_path),
            chat_artifact=str(chat_path) if chat_path else None,
            replace_existing=replace_existing,
        )

    @staticmethod
    def _first_existing(root: Path, *relative_paths: str) -> Path | None:
        for relative in relative_paths:
            candidate = root / relative
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _bounded_evidence(payload: str, end_ms: int) -> str:
        evidence = json.loads(payload)
        bounded = []
        for item in evidence:
            value = dict(item)
            value["end_ms"] = min(int(value.get("end_ms", end_ms)), end_ms)
            value["start_ms"] = min(int(value.get("start_ms", value["end_ms"])), value["end_ms"])
            bounded.append(value)
        return json.dumps(bounded, ensure_ascii=False)

    @staticmethod
    def _extractive_summary(text: str, *, max_chars: int = 240) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", compact) if item.strip()]
        summary = " ".join(sentences[:2]) if sentences else compact
        if len(summary) > max_chars:
            clipped = summary[:max_chars].rsplit(" ", 1)[0].strip() or summary[:max_chars].strip()
            summary = clipped.rstrip(".,;: ") + "…"
        return summary

    @staticmethod
    def _apply_enrichment(moment: Moment, enrichment: list[dict[str, Any]]) -> None:
        matching = [item for item in enrichment if int(item.get("end_ms", 0)) >= moment.start_ms and int(item.get("start_ms", 0)) <= moment.end_ms]
        moment.visual_text = " ".join(str(item.get("visual_text") or "").strip() for item in matching).strip()
        moment.ocr_text = " ".join(str(item.get("ocr_text") or "").strip() for item in matching).strip()
        speakers = [item.get("speaker_data") for item in matching if item.get("speaker_data")]
        emotions = [item.get("emotion_data") for item in matching if item.get("emotion_data")]
        moment.speaker_data_json = json.dumps(speakers, ensure_ascii=False)
        moment.emotion_data_json = json.dumps(emotions, ensure_ascii=False)
