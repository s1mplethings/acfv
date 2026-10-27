from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import gc
import hashlib
import inspect
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Protocol

from acfv.processing.ffmpeg_runner import run_ffmpeg

from .subtitles import (
    SemanticImportance, SemanticPosition, SubtitleWord, language_release_state,
    language_risk_issue, words_from_payload,
)


_FINAL_ASR_ADAPTERS: dict[tuple[str, str], Any] = {}


@dataclass(frozen=True)
class FinalAsrConfig:
    model: str = "large-v3"
    multilingual_model: str = "large-v3"
    device: str = "auto"
    context_padding_ms: int = 5_000
    vad_filter: bool = True
    alignment_backend: str = "auto"
    correction_version: str = "source-refiner-v2"
    low_word_confidence: float = 0.60
    low_segment_logprob: float = -0.80
    high_no_speech_prob: float = 0.60
    local_redecode_padding_ms: int = 2_000
    max_local_redecodes: int = 4


@dataclass(frozen=True)
class FinalTranscriptRequest:
    recording_id: str
    event_id: str
    source_path: str
    source_duration_ms: int
    event_start_ms: int
    event_end_ms: int
    source_language: str
    raw_library_transcript: str = ""
    event_summary: str = ""
    game_title: str = ""
    ocr_context: str = ""
    payoff_anchor_ms: int | None = None
    glossary: dict[str, str] = field(default_factory=dict)
    music_spans: tuple[tuple[int, int], ...] = ()
    overlap_spans: tuple[tuple[int, int], ...] = ()
    lyrics_mode: bool = False


class ASRQualityFlag(str, Enum):
    LOW_WORD_CONFIDENCE = "LOW_WORD_CONFIDENCE"
    POSSIBLE_MUSIC = "POSSIBLE_MUSIC"
    LIKELY_BACKGROUND_LYRICS = "LIKELY_BACKGROUND_LYRICS"
    POSSIBLE_OVERLAP = "POSSIBLE_OVERLAP"
    REPEATED_FRAGMENT = "REPEATED_FRAGMENT"
    LANGUAGE_MISMATCH = "LANGUAGE_MISMATCH"
    BROKEN_SENTENCE = "BROKEN_SENTENCE"
    UNCERTAIN_PROPER_NOUN = "UNCERTAIN_PROPER_NOUN"


class SourceCorrectionState(str, Enum):
    UNCHANGED_CONFIDENT = "UNCHANGED_CONFIDENT"
    UNCHANGED = "UNCHANGED_CONFIDENT"  # compatibility alias
    AUTO_CORRECTED = "AUTO_CORRECTED"
    UNCHANGED_UNCERTAIN = "UNCHANGED_UNCERTAIN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class BrokenSentenceClass(str, Enum):
    TRUE_BROKEN = "TRUE_BROKEN"
    INTERRUPTED_SPEECH = "INTERRUPTED_SPEECH"
    VALID_FRAGMENT = "VALID_FRAGMENT"
    REACTION = "REACTION"
    ASR_ERROR = "ASR_ERROR"


@dataclass(frozen=True)
class CorrectionEvidence:
    candidate_text: str
    evidence_sources: tuple[str, ...] = ()
    independent_evidence_count: int = 0
    acoustic_support: bool = False
    repetition_support: bool = False
    glossary_support: bool = False
    OCR_support: bool = False
    context_support: bool = False
    semantic_risk: str = "LOW"
    correction_confidence: float = 0.0


@dataclass(frozen=True)
class SourceCorrection:
    raw_text: str
    corrected_text: str
    changes: tuple[dict[str, Any], ...] = ()
    confidence: float = 1.0
    reason: str = "no_change"
    state: str = SourceCorrectionState.UNCHANGED_CONFIDENT.value
    needs_review_reasons: tuple[str, ...] = ()
    evidence: CorrectionEvidence | None = None


@dataclass(frozen=True)
class FinalTranscriptQuality:
    total_words: int
    low_confidence_words: int
    corrected_words: int
    unchanged_words: int
    needs_review_words: int
    music_spans: tuple[tuple[int, int], ...]
    overlap_spans: tuple[tuple[int, int], ...]
    repeated_fragments_removed: int
    terminology_resolutions: tuple[dict[str, Any], ...]
    broken_sentences: int
    payoff_low_confidence: bool
    local_redecode_count: int
    final_quality_state: str
    issues: tuple[dict[str, Any], ...] = ()
    aggregate_risk: float = 0.0
    maximum_issue_risk: float = 0.0

    @property
    def low_confidence_word_ratio(self) -> float:
        return self.low_confidence_words / max(self.total_words, 1)


@dataclass(frozen=True)
class FinalTranscriptArtifact:
    cache_key: str
    path: str
    raw_library_transcript: str
    raw_final_asr: str
    corrected_final_transcript: str
    aligned_words: tuple[SubtitleWord, ...]
    final_asr_model: str
    timing_backend: str
    text_source: str
    timing_source: str
    context_start_ms: int
    context_end_ms: int
    event_start_ms: int
    event_end_ms: int
    correction: SourceCorrection
    wall_time_seconds: float
    audio_duration_seconds: float
    cache_hit: bool = False
    asr_wall_time_seconds: float = 0.0
    alignment_wall_time_seconds: float = 0.0
    correction_wall_time_seconds: float = 0.0
    quality: FinalTranscriptQuality | None = None
    quality_report_path: str = ""
    local_redecode_evidence: tuple[dict[str, Any], ...] = ()

    @property
    def rtf(self) -> float:
        return self.wall_time_seconds / max(self.audio_duration_seconds, 0.001)


class FinalAsrRunner(Protocol):
    def __call__(self, audio_path: Path, *, model: str, language: str | None,
                 device: str, vad_filter: bool, recording_offset_ms: int,
                 hotwords: str = "", context_prompt: str = "") -> tuple[list[dict[str, Any]], str]: ...


class WordAligner(Protocol):
    def __call__(self, audio_path: Path, segments: list[dict[str, Any]], *, language: str,
                 device: str, recording_offset_ms: int) -> tuple[list[dict[str, Any]], str]: ...


class SourceTranscriptRefiner:
    """Conservative source-text correction; timing remains owned by alignment."""

    def __init__(self, client: Any | None = None, *, max_input_chars: int = 3_000) -> None:
        self.client = client
        self.max_input_chars = max_input_chars

    def refine(self, raw_text: str, *, previous_sentence: str = "", next_sentence: str = "",
               event_summary: str = "", game_title: str = "", ocr_context: str = "",
               glossary: dict[str, str] | None = None,
               acoustic_alternatives: tuple[dict[str, Any], ...] = (),
               repeated_high_confidence_terms: tuple[str, ...] = (),
               human_confirmed_terms: tuple[str, ...] = ()) -> SourceCorrection:
        raw = _normalize_text(raw_text)
        if not raw or self.client is None:
            return SourceCorrection(
                raw, raw, confidence=1.0, reason="no_lexical_change_requested",
                state=SourceCorrectionState.UNCHANGED_CONFIDENT.value,
            )
        # Preserving the complete aligned source is safer than truncating a
        # several-minute transcript or accepting a partial model rewrite.
        if len(raw) > self.max_input_chars:
            return SourceCorrection(
                raw, raw, confidence=0.0, reason="UNCERTAIN_REFINER_INPUT_TOO_LONG",
                state=SourceCorrectionState.UNCHANGED_UNCERTAIN.value,
                needs_review_reasons=("REFINER_INPUT_TOO_LONG",),
            )
        try:
            payload = self.client.complete_json(
                system_prompt=(
                    "Correct obvious ASR word errors, sentence breaks, casing, punctuation, repeated fragments, "
                    "and high-confidence proper names. Preserve meaning, speech style, profanity, uncertainty, "
                    "and every supported claim. Do not rewrite, summarize, formalize, or add words that were not spoken. "
                    "A lexical replacement is allowed only when its change record cites acoustic_redecode, glossary, "
                    "OCR, repeated_high_confidence, or same_phrase evidence. Punctuation, capitalization, and exact "
                    "duplicate cleanup need no lexical evidence. If uncertain, keep the raw wording. Return JSON only."
                ),
                user_prompt=(
                    f"Previous: {previous_sentence}\nRaw: {raw}\nNext: {next_sentence}\n"
                    f"Event: {event_summary}\nGame: {game_title}\nOCR: {ocr_context}\n"
                    f"Glossary: {json.dumps(glossary or {}, ensure_ascii=False, sort_keys=True)}\n"
                    f"Acoustic alternatives: {json.dumps(acoustic_alternatives, ensure_ascii=False)}"
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "corrected_text": {"type": "string"},
                        "changes": {"type": "array"},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["corrected_text", "changes", "confidence", "reason"],
                },
                validator=lambda value: value,
                temperature=0.0,
            )
        except Exception:
            return SourceCorrection(
                raw, raw, confidence=0.0, reason="UNCERTAIN_REFINER_UNAVAILABLE",
                state=SourceCorrectionState.UNCHANGED_UNCERTAIN.value,
                needs_review_reasons=("REFINER_UNAVAILABLE",),
            )
        corrected = _normalize_text(str(payload.get("corrected_text") or ""))
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
        changes = tuple(item for item in payload.get("changes", []) if isinstance(item, dict))
        safe, reasons, evidence = _safe_correction(
            raw, corrected, changes=changes, glossary=glossary or {},
            acoustic_alternatives=acoustic_alternatives, ocr_context=ocr_context,
            repeated_high_confidence_terms=repeated_high_confidence_terms,
            human_confirmed_terms=human_confirmed_terms, confidence=confidence,
        )
        if confidence < 0.75 or not safe:
            hard_risk = bool({"PROFANITY_REMOVED", "NEGATION_REMOVED", "NUMBER_CHANGED"}.intersection(reasons))
            return SourceCorrection(
                raw, raw, changes, confidence, "UNCERTAIN",
                (SourceCorrectionState.NEEDS_REVIEW.value if hard_risk
                 else SourceCorrectionState.UNCHANGED_UNCERTAIN.value),
                tuple(reasons or ("LOW_CORRECTION_CONFIDENCE",)),
                evidence,
            )
        state = (SourceCorrectionState.UNCHANGED_CONFIDENT.value if corrected == raw
                 else SourceCorrectionState.AUTO_CORRECTED.value)
        return SourceCorrection(
            raw, corrected, changes, confidence,
            str(payload.get("reason") or "contextual_asr_correction"), state, (), evidence,
        )


class FinalClipTranscriptService:
    def __init__(self, *, config: FinalAsrConfig | None = None,
                 asr_runner: FinalAsrRunner | None = None,
                 aligner: WordAligner | None = None,
                 refiner: SourceTranscriptRefiner | None = None) -> None:
        self.config = config or FinalAsrConfig()
        self.asr_runner = asr_runner or _run_faster_whisper
        self.aligner = aligner or _align_words
        self.refiner = refiner or SourceTranscriptRefiner()

    def refine(self, request: FinalTranscriptRequest, *, output_root: Path) -> FinalTranscriptArtifact:
        source = Path(request.source_path)
        if not source.is_file():
            raise FileNotFoundError(f"Final Clip source media is missing: {source}")
        if request.event_end_ms <= request.event_start_ms:
            raise ValueError("Final event end must be after start")
        start = max(0, request.event_start_ms - self.config.context_padding_ms)
        end = min(request.source_duration_ms, request.event_end_ms + self.config.context_padding_ms)
        model = self._model_for(request.source_language)
        cache_key = self._cache_key(request, start=start, end=end, model=model)
        target = Path(output_root) / "final_transcript" / cache_key
        artifact_path = target / "final_event_transcript.json"
        if artifact_path.is_file():
            return _artifact_from_json(artifact_path, cache_hit=True)
        target.mkdir(parents=True, exist_ok=True)
        audio_path = target / "event_with_context.wav"
        _extract_audio(source, audio_path, start_ms=start, end_ms=end)
        started = time.perf_counter()
        segments, detected_language = self._run_asr(
            audio_path, model=model, language=_language_arg(request.source_language),
            recording_offset_ms=start, request=request,
        )
        asr_elapsed = time.perf_counter() - started
        if not segments:
            raise RuntimeError("FINAL_CLIP_TRANSCRIPT_REFINEMENT returned no speech")
        alignment_started = time.perf_counter()
        aligned, timing_backend = self.aligner(
            audio_path, segments, language=detected_language or request.source_language,
            device=self.config.device, recording_offset_ms=start,
        )
        alignment_elapsed = time.perf_counter() - alignment_started
        annotated = _annotate_aligned_words(
            aligned, segments, request=request, detected_language=detected_language,
            config=self.config,
        )
        words = words_from_payload(annotated, language=detected_language or request.source_language)
        words = [word for word in words if word.end_ms > request.event_start_ms and word.start_ms < request.event_end_ms]
        if not words:
            raise RuntimeError("Final alignment produced no words inside the semantic event")
        local_evidence = self._local_redecode(
            source, target, segments, request=request, model=model,
        )
        raw_text = _segments_text(segments, request.event_start_ms, request.event_end_ms)
        correction_started = time.perf_counter()
        correction = self.refiner.refine(
            raw_text, event_summary=request.event_summary, game_title=request.game_title,
            ocr_context=request.ocr_context, glossary=request.glossary,
            acoustic_alternatives=tuple(local_evidence),
        )
        correction_elapsed = time.perf_counter() - correction_started
        # A rejected/uncertain proposal is not a correction. Preserve the
        # original word timestamps, probabilities and per-word quality flags;
        # re-tokenizing the wider context text here used to erase all acoustic
        # confidence and falsely mark every event word as low-confidence.
        corrected_words = (
            _apply_correction_to_timed_words(words, correction.corrected_text)
            if correction.state == SourceCorrectionState.AUTO_CORRECTED.value
            else list(words)
        )
        if not request.lyrics_mode:
            corrected_words = [
                word for word in corrected_words
                if ASRQualityFlag.LIKELY_BACKGROUND_LYRICS.value not in word.quality_flags
            ]
        if not corrected_words:
            raise RuntimeError("Final transcript contains only suppressed background lyrics")
        quality = _build_quality_report(
            corrected_words, correction=correction, request=request,
            local_redecode_count=len(local_evidence),
        )
        elapsed = time.perf_counter() - started
        quality_path = target / "final_transcript_quality.json"
        artifact = FinalTranscriptArtifact(
            cache_key=cache_key, path=str(artifact_path.resolve()),
            raw_library_transcript=request.raw_library_transcript,
            raw_final_asr=raw_text, corrected_final_transcript=correction.corrected_text,
            aligned_words=tuple(corrected_words), final_asr_model=model,
            timing_backend=timing_backend, text_source="corrected_final_transcript",
            timing_source=timing_backend, context_start_ms=start, context_end_ms=end,
            event_start_ms=request.event_start_ms, event_end_ms=request.event_end_ms,
            correction=correction, wall_time_seconds=elapsed,
            audio_duration_seconds=(end - start) / 1000,
            asr_wall_time_seconds=asr_elapsed,
            alignment_wall_time_seconds=alignment_elapsed,
            correction_wall_time_seconds=correction_elapsed,
            quality=quality, quality_report_path=str(quality_path.resolve()),
            local_redecode_evidence=tuple(local_evidence),
        )
        _write_artifact(artifact_path, artifact, segments=segments)
        quality_path.write_text(
            json.dumps(_quality_payload(quality), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _release_accelerator_memory()
        return artifact

    def _local_redecode(self, source: Path, target: Path, segments: list[dict[str, Any]], *,
                        request: FinalTranscriptRequest, model: str) -> list[dict[str, Any]]:
        def confidence(row: dict[str, Any]) -> float | None:
            probabilities = [
                float(word["probability"]) for word in (row.get("words") or [])
                if word.get("probability") is not None
            ]
            if probabilities:
                return sum(probabilities) / len(probabilities)
            if row.get("avg_logprob") is not None:
                return max(0.0, min(1.0, float(__import__("math").exp(float(row["avg_logprob"])))))
            return None

        def token_probabilities(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {"token": str(word.get("word") or word.get("text") or "").strip(),
                 "probability": word.get("probability")}
                for row in rows for word in (row.get("words") or [])
                if str(word.get("word") or word.get("text") or "").strip()
            ]

        candidates = sorted(
            (item for item in segments if _segment_quality_flags(item, request=request, config=self.config)),
            key=lambda item: _high_risk_segment_priority(item, request=request), reverse=True,
        )[:self.config.max_local_redecodes]
        hotwords = _scoped_hotwords(request)
        context_prompt = " ".join(filter(None, (request.game_title, request.event_summary)))[:500]
        evidence: list[dict[str, Any]] = []
        for index, segment in enumerate(candidates):
            segment_start = round(float(segment.get("start", 0)) * 1000)
            segment_end = round(float(segment.get("end", 0)) * 1000)
            start = max(0, segment_start - self.config.local_redecode_padding_ms)
            end = min(request.source_duration_ms, segment_end + self.config.local_redecode_padding_ms)
            if end <= start:
                continue
            audio_path = target / f"local_redecode_{index + 1:02d}.wav"
            try:
                _extract_audio(source, audio_path, start_ms=start, end_ms=end)
                rows, language = self._run_asr(
                    audio_path, model=model, language=_language_arg(request.source_language),
                    recording_offset_ms=start, request=request,
                )
            except Exception as exc:
                evidence.append({
                    "start_ms": start, "end_ms": end, "status": "UNAVAILABLE",
                    "error": f"{type(exc).__name__}: {exc}",
                    "window_bounds": {"start_ms": start, "end_ms": end},
                    "model": model, "compute_type": "adapter-managed",
                    "hotwords": list(hotwords), "context": context_prompt,
                    "config": asdict(self.config), "decision": "UNAVAILABLE",
                })
                continue
            original_confidence = confidence(segment)
            local_values = [value for value in (confidence(row) for row in rows) if value is not None]
            local_confidence = sum(local_values) / len(local_values) if local_values else None
            delta = (
                local_confidence - original_confidence
                if local_confidence is not None and original_confidence is not None else None
            )
            original_text = _normalize_text(str(segment.get("text") or ""))
            candidate_text = _segments_text(rows, segment_start, segment_end)
            if candidate_text.casefold() == original_text.casefold():
                decision = "SUPPORTS_RAW"
            elif delta is not None and delta >= 0.15:
                decision = "HIGHER_CONFIDENCE_ALTERNATIVE_REQUIRES_INDEPENDENT_SUPPORT"
            else:
                decision = "INCONCLUSIVE_KEEP_RAW"
            evidence.append({
                "start_ms": start, "end_ms": end, "status": "READY",
                "text": candidate_text, "candidate_text": candidate_text,
                "original_text": original_text,
                "original_confidence": original_confidence,
                "original_probability": original_confidence,
                "original_segment_avg_logprob": segment.get("avg_logprob"),
                "original_no_speech_prob": segment.get("no_speech_prob"),
                "local_redecode_confidence": local_confidence,
                "local_probability": local_confidence,
                "local_avg_logprob": (
                    sum(float(row["avg_logprob"]) for row in rows if row.get("avg_logprob") is not None)
                    / max(1, sum(row.get("avg_logprob") is not None for row in rows))
                ),
                "confidence_delta": delta,
                "original_token_probabilities": token_probabilities((segment,)),
                "local_token_probabilities": token_probabilities(rows),
                "window_bounds": {"start_ms": start, "end_ms": end},
                "model": model, "compute_type": "adapter-managed",
                "hotwords": list(hotwords), "context": context_prompt,
                "config": asdict(self.config), "decision": decision,
                "language": language, "source": "acoustic_redecode",
            })
        return evidence

    def _run_asr(self, audio_path: Path, *, model: str, language: str | None,
                 recording_offset_ms: int, request: FinalTranscriptRequest) -> tuple[list[dict[str, Any]], str]:
        kwargs: dict[str, Any] = {
            "model": model, "language": language, "device": self.config.device,
            "vad_filter": self.config.vad_filter, "recording_offset_ms": recording_offset_ms,
        }
        parameters = inspect.signature(self.asr_runner).parameters
        if "hotwords" in parameters:
            kwargs["hotwords"] = ", ".join(_scoped_hotwords(request))
        if "context_prompt" in parameters:
            kwargs["context_prompt"] = " ".join(filter(None, (
                request.game_title, request.event_summary, request.ocr_context,
            )))[:500]
        return self.asr_runner(audio_path, **kwargs)

    def _model_for(self, language: str) -> str:
        return self.config.model if _language_arg(language) == "en" else self.config.multilingual_model

    def _cache_key(self, request: FinalTranscriptRequest, *, start: int, end: int, model: str) -> str:
        payload = {
            "recording_id": request.recording_id, "event_id": request.event_id,
            "audio_start_ms": start, "audio_end_ms": end, "asr_model": model,
            "vad_filter": self.config.vad_filter, "alignment_backend": self.config.alignment_backend,
            "correction_version": self.config.correction_version,
            "quality_policy": "final-language-quality-v3-preserve-acoustic-confidence",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _extract_audio(source: Path, target: Path, *, start_ms: int, end_ms: int) -> None:
    run_ffmpeg([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start_ms / 1000:.3f}",
        "-i", str(source), "-t", f"{(end_ms - start_ms) / 1000:.3f}", "-vn", "-ac", "1",
        "-ar", "16000", "-c:a", "pcm_s16le", str(target),
    ], timeout=max(120, int((end_ms - start_ms) / 1000) * 3))


def _run_faster_whisper(audio_path: Path, *, model: str, language: str | None, device: str,
                        vad_filter: bool, recording_offset_ms: int, hotwords: str = "",
                        context_prompt: str = "") -> tuple[list[dict[str, Any]], str]:
    from acfv.steps.transcribe_audio.impl import _load_faster_whisper_model

    key = (model, device)
    adapter = _FINAL_ASR_ADAPTERS.get(key)
    if adapter is None:
        adapter = _load_faster_whisper_model(model, device)
        _FINAL_ASR_ADAPTERS[key] = adapter
    options = dict(language=language, word_timestamps=True, vad_filter=vad_filter,
                   vad_parameters={"min_silence_duration_ms": 500},
                   condition_on_previous_text=True)
    if hotwords:
        options["hotwords"] = hotwords
    if context_prompt:
        options["initial_prompt"] = context_prompt
    try:
        segments, info = adapter._model.transcribe(str(audio_path), **options)
    except TypeError:
        options.pop("hotwords", None)
        options.pop("initial_prompt", None)
        segments, info = adapter._model.transcribe(str(audio_path), **options)
    rows: list[dict[str, Any]] = []
    offset = recording_offset_ms / 1000
    for segment in segments:
        row = {
            "start": float(segment.start) + offset, "end": float(segment.end) + offset,
            "text": str(segment.text).strip(), "avg_logprob": getattr(segment, "avg_logprob", None),
            "no_speech_prob": getattr(segment, "no_speech_prob", None),
            "compression_ratio": getattr(segment, "compression_ratio", None), "words": [],
        }
        for word in getattr(segment, "words", None) or []:
            if word.start is None or word.end is None:
                continue
            row["words"].append({
                "start": float(word.start) + offset, "end": float(word.end) + offset,
                "word": str(word.word).strip(), "probability": getattr(word, "probability", None),
            })
        rows.append(row)
    return rows, str(getattr(info, "language", None) or language or "")


def _align_words(audio_path: Path, segments: list[dict[str, Any]], *, language: str,
                 device: str, recording_offset_ms: int) -> tuple[list[dict[str, Any]], str]:
    existing = [word for segment in segments for word in segment.get("words", []) if word.get("word")]
    if not existing:
        raise RuntimeError("Reliable word alignment unavailable: ASR returned no word timestamps")
    # ASR words are already absolute because the ASR runner applied recording_offset_ms.
    return existing, "faster-whisper-word-timestamps"


def _segments_text(segments: Iterable[dict[str, Any]], start_ms: int, end_ms: int) -> str:
    parts = [str(item.get("text") or "").strip() for item in segments
             if float(item.get("end", 0)) * 1000 > start_ms and float(item.get("start", 0)) * 1000 < end_ms]
    return _normalize_text(" ".join(part for part in parts if part))


def _apply_correction_to_timed_words(words: list[SubtitleWord], corrected_text: str) -> list[SubtitleWord]:
    tokens = re.findall(r"\S+", corrected_text)
    if not tokens:
        raise RuntimeError("Source correction produced empty text")
    if len(tokens) != len(words):
        # Timing facts remain untouched. For non-token-preserving corrections, distribute
        # corrected tokens monotonically across the already aligned event span.
        start, end = words[0].start_ms, words[-1].end_ms
        width = max(1, (end - start) / len(tokens))
        return [SubtitleWord(
            f"corrected-{index:06d}", token, round(start + index * width),
            max(round(start + (index + 1) * width), round(start + index * width) + 1),
            None, words[0].language, words[0].speaker, token, "SOURCE_REFINER",
            tuple(sorted({flag for word in words for flag in word.quality_flags})),
        ) for index, token in enumerate(tokens)]
    return [replace(
        word, text=token,
        source="SOURCE_REFINER" if token != word.text else word.source,
    ) for word, token in zip(words, tokens)]


def _safe_correction(raw: str, corrected: str, *, changes: tuple[dict[str, Any], ...] = (),
                     glossary: dict[str, str] | None = None,
                     acoustic_alternatives: tuple[dict[str, Any], ...] = (),
                     ocr_context: str = "", repeated_high_confidence_terms: tuple[str, ...] = (),
                     human_confirmed_terms: tuple[str, ...] = (),
                     confidence: float = 0.0) -> tuple[bool, list[str], CorrectionEvidence]:
    reasons: list[str] = []
    if not corrected:
        evidence = CorrectionEvidence(corrected, correction_confidence=confidence)
        return False, ["EMPTY_CORRECTION"], evidence
    raw_tokens = re.findall(r"[\w']+", raw.casefold())
    corrected_tokens = re.findall(r"[\w']+", corrected.casefold())
    if not raw_tokens or not corrected_tokens:
        evidence = CorrectionEvidence(corrected, correction_confidence=confidence)
        return False, ["EMPTY_TOKENS"], evidence
    profanity = {"fuck", "fucking", "shit", "bitch", "damn", "ass"}
    if profanity.intersection(raw_tokens) - set(corrected_tokens):
        reasons.append("PROFANITY_REMOVED")
    negation = {"not", "no", "never", "can't", "cannot", "won't", "didn't", "isn't", "wasn't"}
    if negation.intersection(raw_tokens) - set(corrected_tokens):
        reasons.append("NEGATION_REMOVED")
    raw_numbers = re.findall(r"\d+(?:\.\d+)?%?", raw)
    if raw_numbers != re.findall(r"\d+(?:\.\d+)?%?", corrected):
        reasons.append("NUMBER_CHANGED")
    # Exact duplicate removal is the only token-count-changing auto edit.
    if len(corrected_tokens) != len(raw_tokens):
        deduped = [token for index, token in enumerate(raw_tokens)
                   if index == 0 or token != raw_tokens[index - 1]]
        if corrected_tokens != deduped:
            reasons.append("UNSUPPORTED_TOKEN_COUNT_CHANGE")
    lexical_change = raw_tokens != corrected_tokens and not (
        len(corrected_tokens) < len(raw_tokens)
        and corrected_tokens == [token for index, token in enumerate(raw_tokens)
                                 if index == 0 or token != raw_tokens[index - 1]]
    )
    declared = {
        str(item.get("evidence_type") or item.get("evidence") or "").casefold()
        for item in changes
    }
    corrected_folded = corrected.casefold()
    acoustic_support = any(
        str(item.get("status") or "READY").upper() == "READY"
        and str(item.get("text") or "").strip().casefold() == corrected_folded
        and str(item.get("text") or "").strip().casefold() != raw.casefold()
        for item in acoustic_alternatives
    ) and "acoustic_redecode" in declared
    glossary_values = {str(key).casefold() for key in (glossary or {})} | {
        str(value).casefold() for value in (glossary or {}).values()
    }
    glossary_support = (
        "glossary" in declared and any(token in glossary_values for token in corrected_tokens)
    )
    ocr_folded = ocr_context.casefold()
    ocr_support = "ocr" in declared and any(
        str(item.get("after") or "").strip().casefold() in ocr_folded
        for item in changes if str(item.get("evidence_type") or "").casefold() == "ocr"
    )
    repeated_folded = {str(item).casefold() for item in repeated_high_confidence_terms}
    repetition_support = bool(declared.intersection({"repeated_high_confidence", "same_phrase"})) and any(
        str(item.get("after") or "").strip().casefold() in repeated_folded for item in changes
    )
    human_folded = {str(item).casefold() for item in human_confirmed_terms}
    human_tm_support = "human_translation_memory" in declared and any(
        str(item.get("after") or "").strip().casefold() in human_folded for item in changes
    )
    evidence_sources = tuple(name for name, supported in (
        ("acoustic_redecode", acoustic_support),
        ("repeated_high_confidence", repetition_support),
        ("glossary", glossary_support),
        ("ocr", ocr_support),
        ("human_translation_memory", human_tm_support),
    ) if supported)
    independent_count = len(evidence_sources)
    semantic_risk = "CRITICAL" if any(reason in reasons for reason in (
        "NEGATION_REMOVED", "NUMBER_CHANGED", "PROFANITY_REMOVED"
    )) else "MEDIUM" if lexical_change else "LOW"
    evidence = CorrectionEvidence(
        candidate_text=corrected, evidence_sources=evidence_sources,
        independent_evidence_count=independent_count,
        acoustic_support=acoustic_support, repetition_support=repetition_support,
        glossary_support=glossary_support, OCR_support=ocr_support,
        context_support=bool(declared.intersection({"context", "qwen_context"})),
        semantic_risk=semantic_risk, correction_confidence=confidence,
    )
    if lexical_change:
        if independent_count == 0:
            reasons.append("LEXICAL_CHANGE_WITHOUT_EXTERNAL_EVIDENCE")
        elif independent_count < 2:
            reasons.append("LEXICAL_CHANGE_WITH_INSUFFICIENT_INDEPENDENT_EVIDENCE")
    return not reasons, reasons, evidence


def _span_overlaps(start_ms: int, end_ms: int, spans: tuple[tuple[int, int], ...]) -> bool:
    return any(end_ms > start and start_ms < end for start, end in spans)


def classify_broken_sentence(text: str) -> BrokenSentenceClass:
    """Classify speech form without treating conversational fragments as ASR damage."""
    normalized = _normalize_text(text)
    tokens = re.findall(r"[\w']+", normalized.casefold())
    if not tokens:
        return BrokenSentenceClass.ASR_ERROR
    if any(tokens[index:index + 2] == tokens[index + 2:index + 4]
           for index in range(max(0, len(tokens) - 3))):
        return BrokenSentenceClass.ASR_ERROR
    if re.search(r"(?:—|-|\.\.\.)\s*$", normalized):
        return BrokenSentenceClass.INTERRUPTED_SPEECH
    reaction_words = {
        "oh", "wow", "whoa", "no", "yes", "what", "why", "damn", "shit", "fuck",
        "really", "seriously", "help", "wait", "stop", "nice", "okay", "omg",
    }
    if len(tokens) <= 5 and (
        normalized.endswith(("!", "?", "?!", "!?")) or tokens[0] in reaction_words
    ):
        return BrokenSentenceClass.REACTION
    dangling = {"and", "but", "because", "so", "that", "if", "when", "although", "to"}
    if tokens[-1] in dangling or re.search(r"[,;:]\s*$", normalized):
        return BrokenSentenceClass.TRUE_BROKEN
    if re.search(r"[!?\.]\s*$", normalized) or len(tokens) <= 8:
        return BrokenSentenceClass.VALID_FRAGMENT
    return BrokenSentenceClass.VALID_FRAGMENT


def _segment_quality_flags(segment: dict[str, Any], *, request: FinalTranscriptRequest,
                           config: FinalAsrConfig) -> tuple[str, ...]:
    flags: list[str] = []
    words = list(segment.get("words") or [])
    probabilities = [float(word["probability"]) for word in words if word.get("probability") is not None]
    if ((probabilities and sum(probabilities) / len(probabilities) < config.low_word_confidence)
            or (segment.get("avg_logprob") is not None
                and float(segment["avg_logprob"]) < config.low_segment_logprob)
            or (segment.get("no_speech_prob") is not None
                and float(segment["no_speech_prob"]) > config.high_no_speech_prob)):
        flags.append(ASRQualityFlag.LOW_WORD_CONFIDENCE.value)
    text = _normalize_text(str(segment.get("text") or ""))
    tokens = re.findall(r"[\w']+", text.casefold())
    if any(tokens[index:index + 2] == tokens[index + 2:index + 4]
           for index in range(max(0, len(tokens) - 3))):
        flags.append(ASRQualityFlag.REPEATED_FRAGMENT.value)
    sentence_class = classify_broken_sentence(text)
    suspect = bool(text and (
        re.search(r"^(?:and|but|because|so|that|there's|i|you)\b", text, re.I)
        or re.search(r"\b(?:and|but|because|so|that|i|you)$", text, re.I)
        or re.search(r"[!?.,]{3,}", text)
        or sentence_class in {BrokenSentenceClass.INTERRUPTED_SPEECH, BrokenSentenceClass.REACTION}
    ))
    if suspect:
        flags.append(f"SENTENCE_CLASS_{sentence_class.value}")
    if sentence_class in {BrokenSentenceClass.TRUE_BROKEN, BrokenSentenceClass.ASR_ERROR}:
        flags.append(ASRQualityFlag.BROKEN_SENTENCE.value)
    start_ms = round(float(segment.get("start", 0)) * 1000)
    end_ms = round(float(segment.get("end", 0)) * 1000)
    if segment.get("music") or _span_overlaps(start_ms, end_ms, request.music_spans):
        flags.extend((ASRQualityFlag.POSSIBLE_MUSIC.value,
                      ASRQualityFlag.LIKELY_BACKGROUND_LYRICS.value))
    if segment.get("overlap") or _span_overlaps(start_ms, end_ms, request.overlap_spans):
        flags.append(ASRQualityFlag.POSSIBLE_OVERLAP.value)
    return tuple(dict.fromkeys(flags))


_HIGH_RISK_ASR = re.compile(
    r"\b(?:no|not|never|can't|cannot|won't|didn't|doesn't|isn't|wasn't|"
    r"\d+(?:\.\d+)?%?|won|lost|dead|died|killed|escaped|result|answer)\b",
    re.IGNORECASE,
)


def _high_risk_segment_priority(segment: dict[str, Any], *, request: FinalTranscriptRequest) -> tuple[int, int, float]:
    """Prioritize low-confidence semantic risk rather than all uncertainty."""
    text = str(segment.get("text") or "")
    start = round(float(segment.get("start", 0)) * 1000)
    end = round(float(segment.get("end", 0)) * 1000)
    near_payoff = bool(request.payoff_anchor_ms is not None and start - 3_000 <= request.payoff_anchor_ms <= end + 3_000)
    identity_or_game = any(
        term and re.search(rf"\b{re.escape(str(term))}\b", text, re.IGNORECASE)
        for term in request.glossary
    ) or bool(re.search(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text))
    semantic = bool(_HIGH_RISK_ASR.search(text))
    confidence = [float(word["probability"]) for word in segment.get("words") or []
                  if word.get("probability") is not None]
    lowest = 1.0 - (sum(confidence) / len(confidence) if confidence else 0.5)
    return (int(near_payoff) + int(semantic), int(identity_or_game), lowest)


def _scoped_hotwords(request: FinalTranscriptRequest) -> tuple[str, ...]:
    """Use only context-relevant recording/game/creator terms, in scoped order."""
    context = " ".join((request.event_summary, request.game_title, request.ocr_context)).casefold()
    recording_terms = [term for term in request.glossary if str(term).casefold() in context]
    game_terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", request.game_title)
    ocr_terms = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", request.ocr_context)
    ordered = []
    for term in (*recording_terms, *game_terms, *ocr_terms):
        value = str(term).strip()
        if value and value.casefold() not in {item.casefold() for item in ordered}:
            ordered.append(value)
    return tuple(ordered[:40])


def _annotate_aligned_words(aligned: list[dict[str, Any]], segments: list[dict[str, Any]], *,
                            request: FinalTranscriptRequest, detected_language: str,
                            config: FinalAsrConfig) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    expected_language = _language_arg(request.source_language)
    mismatch = bool(expected_language and detected_language and
                    _language_arg(detected_language) != expected_language)
    previous = ""
    for item in aligned:
        row = dict(item)
        start_ms = int(row.get("start_ms") if row.get("start_ms") is not None
                       else round(float(row.get("start", 0)) * 1000))
        end_ms = int(row.get("end_ms") if row.get("end_ms") is not None
                     else round(float(row.get("end", 0)) * 1000))
        containing = next((segment for segment in segments
                           if float(segment.get("end", 0)) * 1000 > start_ms
                           and float(segment.get("start", 0)) * 1000 < end_ms), {})
        flags = list(_segment_quality_flags(containing, request=request, config=config))
        probability = row.get("probability")
        if (ASRQualityFlag.LOW_WORD_CONFIDENCE.value in flags and probability is not None
                and float(probability) >= config.low_word_confidence):
            flags.remove(ASRQualityFlag.LOW_WORD_CONFIDENCE.value)
        if probability is not None and float(probability) < config.low_word_confidence:
            flags.append(ASRQualityFlag.LOW_WORD_CONFIDENCE.value)
        segment_end_ms = round(float(containing.get("end", 0)) * 1000) if containing else end_ms
        if (ASRQualityFlag.BROKEN_SENTENCE.value in flags
                and end_ms < segment_end_ms - 100):
            flags.remove(ASRQualityFlag.BROKEN_SENTENCE.value)
        # Repetition is a word-level signal. A segment-level repeated-pattern
        # detector selects a local re-decode window but must not mark every word.
        if ASRQualityFlag.REPEATED_FRAGMENT.value in flags:
            flags.remove(ASRQualityFlag.REPEATED_FRAGMENT.value)
        token = str(row.get("word") or row.get("text") or "").strip()
        normalized = re.sub(r"\W+", "", token.casefold())
        if normalized and normalized == previous:
            flags.append(ASRQualityFlag.REPEATED_FRAGMENT.value)
        previous = normalized
        if mismatch:
            flags.append(ASRQualityFlag.LANGUAGE_MISMATCH.value)
        if token[:1].isupper() and token.casefold() not in {
            "i", "i'm", "i've", "the", "a", "an",
        } and probability is not None and float(probability) < 0.80:
            flags.append(ASRQualityFlag.UNCERTAIN_PROPER_NOUN.value)
        row.update({
            "raw_text": token, "source": "FINAL_ASR",
            "quality_flags": list(dict.fromkeys(flags)),
        })
        annotated.append(row)
    return annotated


def _build_quality_report(words: list[SubtitleWord], *, correction: SourceCorrection,
                          request: FinalTranscriptRequest,
                          local_redecode_count: int) -> FinalTranscriptQuality:
    low = sum(ASRQualityFlag.LOW_WORD_CONFIDENCE.value in word.quality_flags for word in words)
    broken = len({(word.start_ms, word.end_ms) for word in words
                  if ASRQualityFlag.BROKEN_SENTENCE.value in word.quality_flags})
    overlap = any(ASRQualityFlag.POSSIBLE_OVERLAP.value in word.quality_flags for word in words)
    anchor = request.payoff_anchor_ms
    payoff_low = bool(anchor is not None and any(
        abs(((word.start_ms + word.end_ms) // 2) - anchor) <= 2_000
        and ASRQualityFlag.LOW_WORD_CONFIDENCE.value in word.quality_flags for word in words
    ))
    needs_review = sum(bool(set(word.quality_flags).intersection({
        ASRQualityFlag.LOW_WORD_CONFIDENCE.value,
        ASRQualityFlag.POSSIBLE_OVERLAP.value,
        ASRQualityFlag.LANGUAGE_MISMATCH.value,
        ASRQualityFlag.UNCERTAIN_PROPER_NOUN.value,
    })) for word in words)
    issues: list[dict[str, Any]] = []
    filler_words = {"a", "an", "the", "uh", "um", "erm", "like", "well", "so", "okay", "yeah"}
    negations = {"not", "no", "never", "can't", "cannot", "won't", "didn't", "isn't", "wasn't"}
    for index, word in enumerate(words):
        flags = set(word.quality_flags)
        if not flags.intersection({
            ASRQualityFlag.LOW_WORD_CONFIDENCE.value, ASRQualityFlag.POSSIBLE_OVERLAP.value,
            ASRQualityFlag.LANGUAGE_MISMATCH.value, ASRQualityFlag.UNCERTAIN_PROPER_NOUN.value,
            ASRQualityFlag.BROKEN_SENTENCE.value,
        }):
            continue
        token = re.sub(r"[^\w']+", "", word.text.casefold())
        midpoint = (word.start_ms + word.end_ms) // 2
        position = _semantic_position(midpoint, request)
        importance = "LOW" if token in filler_words else "MEDIUM"
        issue_type = "LOW_WORD_CONFIDENCE"
        severity = "WARNING"
        hard_blocker = False
        if token in negations or re.fullmatch(r"\d+(?:\.\d+)?%?", token):
            importance, severity = "CRITICAL", "CRITICAL"
            issue_type = "UNRESOLVED_NEGATION" if token in negations else "UNRESOLVED_KEY_NUMBER"
            hard_blocker = position in {"CORE", "PAYOFF"}
        elif ASRQualityFlag.UNCERTAIN_PROPER_NOUN.value in flags:
            importance, severity, issue_type = "HIGH", "HIGH", "UNCERTAIN_IDENTITY"
            hard_blocker = position in {"CORE", "PAYOFF"}
        elif ASRQualityFlag.LANGUAGE_MISMATCH.value in flags:
            importance, severity, issue_type = "HIGH", "HIGH", "LANGUAGE_MISMATCH"
        elif ASRQualityFlag.POSSIBLE_OVERLAP.value in flags:
            importance, severity, issue_type = "MEDIUM", "WARNING", "POSSIBLE_OVERLAP"
        elif ASRQualityFlag.BROKEN_SENTENCE.value in flags:
            importance, severity, issue_type = "MEDIUM", "WARNING", "TRUE_BROKEN_OR_ASR_ERROR"
        confidence = 1.0 if word.confidence is None else max(0.0, 1.0 - float(word.confidence))
        if (position == "PAYOFF" and ASRQualityFlag.LOW_WORD_CONFIDENCE.value in flags
                and word.confidence is not None and word.confidence < 0.25):
            importance, severity, hard_blocker = "CRITICAL", "CRITICAL", True
            issue_type = "EXTREMELY_LOW_CONFIDENCE_PAYOFF"
        issues.append(language_risk_issue(
            issue_id=f"asr:{index}:{issue_type}", issue_type=issue_type,
            timestamp_ms=midpoint, severity=severity, semantic_importance=importance,
            semantic_position=position, evidence_confidence=confidence,
            clip_id=request.event_id, start_ms=word.start_ms, end_ms=word.end_ms,
            root_cause_key=f"asr:{request.recording_id}:{word.word_id}",
            evidence_source="final-asr-word-quality", semantic_consequence=issue_type,
            evidence={"word": word.text, "confidence": word.confidence, "flags": sorted(flags)},
            recommended_action="MANUAL_REVIEW" if hard_blocker else "ACCEPT_OR_REVIEW",
            hard_blocker=hard_blocker,
        ))
    if correction.state in {
        SourceCorrectionState.UNCHANGED_UNCERTAIN.value, SourceCorrectionState.NEEDS_REVIEW.value,
    }:
        hard = correction.state == SourceCorrectionState.NEEDS_REVIEW.value
        issues.append(language_risk_issue(
            issue_id="source-correction:decision", issue_type="SOURCE_CORRECTION_UNRESOLVED",
            severity="CRITICAL" if hard else "WARNING",
            semantic_importance="CRITICAL" if hard else "LOW", semantic_position="CONTEXT",
            evidence_confidence=max(0.25, 1.0 - correction.confidence),
            evidence={"state": correction.state, "reasons": list(correction.needs_review_reasons)},
            recommended_action="MANUAL_REVIEW" if hard else "KEEP_RAW",
            hard_blocker=hard,
        ))
    state, aggregate_risk, maximum_risk = language_release_state(issues)
    terminology = tuple(item for item in correction.changes
                        if str(item.get("evidence_type") or "").casefold() == "glossary")
    return FinalTranscriptQuality(
        total_words=len(words), low_confidence_words=low,
        corrected_words=sum(word.text != word.raw_text for word in words),
        unchanged_words=sum(word.text == word.raw_text for word in words),
        needs_review_words=needs_review,
        music_spans=request.music_spans, overlap_spans=request.overlap_spans,
        repeated_fragments_removed=sum(
            str(item.get("type") or "").casefold() in {"duplicate_removal", "repeated_fragment_removal"}
            for item in correction.changes
        ),
        terminology_resolutions=terminology, broken_sentences=broken,
        payoff_low_confidence=payoff_low, local_redecode_count=local_redecode_count,
        final_quality_state=state, issues=tuple(issues), aggregate_risk=aggregate_risk,
        maximum_issue_risk=maximum_risk,
    )


def _semantic_position(timestamp_ms: int, request: FinalTranscriptRequest) -> str:
    if request.payoff_anchor_ms is not None:
        delta = timestamp_ms - request.payoff_anchor_ms
        if abs(delta) <= 2_000:
            return SemanticPosition.PAYOFF.value
        if delta > 2_000:
            return SemanticPosition.AFTERMATH.value
    span = max(1, request.event_end_ms - request.event_start_ms)
    ratio = (timestamp_ms - request.event_start_ms) / span
    if ratio < 0.2:
        return SemanticPosition.SETUP.value
    if ratio < 0.45:
        return SemanticPosition.CONTEXT.value
    if ratio < 0.8:
        return SemanticPosition.CORE.value
    return SemanticPosition.AFTERMATH.value


def _quality_payload(quality: FinalTranscriptQuality) -> dict[str, Any]:
    payload = asdict(quality)
    payload["low_confidence_word_ratio"] = round(quality.low_confidence_word_ratio, 6)
    payload["ASR_RELEASE_STATE"] = quality.final_quality_state
    return payload


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _language_arg(language: str) -> str | None:
    value = str(language or "").strip().lower().split("-")[0]
    return None if value in {"", "auto", "detect", "mixed", "multilingual"} else value


def _write_artifact(path: Path, artifact: FinalTranscriptArtifact, *, segments: list[dict[str, Any]]) -> None:
    payload = asdict(artifact)
    payload["aligned_words"] = [asdict(word) for word in artifact.aligned_words]
    payload["correction"] = asdict(artifact.correction)
    payload["raw_final_asr_segments"] = segments
    payload["rtf"] = artifact.rtf
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _artifact_from_json(path: Path, *, cache_hit: bool) -> FinalTranscriptArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    correction_payload = dict(payload["correction"])
    correction_payload["changes"] = tuple(correction_payload.get("changes") or ())
    correction_payload["needs_review_reasons"] = tuple(correction_payload.get("needs_review_reasons") or ())
    if isinstance(correction_payload.get("evidence"), dict):
        evidence_payload = dict(correction_payload["evidence"])
        evidence_payload["evidence_sources"] = tuple(evidence_payload.get("evidence_sources") or ())
        correction_payload["evidence"] = CorrectionEvidence(**evidence_payload)
    correction = SourceCorrection(**correction_payload)
    quality_payload = payload.get("quality")
    quality = None
    if isinstance(quality_payload, dict):
        quality_payload = dict(quality_payload)
        quality_payload["music_spans"] = tuple(tuple(item) for item in quality_payload.get("music_spans") or ())
        quality_payload["overlap_spans"] = tuple(tuple(item) for item in quality_payload.get("overlap_spans") or ())
        quality_payload["terminology_resolutions"] = tuple(quality_payload.get("terminology_resolutions") or ())
        quality_payload["issues"] = tuple(quality_payload.get("issues") or ())
        quality = FinalTranscriptQuality(**quality_payload)
    return FinalTranscriptArtifact(
        cache_key=payload["cache_key"], path=str(path.resolve()),
        raw_library_transcript=payload.get("raw_library_transcript", ""),
        raw_final_asr=payload["raw_final_asr"], corrected_final_transcript=payload["corrected_final_transcript"],
        aligned_words=tuple(SubtitleWord(**item) for item in payload["aligned_words"]),
        final_asr_model=payload["final_asr_model"], timing_backend=payload["timing_backend"],
        text_source=payload["text_source"], timing_source=payload["timing_source"],
        context_start_ms=payload["context_start_ms"], context_end_ms=payload["context_end_ms"],
        event_start_ms=payload["event_start_ms"], event_end_ms=payload["event_end_ms"],
        correction=correction, wall_time_seconds=payload["wall_time_seconds"],
        audio_duration_seconds=payload["audio_duration_seconds"], cache_hit=cache_hit,
        asr_wall_time_seconds=float(payload.get("asr_wall_time_seconds", payload["wall_time_seconds"])),
        alignment_wall_time_seconds=float(payload.get("alignment_wall_time_seconds", 0.0)),
        correction_wall_time_seconds=float(payload.get("correction_wall_time_seconds", 0.0)),
        quality=quality, quality_report_path=str(payload.get("quality_report_path") or ""),
        local_redecode_evidence=tuple(payload.get("local_redecode_evidence") or ()),
    )


def _release_accelerator_memory() -> None:
    _FINAL_ASR_ADAPTERS.clear()
    try:
        from acfv.steps.transcribe_audio.impl import _clear_transcriber_cache
        _clear_transcriber_cache()
    except Exception:
        pass
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


__all__ = [
    "ASRQualityFlag", "BrokenSentenceClass", "CorrectionEvidence", "FinalAsrConfig",
    "FinalClipTranscriptService", "FinalTranscriptArtifact", "classify_broken_sentence",
    "FinalTranscriptQuality", "FinalTranscriptRequest", "SourceCorrection", "SourceCorrectionState",
    "SourceTranscriptRefiner",
]
