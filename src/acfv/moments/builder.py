from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable


def _milliseconds(value: Any) -> int:
    return int(round(float(value) * 1000))


@dataclass(frozen=True)
class MomentDraft:
    start_ms: int
    end_ms: int
    transcript_text: str
    chat_text: str
    evidence_json: str


class ProvisionalMomentBuilder:
    def __init__(self, *, preferred_min_ms: int = 20_000, soft_max_ms: int = 90_000, hard_max_ms: int = 120_000, max_gap_ms: int = 8_000) -> None:
        self.preferred_min_ms = preferred_min_ms
        self.soft_max_ms = soft_max_ms
        self.hard_max_ms = hard_max_ms
        self.max_gap_ms = max_gap_ms

    def build(
        self,
        transcript_payload: dict[str, Any],
        chat_payload: dict[str, Any] | None = None,
        *,
        transcript_artifact: str | None = None,
        chat_artifact: str | None = None,
        suppress_low_information: bool = True,
    ) -> list[MomentDraft]:
        segments = [self._normalize_segment(item) for item in transcript_payload.get("segments", [])]
        segments = [item for item in segments if item is not None]
        # Derive language/source metadata from the immutable raw transcript.
        # Product text may use a high-confidence display correction, but the
        # original text remains attached to each evidence unit.
        from acfv.library.transcript_quality import analyze_transcript

        _, profiles = analyze_transcript(transcript_payload)
        for segment, profile in zip(segments, profiles):
            segment["raw_text"] = profile.raw_text
            segment["text"] = profile.display_text
            segment["detected_language"] = profile.detected_language
            segment["language_confidence"] = profile.confidence
            segment["classification"] = profile.classification.value
            segment["classification_confidence"] = profile.classification_confidence
            segment["correction"] = profile.correction
        groups: list[list[dict[str, Any]]] = []
        for segment in segments:
            if not groups or self._starts_new_group(groups[-1], segment):
                groups.append([segment])
            else:
                groups[-1].append(segment)
        records = (chat_payload or {}).get("records", [])
        if suppress_low_information:
            groups = self._merge_low_information(groups, records)
        return [self._draft(group, records, transcript_artifact, chat_artifact) for group in groups]

    def _normalize_segment(self, segment: dict[str, Any]) -> dict[str, Any] | None:
        text = str(segment.get("text") or "").strip()
        if not text:
            return None
        start_ms = _milliseconds(segment["start"])
        end_ms = _milliseconds(segment["end"])
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("Transcript segment must have a positive time range")
        return {"start_ms": start_ms, "end_ms": end_ms, "text": text, "confidence": segment.get("confidence")}

    def _starts_new_group(self, group: list[dict[str, Any]], segment: dict[str, Any]) -> bool:
        gap = segment["start_ms"] - group[-1]["end_ms"]
        duration = segment["end_ms"] - group[0]["start_ms"]
        if gap > self.max_gap_ms or duration > self.hard_max_ms:
            return True
        if duration <= self.preferred_min_ms:
            return False
        previous_text = group[-1]["text"].strip()
        sentence_end = bool(re.search(r"[.!?。！？][\"']?$", previous_text))
        if duration > self.soft_max_ms and (sentence_end or gap >= 500):
            return True
        if gap >= 1_500 and sentence_end:
            return True
        return self._topic_shift(group, segment) and sentence_end and len(group) >= 3

    @staticmethod
    def _topic_shift(group: list[dict[str, Any]], segment: dict[str, Any]) -> bool:
        recent = " ".join(item["text"] for item in group[-3:]).casefold()
        incoming = segment["text"].casefold()
        left = set(re.findall(r"[a-z0-9]{3,}|[\u3400-\u9fff]{2,}", recent))
        right = set(re.findall(r"[a-z0-9]{3,}|[\u3400-\u9fff]{2,}", incoming))
        return bool(left and right) and len(left & right) / max(1, min(len(left), len(right))) < 0.08

    def _merge_low_information(self, groups: list[list[dict[str, Any]]], records: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        records = list(records)
        merged: list[list[dict[str, Any]]] = []
        for index, group in enumerate(groups):
            group = [
                item
                for item in group
                if str(item.get("classification") or "SPEECH")
                not in {"LIKELY_BACKGROUND_LYRICS", "NOISE", "UNCERTAIN"}
                or any(
                    item["start_ms"] <= _milliseconds(record.get("timestamp", -1)) <= item["end_ms"]
                    and str(record.get("message") or "").strip()
                    for record in records
                )
            ]
            if not group:
                continue
            text = " ".join(item["text"] for item in group).strip()
            start_ms, end_ms = group[0]["start_ms"], group[-1]["end_ms"]
            chat_signal = any(start_ms <= _milliseconds(item.get("timestamp", -1)) <= end_ms and str(item.get("message") or "").strip() for item in records)
            classifications = {str(item.get("classification") or "SPEECH") for item in group}
            if classifications <= {"LIKELY_BACKGROUND_LYRICS", "NOISE", "UNCERTAIN"} and not chat_signal:
                continue
            if self._low_information(text) and not chat_signal:
                if merged and start_ms - merged[-1][-1]["end_ms"] <= self.max_gap_ms:
                    merged[-1].extend(group)
                    continue
                if index + 1 < len(groups) and groups[index + 1][0]["start_ms"] - end_ms <= self.max_gap_ms:
                    groups[index + 1] = group + groups[index + 1]
                    continue
                # Preserve isolated speech as supporting evidence here. The
                # final quality pass can suppress it with surrounding event
                # context; the streaming builder must not erase a real short
                # utterance before that context exists.
            merged.append(group)
        return merged

    @staticmethod
    def _low_information(text: str) -> bool:
        meaningful = "".join(char for char in text if unicodedata.category(char)[0] in {"L", "N"})
        if not meaningful:
            return True
        words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]|[\u3040-\u30ff]+", text.casefold())
        reaction = bool(re.fullmatch(
            r"(?:oh+|ah+|wow+|whoa+|no+|yes+|what+|huh+|ha(?:ha)+|lmao+|lol+|scream(?:ing)?|laugh(?:ing)?)[!?！。\s]*",
            text.strip(),
            flags=re.IGNORECASE,
        ))
        if reaction:
            return False
        return len(words) < 4 or (len(set(words)) <= 1 and len(words) > 1)

    def _draft(self, group: list[dict[str, Any]], records: Iterable[dict[str, Any]], transcript_artifact: str | None, chat_artifact: str | None) -> MomentDraft:
        start_ms, end_ms = group[0]["start_ms"], group[-1]["end_ms"]
        transcript_text = " ".join(item["text"] for item in group)
        chat = []
        for record in records:
            timestamp_ms = _milliseconds(record.get("timestamp", -1))
            message = str(record.get("message") or "").strip()
            if start_ms <= timestamp_ms <= end_ms and message:
                chat.append({"timestamp_ms": timestamp_ms, "text": message})
        evidence = [
            {
                "type": "transcript",
                "start_ms": item["start_ms"],
                "end_ms": item["end_ms"],
                "text": item["text"],
                "raw_text": item.get("raw_text", item["text"]),
                "confidence": item["confidence"],
                "artifact": transcript_artifact,
                "detected_language": item.get("detected_language", "unknown"),
                "language_confidence": item.get("language_confidence", 0.0),
                "classification": item.get("classification", "SPEECH"),
                "classification_confidence": item.get("classification_confidence", 0.0),
                "correction": (
                    {
                        "raw_text": item["correction"].raw_text,
                        "corrected_text": item["correction"].corrected_text,
                        "correction_reason": item["correction"].correction_reason,
                        "confidence": item["correction"].confidence,
                        "correction_provider": item["correction"].correction_provider,
                        "version": item["correction"].version,
                    }
                    if item.get("correction") is not None
                    else None
                ),
            }
            for item in group
        ]
        evidence.extend({"type": "chat", "start_ms": item["timestamp_ms"], "end_ms": item["timestamp_ms"], "text": item["text"], "confidence": None, "artifact": chat_artifact} for item in chat)
        return MomentDraft(start_ms=start_ms, end_ms=end_ms, transcript_text=transcript_text, chat_text=" ".join(item["text"] for item in chat), evidence_json=json.dumps(evidence, ensure_ascii=False))
