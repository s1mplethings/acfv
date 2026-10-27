"""Bounded real-library validation for creator-adaptive identity and voice profiles.

This script reads existing 10-minute proxy audio/transcripts, never raw media, and
writes only to ``var/creator-adaptive-validation`` plus promoted JSON evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import median
import time
from typing import Any

from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.providers.avatar_identity import ExistingAvatarModelAdapter
from acfv.providers.speaker_embedding import ResemblyzerSpeakerEmbeddingProvider
from acfv.voice_profile import CreatorVoiceProfileService
from acfv.voice_profile.service import cosine


@dataclass(frozen=True)
class Source:
    creator: str
    creator_id: str
    recording_id: str
    run_root: Path
    role: str

    @property
    def transcript(self) -> Path:
        return self.run_root / "work" / "transcript_merged.json"

    @property
    def audio(self) -> Path:
        return next((self.run_root / "work" / "audio").glob("*.wav"))


def _sources(root: Path) -> list[Source]:
    current = root / "acfv-current-machine-validation" / "processing" / "runs"
    scale = root / "acfv-large-scale-generation-quality" / "processing" / "runs"
    legacy = root / "real_library_build_20261007" / "runs"
    return [
        Source("Saruei", "763d6db5-d95b-4634-84bb-b1ef0a998883", "90e4d92d-8552-423c-bb06-4963753f6b33", scale / "90e4d92d-8552-423c-bb06-4963753f6b33", "profile"),
        Source("Saruei", "763d6db5-d95b-4634-84bb-b1ef0a998883", "63f73d16-8d64-4cee-8b0d-a1375c4ba21c", scale / "63f73d16-8d64-4cee-8b0d-a1375c4ba21c", "profile"),
        Source("Saruei", "763d6db5-d95b-4634-84bb-b1ef0a998883", "2a407bf2-05bd-40a9-b5e7-d164ac475d76", current / "2a407bf2-05bd-40a9-b5e7-d164ac475d76", "holdout"),
        Source("Saruei", "763d6db5-d95b-4634-84bb-b1ef0a998883", "0a01c6ab-65ae-4c47-a5a4-02bdd7029540", legacy / "0a01c6ab-65ae-4c47-a5a4-02bdd7029540", "holdout"),
        Source("Saruei", "763d6db5-d95b-4634-84bb-b1ef0a998883", "121a99a3-affb-4e74-80de-c5fd13ed7c4b", legacy / "121a99a3-affb-4e74-80de-c5fd13ed7c4b", "holdout"),
        Source("anny", "a8f4bf07-88bc-40aa-bf38-989c4eab6396", "424492b1-8773-4a77-b8a4-939fd0860f3a", current / "424492b1-8773-4a77-b8a4-939fd0860f3a", "profile"),
        Source("anny", "a8f4bf07-88bc-40aa-bf38-989c4eab6396", "9b6a3bd6-c08e-48c5-829d-b0d093ef2704", scale / "9b6a3bd6-c08e-48c5-829d-b0d093ef2704", "profile"),
        Source("anny", "a8f4bf07-88bc-40aa-bf38-989c4eab6396", "4b17a951-b73d-4c23-a684-035ef855994a", scale / "4b17a951-b73d-4c23-a684-035ef855994a", "holdout"),
        Source("anny", "a8f4bf07-88bc-40aa-bf38-989c4eab6396", "49169f8b-ab49-4868-b540-6c7b521962f6", current / "49169f8b-ab49-4868-b540-6c7b521962f6", "holdout"),
    ]


def _windows(source: Source, limit: int, *, minimum_spacing: float = 3.6) -> list[dict[str, Any]]:
    payload = json.loads(source.transcript.read_text(encoding="utf-8-sig"))
    segments = payload.get("segments", [])
    candidates: list[dict[str, Any]] = []
    last = -minimum_spacing
    for segment in segments:
        words = segment.get("words") or []
        strong = [word for word in words if float(word.get("probability", 0)) >= 0.82]
        if len(strong) < 3:
            continue
        for word in strong:
            center = float(word["start"])
            if center - last < minimum_spacing:
                continue
            start = max(0.0, center - 1.25)
            end = min(601.0, start + 3.5)
            candidates.append({
                "start_ms": round(start * 1000), "end_ms": round(end * 1000),
                "asr_confidence": sum(float(value.get("probability", 0)) for value in strong) / len(strong),
                "text": str(segment.get("text", "")).strip(),
            })
            last = center
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    if not candidates:
        last = -minimum_spacing
        for segment in segments:
            start_value, end_value = float(segment.get("start", 0)), float(segment.get("end", 0))
            if end_value - start_value < .8 or not str(segment.get("text", "")).strip():
                continue
            center = (start_value + end_value) / 2
            if center - last < minimum_spacing:
                continue
            start = max(0.0, center - 1.25)
            candidates.append({
                "start_ms": round(start * 1000), "end_ms": round(min(start + 3.5, end_value) * 1000),
                "asr_confidence": float(segment.get("confidence", 0)), "text": str(segment.get("text", "")).strip(),
            })
            last = center
            if len(candidates) >= limit:
                break
    return candidates


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    def pct(value: float) -> float:
        return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * value))]
    return {"min": ordered[0], "p10": pct(.1), "median": median(ordered), "p90": pct(.9), "max": ordered[-1]}


def run(root: Path, output: Path) -> dict[str, Any]:
    sources = _sources(root)
    missing = [str(path) for source in sources for path in (source.audio, source.transcript) if not path.is_file()]
    if missing:
        raise FileNotFoundError("\n".join(missing))
    output.mkdir(parents=True, exist_ok=True)
    repository = CreatorAdaptiveRepository(output / "creator_adaptive_validation.sqlite")
    voice = CreatorVoiceProfileService(repository=repository)
    provider = ResemblyzerSpeakerEmbeddingProvider(device="cuda")
    embed_times: list[float] = []
    profiles: dict[str, dict[str, Any]] = {}
    holdout: dict[str, list[list[float]]] = {"Saruei": [], "anny": []}
    holdout_items: list[tuple[Source, dict[str, Any], list[float]]] = []
    source_receipts: list[dict[str, Any]] = []

    for source in sources:
        wanted = 10 if source.role == "profile" else 100
        windows = _windows(source, wanted)
        vectors: list[list[float]] = []
        accepted: list[dict[str, Any]] = []
        for item in windows:
            started = time.perf_counter()
            try:
                vector = list(provider.embed(source.audio, start_ms=item["start_ms"], end_ms=item["end_ms"]))
            except (ValueError, RuntimeError):
                continue
            embed_times.append((time.perf_counter() - started) * 1000)
            vectors.append(vector); accepted.append(item)
        source_receipts.append({
            "creator": source.creator, "recording_id": source.recording_id, "role": source.role,
            "candidate_windows": len(windows), "embedded": len(vectors),
            "audio": str(source.audio), "transcript": str(source.transcript),
        })
        if source.role == "profile":
            for index, (item, vector) in enumerate(zip(accepted, vectors)):
                voice.add_exemplar(
                    creator_id=source.creator_id, recording_id=source.recording_id,
                    start_ms=item["start_ms"], end_ms=item["end_ms"], audio_locator=str(source.audio),
                    embedding=vector, speech_quality=item["asr_confidence"], identity_confidence=.75,
                    asr_confidence=item["asr_confidence"], overlap_status="NOT_EVALUATED",
                    music_status="NOT_EVALUATED", trust_level="PSEUDO_TRUSTED",
                    profile_version="creator_profile_v1", temporal_region=f"{source.recording_id}:{index // 5}",
                )
        else:
            holdout[source.creator].extend(vectors)
            holdout_items.extend((source, item, vector) for item, vector in zip(accepted, vectors))

    for creator in ("Saruei", "anny"):
        creator_id = next(source.creator_id for source in sources if source.creator == creator)
        profiles[creator] = voice.build(creator_id, profile_version="creator_profile_v1")

    evaluation: dict[str, Any] = {}
    for creator, other in (("Saruei", "anny"), ("anny", "Saruei")):
        positive = [cosine(vector, profiles[creator]["centroid"]) for vector in holdout[creator]]
        negative = [cosine(vector, profiles[creator]["centroid"]) for vector in holdout[other]]
        calibration_positive, test_positive = positive[:50], positive[50:]
        calibration_negative, test_negative = negative[:50], negative[50:]
        threshold = (median(calibration_positive) + median(calibration_negative)) / 2
        evaluation[creator] = {
            "positive_segments": len(positive), "negative_segments": len(negative),
            "calibration_segments": len(calibration_positive) + len(calibration_negative),
            "test_positive_segments": len(test_positive), "test_negative_segments": len(test_negative),
            "threshold": threshold, "threshold_kind": "heldout_midpoint_not_probability",
            "positive_scores": _distribution(positive), "negative_scores": _distribution(negative),
            "false_reject_rate": sum(score < threshold for score in test_positive) / max(1, len(test_positive)),
            "false_accept_rate": sum(score >= threshold for score in test_negative) / max(1, len(test_negative)),
        }

    avatar = ExistingAvatarModelAdapter().audit()
    identity_review = []
    for source, item, vector in holdout_items:
        scores = {name: cosine(vector, profile["centroid"]) for name, profile in profiles.items()}
        ranked = sorted(scores, key=scores.get, reverse=True)
        identity_review.append({
            "id": f"{source.recording_id}:{item['start_ms']}", "creator": source.creator,
            "creator_id": source.creator_id, "recording_id": source.recording_id,
            "media": str(source.audio), "start_ms": item["start_ms"], "end_ms": item["end_ms"],
            "predicted_creator": ranked[0], "voice_score": scores[ranked[0]],
            "second_voice_score": scores[ranked[1]], "visual_score": None,
            "context": item["text"], "profile_version": "creator_profile_v1",
            "priority": 0 if ranked[0] != source.creator else abs(scores[ranked[0]] - scores[ranked[1]]),
        })
    identity_review.sort(key=lambda item: item["priority"])
    review_payload = {
        "dataset_version": "creator-adaptive-review-v2", "identity": identity_review[:100],
        "adaptive_asr": [],
        "limitations": ["Adaptive ASR items are empty because no safe visual+voice identity and no human ASR truth are available."],
    }
    result = {
        "status": "PASS_WITH_LIMITATIONS", "profile_version": "creator_profile_v1",
        "avatar_provider": avatar, "speaker_provider": {
            "name": "resemblyzer", "version": "0.1.4", "license": "Apache-2.0",
            "platform": "Windows", "device": "NVIDIA GeForce RTX 4050 Laptop GPU",
            "lexical_evidence_supported": False,
        },
        "sources": source_receipts,
        "profiles": {name: {key: value for key, value in profile.items() if key not in {"centroid", "medoid"}} for name, profile in profiles.items()},
        "evaluation": evaluation,
        "performance": {
            "embedding_samples": len(embed_times), "mean_ms": sum(embed_times) / len(embed_times),
            "p95_ms": sorted(embed_times)[math.floor(.95 * (len(embed_times) - 1))],
        },
        "limitations": [
            "Existing avatar model path was not configured; visual inference is NOT_EVALUATED.",
            "Voice bootstrap uses known Recording ownership plus high-confidence ASR windows because visual bootstrap is unavailable.",
            "Overlap and music status are NOT_EVALUATED; scores are engineering evidence, not production accuracy.",
            "No human speaker labels exist for these windows; production speaker attribution remains NO.",
        ],
    }
    (output / "voice-profile-real-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "creator-adaptive-review-v2.json").write_text(json.dumps(review_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library-root", type=Path, default=Path("F:/ACFV-Derived"))
    parser.add_argument("--output", type=Path, default=Path("var/creator-adaptive-validation"))
    args = parser.parse_args()
    # Keep CLI output safe on Windows shells whose default encoding is GBK.
    print(json.dumps(run(args.library_root, args.output), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
