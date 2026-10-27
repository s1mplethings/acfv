from __future__ import annotations

from pathlib import Path
import json
import re
import unicodedata
from typing import Any, Callable

from acfv.backend.service import render_review_clip
from acfv.library.models import Clip, ClipRenderStatus, utc_now
from acfv.library.repository import LibraryRepository
from acfv.runtime.storage import storage_root

from .duration import DurationProfile, DurationRequest, SemanticBoundaryUnit, VariantStatus
from .variants import ClipEventPlan, ClipVariantService


class ClipService:
    def __init__(
        self,
        repository: LibraryRepository,
        *,
        renderer: Callable[..., dict[str, Any]] = render_review_clip,
        output_root: Path | None = None,
        variant_service: ClipVariantService | None = None,
    ) -> None:
        self.repository = repository
        self.renderer = renderer
        self.output_root = Path(output_root or storage_root() / "clips")
        self.variant_service = variant_service or ClipVariantService(renderer=renderer)

    def create_proposal(
        self,
        moment_id: str,
        *,
        query: str = "",
        context_before_ms: int = 8_000,
        context_after_ms: int = 12_000,
        relevance_score: float | None = None,
        minimum_relevance_score: float = 0.0,
    ) -> Clip:
        moment = self.repository.get_moment(moment_id)
        if moment is None:
            raise KeyError(f"Unknown moment: {moment_id}")
        recording = self.repository.get_recording(moment.recording_id)
        if recording is None:
            raise KeyError(f"Unknown recording: {moment.recording_id}")
        if query.strip() and relevance_score is not None and relevance_score < minimum_relevance_score:
            raise ValueError("Insufficient retrieval evidence for a confident Clip proposal")
        if not self._has_semantic_value(moment):
            raise ValueError("Moment has insufficient semantic or event evidence for an automatic Clip")
        plan = self._event_plan(moment, recording.duration_ms or 0)
        boundary = self.variant_service.select_boundary(plan, DurationRequest(DurationProfile.STANDARD))
        # SOURCE_EDGE is a review warning, not permission to resurrect the
        # legacy fixed-context path.  The canonical service still owns these
        # natural boundaries (for example a recording that begins at the event).
        reviewable_short_event = "semantic_event_below_15s_viability_floor" in boundary.extension_reason
        if (boundary.status is not VariantStatus.READY
                and "SOURCE_EDGE" not in boundary.extension_reason
                and not reviewable_short_event):
            raise ValueError(
                f"STANDARD final variant unavailable: {boundary.status.value}: {boundary.extension_reason}"
            )
        proposed_start, proposed_end = boundary.start_ms, boundary.end_ms
        start_reason = end_reason = boundary.extension_reason
        if recording.duration_ms:
            proposed_end = min(recording.duration_ms, proposed_end)
        return self.repository.save(
            Clip(
                creator_id=moment.creator_id,
                recording_id=moment.recording_id,
                moment_id=moment.id,
                query=query.strip(),
                original_start_ms=moment.start_ms,
                original_end_ms=moment.end_ms,
                proposed_start_ms=proposed_start,
                proposed_end_ms=proposed_end,
                final_start_ms=proposed_start,
                final_end_ms=proposed_end,
                reason=json.dumps({
                    "start_reason": start_reason, "end_reason": end_reason,
                    "artifact_role": "REVIEW_PROPOSAL" if reviewable_short_event else "FINAL_VARIANT",
                    "duration_profile": "STANDARD",
                    "canonical_owner": "ClipVariantService",
                }, ensure_ascii=False),
            )
        )

    @staticmethod
    def _has_semantic_value(moment) -> bool:
        meaningful = "".join(char for char in moment.transcript_text if unicodedata.category(char)[0] in {"L", "N"})
        words = re.findall(r"[\w\u3400-\u9fff]+", moment.transcript_text.casefold())
        transcript_value = len(set(words)) >= 2 or len(meaningful) >= 8
        event_value = bool(moment.chat_text.strip() or moment.visual_text.strip() or moment.ocr_text.strip())
        return transcript_value or event_value

    def _semantic_boundaries(self, moment, *, context_before_ms: int, context_after_ms: int) -> tuple[int, int, str, str]:
        units = []
        for sibling in self.repository.list_moments(recording_id=moment.recording_id):
            try:
                evidence = json.loads(sibling.evidence_json)
            except json.JSONDecodeError:
                evidence = []
            for item in evidence:
                if item.get("type") != "transcript" or not str(item.get("text") or "").strip():
                    continue
                units.append({"start_ms": int(item["start_ms"]), "end_ms": int(item["end_ms"]), "text": str(item["text"]).strip()})
        units = sorted({(item["start_ms"], item["end_ms"], item["text"]): item for item in units}.values(), key=lambda item: (item["start_ms"], item["end_ms"]))
        if not units:
            return max(0, moment.start_ms - context_before_ms), moment.end_ms + context_after_ms, "fixed_context_fallback", "fixed_context_fallback"
        overlapping = [
            index
            for index, item in enumerate(units)
            if item["end_ms"] > moment.start_ms and item["start_ms"] < moment.end_ms
        ]
        if not overlapping:
            return max(0, moment.start_ms - context_before_ms), moment.end_ms + context_after_ms, "fixed_context_fallback", "fixed_context_fallback"
        first, last = overlapping[0], overlapping[-1]
        start_index = first
        lower = max(0, moment.start_ms - min(20_000, context_before_ms + 8_000))
        while start_index > 0 and units[start_index]["start_ms"] > lower:
            previous = units[start_index - 1]
            current = units[start_index]
            if current["start_ms"] - previous["end_ms"] >= 800 or re.search(r"[.!?。！？][\"']?$", previous["text"]):
                break
            start_index -= 1
        proposed_start = units[start_index]["start_ms"]
        start_reason = "previous_sentence_boundary" if start_index < first else "moment_transcript_boundary"
        end_index = last
        upper = min(proposed_start + 90_000, moment.end_ms + max(20_000, context_after_ms))
        while end_index + 1 < len(units):
            current = units[end_index]
            following = units[end_index + 1]
            sentence_complete = bool(re.search(r"[.!?。！？][\"']?$", current["text"]))
            pause_after = following["start_ms"] - current["end_ms"] >= 800
            if current["end_ms"] >= moment.end_ms and (sentence_complete or pause_after):
                break
            if following["end_ms"] > upper:
                break
            end_index += 1
        proposed_end = units[end_index]["end_ms"]
        end_reason = "next_sentence_or_pause" if end_index > last else "moment_transcript_boundary"
        return max(0, proposed_start), proposed_end, start_reason, end_reason

    def _event_plan(self, moment, source_duration_ms: int) -> ClipEventPlan:
        raw: list[tuple[int, int, str]] = []
        for sibling in self.repository.list_moments(recording_id=moment.recording_id):
            try:
                evidence = json.loads(sibling.evidence_json)
            except (json.JSONDecodeError, TypeError):
                evidence = []
            for item in evidence:
                if item.get("type") == "transcript" and str(item.get("text") or "").strip():
                    start, end = int(item["start_ms"]), int(item["end_ms"])
                    if end >= moment.start_ms - 180_000 and start <= moment.end_ms + 180_000:
                        raw.append((start, end, str(item["text"]).strip()))
        if not raw:
            raw = [(moment.start_ms, moment.end_ms, moment.transcript_text or moment.summary or "event")]
        ordered = sorted(set(raw))
        anchor = (moment.start_ms + moment.end_ms) // 2
        anchor_indexes = [index for index, (start, end, _) in enumerate(ordered) if start <= anchor <= end]
        focus = anchor_indexes[0] if anchor_indexes else min(range(len(ordered)), key=lambda i: abs(ordered[i][0] - anchor))
        if not anchor_indexes:
            # Incremental/live evidence may retain chunk-local timestamps while
            # the finalized Moment uses recording-relative bounds.  Keep the
            # event identity but place the payoff anchor inside the nearest
            # actual semantic unit so the canonical duration contract holds.
            anchor = (ordered[focus][0] + ordered[focus][1]) // 2
        left = right = focus
        while left > 0 and ordered[left][0] - ordered[left - 1][1] <= 8_000:
            left -= 1
        while right + 1 < len(ordered) and ordered[right + 1][0] - ordered[right][1] <= 8_000:
            right += 1
        units: list[SemanticBoundaryUnit] = []
        for start, end, text in ordered[left:right + 1]:
            roles: set[str] = set()
            if start < moment.end_ms:
                roles.add("setup")
            if end > moment.start_ms and start < moment.end_ms:
                roles.update(("event", "payoff"))
            if start >= moment.start_ms:
                roles.add("reaction")
            if start >= moment.end_ms:
                roles.add("aftermath")
            units.append(SemanticBoundaryUnit(start, end, text, tuple(sorted(roles))))
        recording = self.repository.get_recording(moment.recording_id)
        return ClipEventPlan(
            event_id=moment.id, clip_id=moment.id, source_path=str(recording.local_path if recording else ""),
            source_duration_ms=source_duration_ms or max(unit.end_ms for unit in units) + 20_000,
            payoff_anchor_ms=anchor, source_language="en", units=tuple(units), words=(),
            recording_id=moment.recording_id, raw_library_transcript=" ".join(unit.text for unit in units),
            event_summary=moment.summary or moment.transcript_text,
            required_evidence_span_ms=(moment.start_ms, moment.end_ms),
            required_evidence_text=moment.transcript_text,
        )

    def apply_duration_profile(self, clip_id: str, profile: DurationProfile, *,
                               target_seconds: float | None = None, min_seconds: float | None = None,
                               max_seconds: float | None = None) -> Clip:
        clip = self._require_clip(clip_id)
        moment = self.repository.get_moment(clip.moment_id)
        recording = self.repository.get_recording(clip.recording_id)
        if moment is None or recording is None:
            raise ValueError("Clip is missing its Moment or Recording")
        boundary = self.variant_service.select_boundary(
            self._event_plan(moment, recording.duration_ms or 0),
            DurationRequest(profile, target_seconds, min_seconds, max_seconds),
        )
        if boundary.status is not VariantStatus.READY:
            raise ValueError(f"{boundary.status.value}: {boundary.extension_reason}")
        return self.update_review(
            clip.id, start_ms=boundary.start_ms, end_ms=boundary.end_ms,
            duration_profile=profile.value, selected_final_variant=profile.value,
            target_duration_seconds=target_seconds, min_duration_seconds=min_seconds,
            max_duration_seconds=max_seconds, extension_reason=boundary.extension_reason,
        )

    def render(self, clip_id: str) -> Clip:
        clip = self._require_clip(clip_id)
        recording = self.repository.get_recording(clip.recording_id)
        if recording is None or not recording.local_path:
            raise ValueError("Clip Recording has no local media path")
        self._assert_candidate_source_context(clip, recording.duration_ms)
        clip.render_status = ClipRenderStatus.RENDERING
        clip.error_message = None
        clip.updated_at = utc_now()
        clip = self.repository.save(clip)
        try:
            metadata = json.loads(clip.reason or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        profile = str(metadata.get("duration_review", {}).get("selected_duration_profile") or
                      metadata.get("duration_profile") or "STANDARD")
        output = self.output_root / clip.id / f"FINAL_{profile}.mp4"
        try:
            result = self.renderer(
                video_path=recording.local_path,
                output_path=str(output),
                start_ms=clip.final_start_ms,
                end_ms=clip.final_end_ms,
                subtitle_text=clip.subtitle_text,
                subtitle_style=json.loads(clip.subtitle_style_json or "{}"),
            )
            clip.output_path = str(Path(result["output_path"]).resolve())
            clip.render_status = ClipRenderStatus.READY
        except Exception as exc:
            clip.render_status = ClipRenderStatus.FAILED
            clip.error_message = str(exc)
            clip.updated_at = utc_now()
            self.repository.save(clip)
            raise
        clip.updated_at = utc_now()
        return self.repository.save(clip)

    def update_review(
        self,
        clip_id: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        subtitle_text: str | None = None,
        subtitle_style: dict[str, Any] | None = None,
        duration_profile: str | None = None,
        target_duration_seconds: float | None = None,
        min_duration_seconds: float | None = None,
        max_duration_seconds: float | None = None,
        display_mode: str | None = None,
        subtitle_completeness: str | None = None,
        subtitle_position: str | None = None,
        selected_final_variant: str | None = None,
        extension_reason: str | None = None,
    ) -> Clip:
        clip = self._require_clip(clip_id)
        old_boundaries = (clip.final_start_ms, clip.final_end_ms)
        next_start = clip.final_start_ms if start_ms is None else max(0, start_ms)
        next_end = clip.final_end_ms if end_ms is None else end_ms
        recording = self.repository.get_recording(clip.recording_id)
        if recording and recording.duration_ms:
            next_end = min(next_end, recording.duration_ms)
        if next_end <= next_start:
            raise ValueError("Clip end must be after start")
        clip.final_start_ms = next_start
        clip.final_end_ms = next_end
        if subtitle_text is not None:
            clip.subtitle_text = subtitle_text
        if subtitle_style is not None:
            clip.subtitle_style_json = json.dumps(subtitle_style, ensure_ascii=False)
        try:
            metadata = json.loads(clip.reason or "{}")
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        review = dict(metadata.get("duration_review") or {})
        values = {
            "selected_duration_profile": duration_profile,
            "target_duration_seconds": target_duration_seconds,
            "min_duration_seconds": min_duration_seconds,
            "max_duration_seconds": max_duration_seconds,
            "display_mode": display_mode,
            "subtitle_completeness": subtitle_completeness,
            "subtitle_position": subtitle_position,
            "selected_final_variant": selected_final_variant,
            "extension_reason": extension_reason,
        }
        review.update({key: value for key, value in values.items() if value is not None})
        review.setdefault("original_boundaries", [clip.original_start_ms, clip.original_end_ms])
        review["generated_boundaries"] = [next_start, next_end]
        if old_boundaries != (next_start, next_end):
            review["subtitle_timeline_status"] = "INVALIDATED_BY_BOUNDARY_CHANGE"
            review["subtitle_timeline_revision"] = int(review.get("subtitle_timeline_revision", 0)) + 1
        metadata["duration_review"] = review
        clip.reason = json.dumps(metadata, ensure_ascii=False)
        clip.render_status = ClipRenderStatus.PROPOSED
        clip.updated_at = utc_now()
        return self.repository.save(clip)

    def get_clip(self, clip_id: str) -> Clip | None:
        return self.repository.get_clip(clip_id)

    def select_rendered_variant(
        self,
        clip_id: str,
        *,
        profile: str,
        output_path: str,
        start_ms: int,
        end_ms: int,
        display_mode: str,
        subtitle_completeness: str,
        subtitle_position: str,
        extension_reason: str = "",
    ) -> Clip:
        output = Path(output_path).resolve()
        if not output.is_file():
            raise ValueError(f"Output file missing: {output}")
        clip = self.update_review(
            clip_id, start_ms=start_ms, end_ms=end_ms, duration_profile=profile,
            selected_final_variant=profile, display_mode=display_mode,
            subtitle_completeness=subtitle_completeness, subtitle_position=subtitle_position,
            extension_reason=extension_reason,
        )
        clip.output_path = str(output)
        clip.render_status = ClipRenderStatus.READY
        clip.error_message = None
        clip.updated_at = utc_now()
        return self.repository.save(clip)

    def list_clips(self, creator_id: str | None = None) -> list[Clip]:
        return self.repository.list_clips(creator_id)

    def _require_clip(self, clip_id: str) -> Clip:
        clip = self.repository.get_clip(clip_id)
        if clip is None:
            raise KeyError(f"Unknown clip: {clip_id}")
        return clip

    @staticmethod
    def _assert_candidate_source_context(clip: Clip, duration_ms: int | None) -> None:
        try:
            reason = json.loads(clip.reason or "{}")
        except (json.JSONDecodeError, TypeError):
            reason = {}
        if not reason.get("candidate_id"):
            return
        near_start = clip.final_start_ms < 10_000
        near_end = bool(duration_ms and duration_ms - clip.final_end_ms < 20_000)
        if (near_start or near_end) and not reason.get("source_edge_override"):
            raise ValueError("SOURCE_CONTEXT_INCOMPLETE: candidate is too close to the source edge")
