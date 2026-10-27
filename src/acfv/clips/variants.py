from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable, Iterable

from acfv.backend.service import render_review_clip
from acfv.processing.ffmpeg_runner import run_ffmpeg

from .duration import DurationProfile, DurationProfileService, DurationRequest, DurationVariant, SemanticBoundaryUnit, VariantStatus
from .refinement import FinalClipTranscriptService, FinalTranscriptArtifact, FinalTranscriptRequest
from .subtitles import (
    BilingualDisplayMode, BilingualSubtitleService, BilingualSubtitleTrack, ClipLanguageQualityState,
    SubtitleCompleteness, SubtitlePosition, SubtitleWord, TranslationProvider,
    language_release_state, language_risk_issue, words_from_payload,
)


@dataclass(frozen=True)
class ClipEventPlan:
    event_id: str
    clip_id: str
    source_path: str
    source_duration_ms: int
    payoff_anchor_ms: int
    source_language: str
    units: tuple[SemanticBoundaryUnit, ...]
    words: tuple[SubtitleWord, ...]
    recording_id: str = ""
    glossary: dict[str, str] | None = None
    raw_library_transcript: str = ""
    event_summary: str = ""
    game_title: str = ""
    ocr_context: str = ""
    creator: str = ""
    content_type: str = ""
    tone: str = ""
    speaker_relations: str = ""
    current_topic: str = ""
    previous_callback: str = ""
    required_evidence_span_ms: tuple[int, int] | None = None
    required_evidence_text: str = ""


@dataclass(frozen=True)
class RenderedVariant:
    boundary: DurationVariant
    output_dir: str
    clean_path: str
    bilingual_path: str
    ass_path: str
    srt_path: str
    manifest_path: str
    timeline_report_path: str
    preview_paths: tuple[str, ...]


class ClipVariantService:
    """Coordinate profile and subtitle services around the canonical renderer."""

    def __init__(self, *, renderer: Callable[..., dict[str, Any]] = render_review_clip,
                 duration_service: DurationProfileService | None = None,
                 subtitle_service: BilingualSubtitleService | None = None,
                 transcript_service: FinalClipTranscriptService | None = None) -> None:
        self.renderer = renderer
        self.duration_service = duration_service or DurationProfileService()
        self.subtitle_service = subtitle_service or BilingualSubtitleService()
        self.transcript_service = transcript_service

    def select_boundary(self, plan: ClipEventPlan, request: DurationRequest) -> DurationVariant:
        """Canonical semantic boundary selection used by every final-clip caller."""
        return self.duration_service.generate(
            event_id=plan.event_id, units=plan.units, payoff_anchor_ms=plan.payoff_anchor_ms,
            source_duration_ms=plan.source_duration_ms,
            request=replace(
                request,
                required_evidence_span_ms=(request.required_evidence_span_ms or plan.required_evidence_span_ms),
            ),
        )

    def generate_one(self, plan: ClipEventPlan, request: DurationRequest, *, output_root: Path,
                     provider: TranslationProvider,
                     display_mode: BilingualDisplayMode = BilingualDisplayMode.ZH_EN,
                     completeness: SubtitleCompleteness = SubtitleCompleteness.COMPLETE,
                     position: SubtitlePosition = SubtitlePosition.AUTO_SAFE_AREA,
                     glossary: dict[str, str] | None = None,
                     progress: Callable[[str], None] | None = None) -> RenderedVariant | DurationVariant:
        boundary = self.select_boundary(plan, request)
        if boundary.status is not VariantStatus.READY:
            return boundary
        plan, transcript = self._prepare_transcript(
            plan, Path(output_root), start_ms=boundary.start_ms, end_ms=boundary.end_ms,
        )
        if not self._final_asr_supports_required_evidence(plan):
            return replace(
                boundary, status=VariantStatus.NOT_AVAILABLE, start_ms=0, end_ms=0,
                extension_reason="final_asr_missing_required_evidence",
            )
        return self._generate_prepared(
            plan, request, output_root=output_root, provider=provider, display_mode=display_mode,
            completeness=completeness, position=position, glossary=glossary,
            progress=progress, transcript=transcript,
        )

    def _generate_prepared(self, plan: ClipEventPlan, request: DurationRequest, *, output_root: Path,
                           provider: TranslationProvider, display_mode: BilingualDisplayMode,
                           completeness: SubtitleCompleteness, position: SubtitlePosition,
                           glossary: dict[str, str] | None, progress: Callable[[str], None] | None,
                           transcript: FinalTranscriptArtifact | None,
                           event_track: BilingualSubtitleTrack | None = None,
                           event_track_start_ms: int | None = None) -> RenderedVariant | DurationVariant:
        notify = progress or (lambda _stage: None)
        notify("BUILDING_BOUNDARY")
        boundary = self.select_boundary(plan, request)
        if transcript is not None and boundary.status is VariantStatus.READY:
            boundary = self._align_boundary_to_words(boundary, plan.words, plan.source_duration_ms)
        if boundary.status is not VariantStatus.READY:
            return boundary
        target = Path(output_root) / boundary.profile.value.casefold()
        target.mkdir(parents=True, exist_ok=True)
        notify("BUILDING_SUBTITLE")
        notify("TRANSLATING")
        translation_started = time.perf_counter()
        event_context = {
            "creator": plan.creator or plan.recording_id,
            "content_type": plan.content_type,
            "game": plan.game_title,
            "event": {
                "setup": plan.event_summary,
                "payoff": plan.event_summary,
                "reaction": "",
            },
            "tone": plan.tone,
            "speaker_relations": plan.speaker_relations,
            "current_topic": plan.current_topic or plan.event_summary,
            "previous_callback": plan.previous_callback,
            "glossary": glossary or plan.glossary or {},
            "ocr": plan.ocr_context,
        }
        track = None
        if event_track is not None and event_track_start_ms is not None:
            track = self._slice_event_track(
                event_track, event_start_ms=event_track_start_ms,
                clip_start_ms=boundary.start_ms, clip_end_ms=boundary.end_ms,
                clip_id=f"{plan.clip_id}:{boundary.profile.value}",
            )
        if track is None:
            track = self.subtitle_service.build_track(
                clip_id=f"{plan.clip_id}:{boundary.profile.value}", words=plan.words,
                clip_start_ms=boundary.start_ms, clip_end_ms=boundary.end_ms,
                source_language=plan.source_language, provider=provider, display_mode=display_mode,
                completeness=completeness, cache_path=Path(output_root) / "translation_cache.json",
                glossary=glossary or plan.glossary,
                timing_provider=transcript.timing_backend if transcript else "library-word-timestamps",
                translation_context={**event_context, "event_id": plan.event_id, "cache_scope": "EVENT"},
            )
        translation_elapsed = time.perf_counter() - translation_started
        speech_ms = sum(
            max(0, min(word.end_ms, boundary.end_ms) - max(word.start_ms, boundary.start_ms))
            for word in plan.words if word.end_ms > boundary.start_ms and word.start_ms < boundary.end_ms
        )
        artifacts = self.subtitle_service.write_artifacts(
            track, target, position=position, clip_duration_ms=boundary.duration_ms,
            recognized_speech_duration_ms=speech_ms, captioned_speech_duration_ms=speech_ms,
        )
        timeline_report = json.loads(Path(artifacts["report"]).read_text(encoding="utf-8"))
        asr_state = "READY"
        if transcript and transcript.quality:
            asr_state = {
                "READY": "READY", "READY_WITH_WARNINGS": "READY_WITH_WARNINGS",
                "NEEDS_REVIEW": "NEEDS_REVIEW",
            }.get(transcript.quality.final_quality_state, "READY_WITH_WARNINGS")
        timeline_errors = int(timeline_report.get("overlap_count", 0)) + int(
            timeline_report.get("out_of_range_cues", 0)
        )
        timeline_state = "READY" if timeline_report.get("timeline_validity") and timeline_errors == 0 else "NEEDS_REVIEW"
        untranslated = int(timeline_report.get("untranslated_cues", 0))
        critical_guards = int(timeline_report.get("critical_semantic_guard_failures", 0))
        translation_state = track.translation_release_state
        combined_issues = list(transcript.quality.issues if transcript and transcript.quality else ())
        combined_issues.extend(
            failure for cue in track.cues for failure in cue.semantic_guard_failures
        )
        if untranslated:
            combined_issues.append(language_risk_issue(
                issue_id="translation:untranslated", issue_type="UNTRANSLATED_CUE",
                severity="CRITICAL", semantic_importance="CRITICAL",
                hard_blocker=True, evidence={"count": untranslated},
            ))
        overall, _, _ = language_release_state(
            combined_issues, timeline_valid=timeline_state == "READY",
            untranslated_critical=untranslated > 0,
        )
        if overall == "READY" and (
            asr_state == "READY_WITH_WARNINGS" or translation_state == "READY_WITH_WARNINGS"
        ):
            overall = "READY_WITH_WARNINGS"
        language_quality = ClipLanguageQualityState(
            ASR=asr_state, Translation=translation_state, Timeline=timeline_state,
            Overall=overall, untranslated=untranslated, timeline_errors=timeline_errors,
            critical_semantic_guard_failures=critical_guards,
        )
        language_quality_path = target / "final_language_quality.json"
        language_payload = asdict(language_quality)
        language_payload.pop("publishable", None)
        language_payload.update({
            "LANGUAGE_QUALITY_READY": language_quality.language_quality_ready,
            "PUBLISHABLE": False, "human_review": "PENDING",
            "translation_provider": track.translation_provider,
            "fallback_cues": track.fallback_cue_count,
        })
        language_quality_path.write_text(
            json.dumps(language_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        clean = target / "clip_clean.mp4"
        bilingual = target / "clip_bilingual.mp4"
        common = dict(video_path=plan.source_path, start_ms=boundary.start_ms, end_ms=boundary.end_ms)
        notify("RENDERING_CLEAN")
        clean_started = time.perf_counter()
        self.renderer(output_path=str(clean), **common)
        clean_elapsed = time.perf_counter() - clean_started
        notify("RENDERING_BILINGUAL")
        bilingual_started = time.perf_counter()
        self.renderer(output_path=str(bilingual), subtitle_path=str(artifacts["ass"]), **common)
        bilingual_elapsed = time.perf_counter() - bilingual_started
        notify("VALIDATING")
        previews = self._preview_frames(bilingual, boundary.duration_ms, target)
        clean_hash, bilingual_hash = _sha256(clean), _sha256(bilingual)
        manifest = target / "manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": "1.0", "event_id": plan.event_id, "clip_id": plan.clip_id,
            "profile": boundary.profile.value, "status": boundary.status.value,
            "start_ms": boundary.start_ms, "end_ms": boundary.end_ms, "duration_ms": boundary.duration_ms,
            "payoff_anchor_ms": boundary.payoff_anchor_ms, "extension_reason": boundary.extension_reason,
            "subtitle_mode": display_mode.value, "subtitle_completeness": completeness.value,
            "translation_provider": track.translation_provider, "clean_path": str(clean.resolve()),
            "translation_mode": track.translation_mode.value,
            "translation_context_size": track.translation_context_size,
            "translation_context": event_context,
            "translation_cache_scope": "EVENT",
            "translation_event_track_reused": event_track is not None,
            "translation_release_state": track.translation_release_state,
            "language_quality_state": language_payload,
            "language_quality_path": str(language_quality_path.resolve()),
            "final_asr_model": transcript.final_asr_model if transcript else "library-asr",
            "alignment_backend": track.timing_provider,
            "raw_asr": transcript.raw_final_asr if transcript else plan.raw_library_transcript,
            "corrected_asr": transcript.corrected_final_transcript if transcript else " ".join(word.text for word in plan.words),
            "source_correction_reason": transcript.correction.reason if transcript else "library_transcript",
            "source_correction_confidence": transcript.correction.confidence if transcript else None,
            "final_transcript_path": transcript.path if transcript else None,
            "performance": {
                "final_asr_seconds": transcript.asr_wall_time_seconds if transcript else 0.0,
                "final_asr_rtf": transcript.rtf if transcript else 0.0,
                "alignment_seconds": transcript.alignment_wall_time_seconds if transcript else 0.0,
                "source_correction_seconds": transcript.correction_wall_time_seconds if transcript else 0.0,
                "translation_seconds": translation_elapsed,
                "render_clean_seconds": clean_elapsed,
                "render_bilingual_seconds": bilingual_elapsed,
                "vram_mb": None,
            },
            "bilingual_path": str(bilingual.resolve()),
            "sha256": {"clean": clean_hash, "bilingual": bilingual_hash},
            "hashes_differ": clean_hash != bilingual_hash,
            "preview_paths": [str(path.resolve()) for path in previews],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return RenderedVariant(boundary, str(target), str(clean), str(bilingual), str(artifacts["ass"]),
                               str(artifacts["srt"]), str(manifest), str(artifacts["report"]),
                               tuple(str(path) for path in previews))

    @staticmethod
    def _final_asr_supports_required_evidence(plan: ClipEventPlan) -> bool:
        """Reject a temporal evidence hit when final ASR disproves its semantics."""
        if not plan.required_evidence_text or not plan.words:
            return True

        def tokens(value: str) -> set[str]:
            ignored = {
                "a", "an", "and", "are", "be", "but", "do", "does", "for", "from",
                "have", "i", "in", "is", "it", "just", "like", "maybe", "of", "on",
                "or", "s", "so", "that", "the", "there", "this", "to", "t", "was",
                "were", "what", "when", "with", "would", "yeah", "you",
            }
            result = set()
            for token in re.findall(r"[a-z0-9]+", value.casefold()):
                if len(token) > 4 and token.endswith("ies"):
                    token = token[:-3] + "y"
                elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
                    token = token[:-1]
                if token not in ignored:
                    result.add(token)
            return result

        final_tokens = tokens(" ".join(word.text for word in plan.words))
        query_tokens = tokens(plan.required_evidence_text)
        query_hits = len(query_tokens & final_tokens)
        if query_hits >= min(2, len(query_tokens)):
            return True
        library_tokens = tokens(plan.raw_library_transcript)
        overlap = len(library_tokens & final_tokens) / max(1, min(len(library_tokens), len(final_tokens)))
        return query_hits >= 1 and overlap >= 0.55

    @staticmethod
    def _align_boundary_to_words(boundary: DurationVariant, words: tuple[SubtitleWord, ...],
                                 source_duration_ms: int) -> DurationVariant:
        start, end = boundary.start_ms, boundary.end_ms
        for word in words:
            if word.start_ms < start < word.end_ms:
                start = word.start_ms
            if word.start_ms < end < word.end_ms:
                end = word.end_ms
        if (start, end) == (boundary.start_ms, boundary.end_ms):
            return boundary
        return replace(boundary, start_ms=max(0, start), end_ms=min(source_duration_ms, end),
                       extension_reason=boundary.extension_reason + "+aligned_word_completion")

    def rerender_bilingual(self, plan: ClipEventPlan, *, start_ms: int, end_ms: int,
                           track: BilingualSubtitleTrack, output_dir: Path,
                           position: SubtitlePosition) -> dict[str, Any]:
        """Render one edited subtitle revision through the canonical renderer."""
        duration_ms = end_ms - start_ms
        if duration_ms <= 0:
            raise ValueError("Variant end must be after start")
        artifacts = self.subtitle_service.write_artifacts(
            track, output_dir, position=position, clip_duration_ms=duration_ms,
        )
        output = output_dir / "clip_bilingual.mp4"
        result = self.renderer(
            video_path=plan.source_path,
            output_path=str(output),
            start_ms=start_ms,
            end_ms=end_ms,
            subtitle_path=str(artifacts["ass"]),
        )
        return {"output_path": str(Path(result["output_path"]).resolve()), **artifacts}

    def generate_all(self, plan: ClipEventPlan, *, output_root: Path, provider: TranslationProvider,
                     display_mode: BilingualDisplayMode = BilingualDisplayMode.ZH_EN,
                     completeness: SubtitleCompleteness = SubtitleCompleteness.COMPLETE,
                     position: SubtitlePosition = SubtitlePosition.AUTO_SAFE_AREA,
                     glossary: dict[str, str] | None = None) -> list[RenderedVariant | DurationVariant]:
        boundaries = self.duration_service.generate_all(
            event_id=plan.event_id, units=plan.units, payoff_anchor_ms=plan.payoff_anchor_ms,
            source_duration_ms=plan.source_duration_ms,
            required_evidence_span_ms=plan.required_evidence_span_ms,
        )
        ready = [item for item in boundaries if item.status is VariantStatus.READY]
        if not ready:
            self.write_summary(boundaries, Path(output_root))
            return list(boundaries)
        plan, transcript = self._prepare_transcript(
            plan, Path(output_root), start_ms=min(item.start_ms for item in ready),
            end_ms=max(item.end_ms for item in ready),
        )
        if not self._final_asr_supports_required_evidence(plan):
            boundaries = [
                replace(
                    item, status=VariantStatus.NOT_AVAILABLE, start_ms=0, end_ms=0,
                    extension_reason="final_asr_missing_required_evidence",
                ) if item.status is VariantStatus.READY else item
                for item in boundaries
            ]
            self.write_summary(boundaries, Path(output_root))
            return list(boundaries)
        # Final ASR owns word timing truth. Align the shared Event track and
        # every downstream profile before translating once and slicing it.
        boundaries = [
            self._align_boundary_to_words(item, plan.words, plan.source_duration_ms)
            if item.status is VariantStatus.READY else item
            for item in boundaries
        ]
        ready = [item for item in boundaries if item.status is VariantStatus.READY]
        event_track = None
        event_track_start = min(item.start_ms for item in ready)
        event_track_end = max(item.end_ms for item in ready)
        if plan.words:
            context = {
                "event_id": plan.event_id, "cache_scope": "EVENT",
                "creator": plan.creator or plan.recording_id, "content_type": plan.content_type,
                "game": plan.game_title,
                "event": {"setup": plan.event_summary, "core": plan.current_topic or plan.event_summary,
                          "payoff": plan.event_summary},
                "tone": plan.tone, "speaker_relations": plan.speaker_relations,
                "current_topic": plan.current_topic or plan.event_summary,
                "previous_callback": plan.previous_callback,
                "glossary": glossary or plan.glossary or {}, "ocr": plan.ocr_context,
            }
            event_track = self.subtitle_service.build_track(
                clip_id=plan.event_id, words=plan.words,
                clip_start_ms=event_track_start, clip_end_ms=event_track_end,
                source_language=plan.source_language, provider=provider, display_mode=display_mode,
                completeness=completeness, cache_path=Path(output_root) / "translation_cache.json",
                glossary=glossary or plan.glossary,
                timing_provider=transcript.timing_backend if transcript else "library-word-timestamps",
                translation_context=context,
            )
        results: list[RenderedVariant | DurationVariant] = []
        for boundary in boundaries:
            if boundary.status is not VariantStatus.READY:
                results.append(boundary)
            else:
                results.append(self._generate_prepared(
                    plan, DurationRequest(boundary.profile), output_root=output_root, provider=provider,
                    display_mode=display_mode, completeness=completeness, position=position, glossary=glossary,
                    progress=None, transcript=transcript,
                    event_track=event_track, event_track_start_ms=event_track_start,
                ))
        self.write_summary(results, Path(output_root))
        return results

    @staticmethod
    def _slice_event_track(track: BilingualSubtitleTrack, *, event_start_ms: int,
                           clip_start_ms: int, clip_end_ms: int,
                           clip_id: str) -> BilingualSubtitleTrack | None:
        cues = []
        for cue in track.cues:
            absolute_start = event_start_ms + cue.start_ms
            absolute_end = event_start_ms + cue.end_ms
            if absolute_start < clip_start_ms or absolute_end > clip_end_ms:
                continue
            cues.append(replace(
                cue, start_ms=absolute_start - clip_start_ms,
                end_ms=absolute_end - clip_start_ms,
            ))
        if not cues:
            return None
        return replace(track, clip_id=clip_id, cues=cues)

    def _prepare_transcript(self, plan: ClipEventPlan, output_root: Path, *,
                            start_ms: int, end_ms: int) -> tuple[ClipEventPlan, FinalTranscriptArtifact | None]:
        if self.transcript_service is None:
            return plan, None
        artifact = self.transcript_service.refine(FinalTranscriptRequest(
            recording_id=plan.recording_id, event_id=plan.event_id, source_path=plan.source_path,
            source_duration_ms=plan.source_duration_ms, event_start_ms=start_ms, event_end_ms=end_ms,
            source_language=plan.source_language, raw_library_transcript=plan.raw_library_transcript,
            event_summary=plan.event_summary, game_title=plan.game_title, ocr_context=plan.ocr_context,
            payoff_anchor_ms=plan.payoff_anchor_ms, glossary=plan.glossary or {},
        ), output_root=output_root)
        return replace(plan, words=artifact.aligned_words), artifact

    def write_summary(self, results: Iterable[RenderedVariant | DurationVariant], output_root: Path) -> None:
        material = list(results)
        self._write_comparison(material, output_root)
        self._write_review_and_aliases(material, output_root)

    @staticmethod
    def _preview_frames(video: Path, duration_ms: int, target: Path) -> tuple[Path, Path, Path]:
        paths: list[Path] = []
        for label, fraction in (("start", .08), ("middle", .5), ("end", .9)):
            path = target / f"subtitle_preview_{label}.jpg"
            run_ffmpeg(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss",
                        str(max(.1, duration_ms * fraction / 1000)), "-i", str(video),
                        "-frames:v", "1", "-q:v", "2", str(path)], timeout=120)
            paths.append(path)
        return paths[0], paths[1], paths[2]

    @staticmethod
    def _write_comparison(results: Iterable[RenderedVariant | DurationVariant], output_root: Path) -> None:
        rows: list[dict[str, Any]] = []
        for result in results:
            boundary = result.boundary if isinstance(result, RenderedVariant) else result
            rows.append({"profile": boundary.profile.value, "status": boundary.status.value,
                         "start_ms": boundary.start_ms, "end_ms": boundary.end_ms,
                         "duration_ms": boundary.duration_ms, "payoff_anchor_ms": boundary.payoff_anchor_ms,
                         "reason": boundary.extension_reason,
                         "bilingual_path": result.bilingual_path if isinstance(result, RenderedVariant) else None})
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "variant_comparison.json").write_text(
            json.dumps({"schema_version": "1.0", "variants": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_review_and_aliases(results: Iterable[RenderedVariant | DurationVariant], output_root: Path) -> None:
        lines = ["# Variant Review", ""]
        human = ["# Final Bilingual Duration Review", ""]
        for result in results:
            boundary = result.boundary if isinstance(result, RenderedVariant) else result
            lines.extend([
                f"## {boundary.profile.value}", "",
                f"- status: {boundary.status.value}",
                f"- duration: {boundary.duration_ms / 1000:.3f}s",
                f"- start/end: {boundary.start_ms} / {boundary.end_ms}",
                "- hook: shared event hook retained",
                "- setup: retained",
                "- payoff: shared payoff anchor retained",
                "- reaction: retained when profile permits",
                f"- omitted aftermath: {'profile-dependent' if boundary.profile is not DurationProfile.FULL_EVENT else 'none'}",
                f"- usefulness: {boundary.extension_reason}", "",
            ])
            if isinstance(result, RenderedVariant):
                alias = output_root / f"FINAL_{boundary.profile.value}_BILINGUAL.mp4"
                shutil.copy2(result.bilingual_path, alias)
                # Compatibility alias for existing Review consumers.
                shutil.copy2(result.bilingual_path, output_root / f"final_clip_{boundary.profile.value.casefold()}_bilingual.mp4")
                report = json.loads(Path(result.timeline_report_path).read_text(encoding="utf-8"))
                lines.extend([
                    f"- subtitle cues: {report['cue_count']}",
                    f"- average cue duration: {report['average_duration_ms'] / 1000:.3f}s",
                    f"- max cue duration: {report['max_duration_ms'] / 1000:.3f}s", "",
                ])
                human.extend([
                    f"## {boundary.profile.value}", "",
                    f"- file: {result.bilingual_path}",
                    f"- duration: {boundary.duration_ms / 1000:.3f}s",
                    f"- start/end: {boundary.start_ms} / {boundary.end_ms}",
                    f"- Chinese/English/bilingual screenshots: {', '.join(result.preview_paths)}",
                    f"- cue count: {report['cue_count']}",
                    f"- average/max cue duration: {report['average_duration_ms'] / 1000:.3f}s / {report['max_duration_ms'] / 1000:.3f}s",
                    f"- zh/en CPS max: {report['zh_cps']['maximum']} / {report['en_cps']['maximum']}",
                    f"- overlap/untranslated: {report['overlap_count']} / {report['untranslated_cues']}", "",
                ])
        lines.extend(["## Best version", "", "- [ ] SHORT", "- [ ] STANDARD", "- [ ] LONG", "- [ ] FULL_EVENT", ""])
        (output_root / "variant_review.md").write_text("\n".join(lines), encoding="utf-8")
        human.extend([
            "## Human Scores", "",
            "TIMELINE_SYNC: [ ] GOOD  [ ] ACCEPTABLE  [ ] BAD", "",
            "SEGMENTATION: [ ] GOOD  [ ] ACCEPTABLE  [ ] BAD", "",
            "CHINESE_TRANSLATION: [ ] GOOD  [ ] ACCEPTABLE  [ ] BAD", "",
            "ENGLISH_TEXT: [ ] GOOD  [ ] ACCEPTABLE  [ ] BAD", "",
            "VISUAL_READABILITY: [ ] GOOD  [ ] ACCEPTABLE  [ ] BAD", "",
            "DURATION: [ ] TOO_SHORT  [ ] RIGHT  [ ] TOO_LONG", "",
            "OVERALL: [ ] READY  [ ] MINOR_EDIT  [ ] MAJOR_EDIT  [ ] WRONG", "",
        ])
        (output_root / "final-bilingual-duration-review.md").write_text("\n".join(human), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_event_plan(path: Path) -> ClipEventPlan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    units = tuple(SemanticBoundaryUnit(
        int(item["start_ms"]), int(item["end_ms"]), str(item["text"]), tuple(item.get("roles") or ())
    ) for item in payload["units"])
    words = tuple(words_from_payload(payload["words"], language=str(payload.get("source_language") or "en")))
    return ClipEventPlan(
        event_id=str(payload["event_id"]), clip_id=str(payload.get("clip_id") or payload["event_id"]),
        source_path=str(payload["source_path"]), source_duration_ms=int(payload["source_duration_ms"]),
        payoff_anchor_ms=int(payload["payoff_anchor_ms"]),
        source_language=str(payload.get("source_language") or "en"), units=units, words=words,
        recording_id=str(payload.get("recording_id") or ""), glossary=dict(payload.get("glossary") or {}),
        raw_library_transcript=str(payload.get("raw_library_transcript") or ""),
        event_summary=str(payload.get("event_summary") or ""),
        game_title=str(payload.get("game_title") or ""),
        ocr_context=str(payload.get("ocr_context") or ""),
        creator=str(payload.get("creator") or ""), content_type=str(payload.get("content_type") or ""),
        tone=str(payload.get("tone") or ""), speaker_relations=str(payload.get("speaker_relations") or ""),
        current_topic=str(payload.get("current_topic") or ""),
        previous_callback=str(payload.get("previous_callback") or ""),
        required_evidence_span_ms=(
            tuple(int(value) for value in payload["required_evidence_span_ms"])
            if payload.get("required_evidence_span_ms") else None
        ),
        required_evidence_text=str(payload.get("required_evidence_text") or ""),
    )


__all__ = ["ClipEventPlan", "ClipVariantService", "RenderedVariant", "load_event_plan"]
