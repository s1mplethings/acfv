from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class TranscriptSpanClassification(str, Enum):
    SPEECH = "SPEECH"
    LIKELY_BACKGROUND_LYRICS = "LIKELY_BACKGROUND_LYRICS"
    NON_SPEECH_REACTION = "NON_SPEECH_REACTION"
    NOISE = "NOISE"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class TextCorrection:
    raw_text: str
    corrected_text: str
    correction_reason: str
    confidence: float
    correction_provider: str = "acfv-conservative-v1"
    version: str = "1.0"


@dataclass(frozen=True)
class TranscriptSpanProfile:
    start_ms: int
    end_ms: int
    raw_text: str
    display_text: str
    detected_language: str
    confidence: float
    language_source: str
    mixed: bool
    classification: TranscriptSpanClassification
    classification_confidence: float
    correction: TextCorrection | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["classification"] = self.classification.value
        return payload


@dataclass(frozen=True)
class RecordingLanguageProfile:
    primary_language: str
    secondary_languages: tuple[str, ...]
    mixed_language: bool
    confidence: float
    source: str
    transcript_language_distribution: dict[str, float]
    segment_language_distribution: dict[str, float]
    last_analyzed_at: str
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["secondary_languages"] = list(self.secondary_languages)
        return payload


_REACTIONS = re.compile(
    r"^(?:oh+|ah+|wow+|whoa+|no+|yes+|what+|huh+|ha(?:ha)+|lmao+|lol+|scream(?:ing)?|laugh(?:ing)?)\W*$",
    re.IGNORECASE,
)


def _compact(text: str) -> str:
    return " ".join(text.split())


def _meaningful(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char)[0] in {"L", "N"})


def _script_counts(text: str) -> dict[str, int]:
    return {
        "latin": len(re.findall(r"[A-Za-z]", text)),
        "kana": len(re.findall(r"[\u3040-\u30ff]", text)),
        "han": len(re.findall(r"[\u3400-\u9fff]", text)),
        "hangul": len(re.findall(r"[\uac00-\ud7af]", text)),
    }


def detect_text_language(text: str) -> tuple[str, float, bool]:
    counts = _script_counts(text)
    latin, kana, han, hangul = (counts[key] for key in ("latin", "kana", "han", "hangul"))
    total = latin + kana + han + hangul
    if total < 2:
        return "unknown", 0.0, False
    active = sum(value / total >= 0.12 for value in (latin, kana + han, hangul) if value)
    mixed = active > 1
    if kana >= 2 and kana + han >= max(2, latin):
        return "ja", round((kana + han) / total, 4), mixed
    if hangul >= 2 and hangul >= max(2, latin):
        return "ko", round(hangul / total, 4), mixed
    if han >= 2 and kana == 0 and han >= latin:
        return "zh", round(han / total, 4), mixed
    if latin >= 2:
        return "en", round(latin / total, 4), mixed
    return "unknown", round(max(latin, kana + han, hangul) / total, 4), mixed


def derive_correction(raw_text: str) -> TextCorrection | None:
    corrected = _compact(raw_text)
    if corrected == raw_text:
        return None
    return TextCorrection(
        raw_text=raw_text,
        corrected_text=corrected,
        correction_reason="whitespace_normalization",
        confidence=0.99,
    )


def _initial_classification(text: str, frequency: int, confidence: float | None) -> tuple[TranscriptSpanClassification, float]:
    compact = _compact(text)
    meaningful = _meaningful(compact)
    if not meaningful or compact in {"-", "--", "...", "…"}:
        return TranscriptSpanClassification.NOISE, 0.99
    if _REACTIONS.match(compact):
        return TranscriptSpanClassification.NON_SPEECH_REACTION, 0.86
    tokens = re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff]+", compact.casefold())
    # Repetition is only a noise signal for tiny ASR tails (for example "me"
    # every three seconds). A complete sentence may be deliberately repeated
    # for emphasis and must remain speech.
    if frequency >= 4 and len(set(tokens)) <= 3 and len(meaningful) < 5:
        return TranscriptSpanClassification.NOISE, 0.88
    if confidence is not None and float(confidence) < 0.16 and len(meaningful) < 5:
        return TranscriptSpanClassification.UNCERTAIN, 0.78
    return TranscriptSpanClassification.SPEECH, 0.82


def analyze_transcript(
    transcript: dict[str, Any],
    *,
    creator_default: str | None = None,
    metadata_language: str | None = None,
    analyzed_at: str | None = None,
) -> tuple[RecordingLanguageProfile, list[TranscriptSpanProfile]]:
    raw_segments = [item for item in transcript.get("segments", []) if str(item.get("text") or "").strip()]
    frequencies = Counter(_compact(str(item.get("text") or "")).casefold() for item in raw_segments)
    working: list[dict[str, Any]] = []
    for item in raw_segments:
        raw = str(item.get("text") or "")
        correction = derive_correction(raw)
        display = correction.corrected_text if correction else raw
        language, confidence, mixed = detect_text_language(display)
        classification, class_confidence = _initial_classification(display, frequencies[_compact(display).casefold()], item.get("confidence"))
        working.append(
            {
                "start_ms": int(round(float(item.get("start", 0)) * 1000)),
                "end_ms": int(round(float(item.get("end", 0)) * 1000)),
                "raw_text": raw,
                "display_text": display,
                "detected_language": language,
                "confidence": confidence,
                "language_source": "transcript_script_profile",
                "mixed": mixed,
                "classification": classification,
                "classification_confidence": class_confidence,
                "correction": correction,
            }
        )

    weighted = Counter()
    for item in working:
        if item["classification"] not in {TranscriptSpanClassification.NOISE, TranscriptSpanClassification.UNCERTAIN}:
            language = item["detected_language"]
            if language != "unknown":
                weighted[language] += max(1, len(_meaningful(item["display_text"])))
    whisper = str(transcript.get("language") or "").casefold()
    if weighted:
        primary, primary_weight = weighted.most_common(1)[0]
        source = "transcript_segments"
    else:
        fallback = next((value for value in (whisper, creator_default, metadata_language) if value and value != "unknown"), "unknown")
        primary, primary_weight, source = fallback, 0, (
            "whisper" if fallback == whisper else "creator_default" if fallback == creator_default else "recording_metadata" if fallback == metadata_language else "fallback_unknown"
        )

    # A sustained minority-language run inside a dominant-language recording is retained but
    # classified as likely background lyrics when it is repetitive or topic-discontinuous.
    index = 0
    while index < len(working):
        item = working[index]
        if item["detected_language"] in {"unknown", primary} or item["classification"] != TranscriptSpanClassification.SPEECH:
            index += 1
            continue
        end = index + 1
        while end < len(working):
            candidate = working[end]
            if candidate["detected_language"] != item["detected_language"] or candidate["start_ms"] - working[end - 1]["end_ms"] > 4_000:
                break
            end += 1
        run = working[index:end]
        duration = run[-1]["end_ms"] - run[0]["start_ms"]
        repeated = sum(frequencies[_compact(entry["display_text"]).casefold()] > 1 for entry in run)
        if len(run) >= 3 and duration >= 8_000 and (repeated or len(run) >= 6):
            for entry in run:
                entry["classification"] = TranscriptSpanClassification.LIKELY_BACKGROUND_LYRICS
                entry["classification_confidence"] = 0.76 if repeated else 0.68
        index = end

    all_language = Counter(item["detected_language"] for item in working if item["detected_language"] != "unknown")
    speech_language = Counter(
        item["detected_language"]
        for item in working
        if item["detected_language"] != "unknown"
        and item["classification"] in {TranscriptSpanClassification.SPEECH, TranscriptSpanClassification.NON_SPEECH_REACTION}
    )

    def distribution(counts: Counter[str]) -> dict[str, float]:
        total = sum(counts.values())
        return {key: round(value / total, 4) for key, value in counts.most_common()} if total else {}

    transcript_distribution = distribution(all_language)
    segment_distribution = distribution(speech_language)
    # Mixed-language describes the recording as heard, including a sustained
    # secondary lyric track. Product speech consumers still use the separate
    # speech-only distribution and span classification.
    secondary = tuple(language for language, share in transcript_distribution.items() if language != primary and share >= 0.03)
    mixed_language = bool(secondary)
    confidence = round(primary_weight / max(1, sum(weighted.values())), 4) if weighted else 0.35 if primary != "unknown" else 0.0
    profile = RecordingLanguageProfile(
        primary_language=primary,
        secondary_languages=secondary,
        mixed_language=mixed_language,
        confidence=confidence,
        source=source,
        transcript_language_distribution=transcript_distribution,
        segment_language_distribution=segment_distribution,
        last_analyzed_at=analyzed_at or datetime.now(timezone.utc).isoformat(),
    )
    return profile, [TranscriptSpanProfile(**item) for item in working]


def derived_metadata(profile: RecordingLanguageProfile, spans: Iterable[TranscriptSpanProfile]) -> dict[str, Any]:
    span_rows = [item.to_dict() for item in spans]
    return {
        "recording_language_profile": profile.to_dict(),
        "transcript_quality": {
            "schema_version": "1.0",
            "raw_transcript_preserved": True,
            "span_count": len(span_rows),
            "classification_counts": dict(Counter(item["classification"] for item in span_rows)),
            "spans": span_rows,
        },
    }


def merge_analysis_metadata(current_json: str, additions: dict[str, Any]) -> str:
    try:
        current = json.loads(current_json or "{}")
    except (json.JSONDecodeError, TypeError):
        current = {}
    current.update(additions)
    return json.dumps(current, ensure_ascii=False, sort_keys=True)
