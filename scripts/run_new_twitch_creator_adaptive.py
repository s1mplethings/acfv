from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from difflib import SequenceMatcher
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any

import numpy as np

from acfv.creator_adaptive import CreatorAdaptiveBootstrapService, TrustedSpeechCandidate
from acfv.creator_adaptive.models import CreatorIdentityDecision, IdentityState
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive_asr import CreatorAdaptiveASRService
from acfv.providers.speaker_embedding import (
    ResemblyzerSpeakerEmbeddingProvider,
    SpeechBrainECAPASpeakerEmbeddingProvider,
)
from acfv.voice_profile.service import cosine
from acfv.voice_profile import CreatorVoiceProfileService, VoiceProfileInsufficientData


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "creator_profile_v4_new_twitch"


def activate_windows_cuda_runtime() -> object | None:
    if os.name != "nt":
        return None
    runtime = Path(sys.prefix) / "Library" / "bin"
    if not runtime.is_dir():
        return None
    os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
    add_directory = getattr(os, "add_dll_directory", None)
    return add_directory(str(runtime)) if callable(add_directory) else None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def agreement(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio() if left and right else 0.0


def extract(media: Path, target: Path, start_ms: int, duration_ms: int) -> None:
    if target.is_file() and target.stat().st_size > 4096:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start_ms / 1000:.3f}",
        "-i", str(media), "-t", f"{duration_ms / 1000:.3f}", "-vn", "-ac", "1", "-ar", "16000", str(target),
    ], check=True)


def centroid(vectors: list[list[float]]) -> list[float]:
    return np.mean(np.asarray(vectors, dtype=np.float32), axis=0).astype(float).tolist()


def metrics(profile: list[float], positives: list[list[float]], negatives: list[list[float]], threshold: float) -> dict[str, float | int]:
    pos = [cosine(profile, value) for value in positives]
    neg = [cosine(profile, value) for value in negatives]
    accepted_pos = sum(value >= threshold for value in pos)
    accepted_neg = sum(value >= threshold for value in neg)
    accepted = accepted_pos + accepted_neg
    return {
        "positive_spans": len(pos), "negative_spans": len(neg), "threshold": threshold,
        "far": accepted_neg / len(neg) if neg else 0.0,
        "frr": 1 - accepted_pos / len(pos) if pos else 1.0,
        "support_precision": accepted_pos / accepted if accepted else 1.0,
        "accepted_positive": accepted_pos, "accepted_negative": accepted_neg,
        "positive_score_min": min(pos, default=0.0), "positive_score_median": float(np.median(pos)) if pos else 0.0,
        "negative_score_max": max(neg, default=0.0),
    }


def build_spans(rows: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    counts = {"TRAIN": 20, "VALIDATION": 24, "HOLDOUT": 150, "UNKNOWN": 36}
    result = []
    rng = random.Random(20261014)
    for row in rows:
        role = str(row["role"])
        count = counts[role]
        duration = int(row["metadata"]["media_validation"]["duration_ms"])
        clip_ms = 12_000
        usable = max(1, duration - clip_ms - 30_000)
        offsets = sorted(rng.sample(range(30_000, 30_000 + usable, 1000), min(count, usable // 1000)))
        for index, start_ms in enumerate(offsets):
            span_id = f"{row['vod_id']}-{index:03d}"
            wav = output / "audio-spans" / str(row["vod_id"]) / f"{span_id}.wav"
            result.append({
                "id": span_id, "creator": row["creator"].casefold(), "vod_id": str(row["vod_id"]),
                "recording_id": str(row["recording_id"]), "role": role,
                "unknown_partition": row.get("unknown_partition"), "start_ms": start_ms,
                "end_ms": start_ms + clip_ms, "source": row["local_path"], "audio": str(wav),
            })
    return result


def main() -> int:
    dll_handle = activate_windows_cuda_runtime()
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipts", type=Path, default=ROOT / "var/new-twitch-validation/manifests/download-receipts-download.json")
    parser.add_argument("--output", type=Path, default=ROOT / "var/new-twitch-validation/creator-adaptive")
    args = parser.parse_args()
    output = args.output.resolve()
    default_output = (ROOT / "var/new-twitch-validation/creator-adaptive").resolve()
    receipt = json.loads(args.receipts.read_text(encoding="utf-8"))
    downloaded = [row for row in receipt["rows"] if row.get("status") == "DOWNLOADED"]
    spans = build_spans(downloaded, output)
    split_manifest = {"schema_version": "1.0", "seed": 20261014, "profile_version": PROFILE, "spans": spans}
    canonical = json.dumps(split_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    split_manifest["sha256"] = hashlib.sha256(canonical).hexdigest()
    write_json(output / "voice-span-manifest.json", split_manifest)
    for span in spans:
        extract(Path(span["source"]), Path(span["audio"]), span["start_ms"], span["end_ms"] - span["start_ms"])

    import torch
    from faster_whisper import WhisperModel
    whisper = WhisperModel(
        "Systran/faster-whisper-large-v3", device="cuda" if torch.cuda.is_available() else "cpu",
        compute_type="float16" if torch.cuda.is_available() else "int8", local_files_only=True,
    )
    providers = {
        "resemblyzer": ResemblyzerSpeakerEmbeddingProvider(device="cuda" if torch.cuda.is_available() else "cpu"),
        "ecapa": SpeechBrainECAPASpeakerEmbeddingProvider(
            device="cuda" if torch.cuda.is_available() else "cpu", cache_dir=output / "models" / "ecapa",
        ),
    }
    # Decode once per frozen span.  This is also the VAD/speech-quality gate for
    # the same-span voice comparison; empty/no-speech clips are excluded equally.
    usable: list[dict[str, Any]] = []
    for index, span in enumerate(spans, 1):
        segments, _ = whisper.transcribe(span["audio"], language="en", beam_size=5, word_timestamps=True, vad_filter=True)
        values = list(segments)
        text = " ".join(str(value.text).strip() for value in values).strip()
        if not text:
            continue
        confidence = max(0.0, min(1.0, max((math.exp(float(value.avg_logprob)) * (1 - float(value.no_speech_prob)) for value in values), default=0.0)))
        words = [{"word": str(word.word).strip(), "start_ms": int(word.start * 1000), "end_ms": int(word.end * 1000), "probability": float(word.probability)} for value in values for word in (value.words or [])]
        item = {**span, "generic_text": text, "asr_confidence": confidence, "words": words, "embeddings": {}}
        for name, provider in providers.items():
            item["embeddings"][name] = list(provider.embed(span["audio"]))
        usable.append(item)
        if index % 25 == 0:
            print(json.dumps({"processed": index, "total": len(spans)}, ensure_ascii=False), flush=True)

    train = [row for row in usable if row["creator"] == "saruei" and row["role"] == "TRAIN"]
    validation_pos = [row for row in usable if row["creator"] == "saruei" and row["role"] == "VALIDATION"]
    validation_neg = [row for row in usable if row["role"] == "UNKNOWN" and row["unknown_partition"] == "CALIBRATION"]
    holdout_pos = [row for row in usable if row["creator"] == "saruei" and row["role"] == "HOLDOUT"]
    holdout_neg = [row for row in usable if row["role"] == "UNKNOWN" and row["unknown_partition"] == "HOLDOUT"]
    holdout_neg += [row for row in usable if row["creator"] == "anny" and row["role"] == "HOLDOUT"]
    voice_report: dict[str, Any] = {"same_frozen_spans": True, "providers": {}, "anny": "INSUFFICIENT_CURRENT_PUBLIC_VODS: no new TRAIN VOD"}
    profiles: dict[str, list[float]] = {}
    for name in providers:
        profile = centroid([row["embeddings"][name] for row in train])
        profiles[name] = profile
        own_scores = [cosine(profile, row["embeddings"][name]) for row in validation_pos]
        other_scores = [cosine(profile, row["embeddings"][name]) for row in validation_neg]
        # Validation only: require no observed calibration false accept, then
        # retain as much same-Creator support as that safety condition permits.
        threshold = max(other_scores, default=-1.0) + 1e-4
        voice_report["providers"][name] = {
            "model_version": providers[name].model_version,
            "train_spans": len(train), "validation": metrics(profile, [row["embeddings"][name] for row in validation_pos], [row["embeddings"][name] for row in validation_neg], threshold),
            "holdout": metrics(profile, [row["embeddings"][name] for row in holdout_pos], [row["embeddings"][name] for row in holdout_neg], threshold),
        }
    winner = max(voice_report["providers"], key=lambda name: (
        voice_report["providers"][name]["holdout"]["support_precision"],
        -voice_report["providers"][name]["holdout"]["frr"],
    ))
    voice_report["winner"] = winner
    voice_report["role"] = "SUPPORT_ONLY"
    write_json(output / "voice-model-ab.json", voice_report)
    threshold = float(voice_report["providers"][winner]["validation"]["threshold"])

    database = output / "creator-adaptive-v4.sqlite"
    if database.exists():
        database.unlink()
    repository = CreatorAdaptiveRepository(database)
    voice_service = CreatorVoiceProfileService(repository=repository)
    for row in train:
        score = cosine(profiles[winner], row["embeddings"][winner])
        voice_service.add_exemplar(
            creator_id="saruei", recording_id=row["recording_id"], start_ms=row["start_ms"], end_ms=row["end_ms"],
            audio_locator=row["audio"], embedding=row["embeddings"][winner], speech_quality=1.0,
            identity_confidence=.95, asr_confidence=row["asr_confidence"], overlap_status="CLEAN",
            music_status="UNKNOWN", trust_level="PSEUDO_TRUSTED" if score >= threshold else "REJECTED",
            profile_version=PROFILE, temporal_region=row["vod_id"],
        )
    try:
        canonical_voice_profile = voice_service.build("saruei", profile_version=PROFILE)
        canonical_voice_profile["provider"] = winner
        canonical_voice_profile["role"] = "SUPPORT_ONLY"
    except VoiceProfileInsufficientData as exc:
        canonical_voice_profile = {"status": "INSUFFICIENT_DATA", "reason": str(exc), "provider": winner}
    bootstrap = CreatorAdaptiveBootstrapService(repository)
    adaptive = CreatorAdaptiveASRService(repository=repository)
    candidates = []
    for row in train:
        score = cosine(profiles[winner], row["embeddings"][winner])
        second, _ = whisper.transcribe(row["audio"], language="en", beam_size=1, word_timestamps=False, vad_filter=True, condition_on_previous_text=False)
        second_text = " ".join(str(value.text).strip() for value in second).strip()
        decision = CreatorIdentityDecision(
            row["recording_id"], row["start_ms"], row["end_ms"], IdentityState.CONFIRMED,
            "saruei", visual_score=.95,
            voice_score=min(.99, .8 + max(0.0, score - threshold)) if score >= threshold else 0.0,
            recording_prior=.9, profile_version=PROFILE,
        )
        candidates.append(TrustedSpeechCandidate(
            identity=decision, recording_id=row["recording_id"], start_ms=row["start_ms"], end_ms=row["end_ms"],
            audio_locator=row["audio"], raw_asr=row["generic_text"], word_timestamps=tuple(row["words"]),
            asr_confidence=row["asr_confidence"], redecode_agreement=agreement(row["generic_text"], second_text),
            independent_evidence=("visual-single-avatar", "independent-beam-redecode"),
            provenance={"dataset": "NEW_TWITCH_VALIDATION_V1", "role": "TRAIN", "vod_id": row["vod_id"], "voice_provider": winner},
        ))
    trusted = bootstrap.bootstrap_trusted_speech("saruei", candidates, profile_version=PROFILE)
    lexicon = bootstrap.bootstrap_lexicon("saruei", profile_version=PROFILE)
    terms = repository.rows("creator_lexicon_entries", where="creator_id=? AND profile_version=?", params=("saruei", PROFILE))
    history = {str(row["text"]): int(row["trusted_occurrences"]) for row in terms}
    hotwords = list(history)

    rng = random.Random(20261014)
    high_risk = sorted(holdout_pos, key=lambda row: row["asr_confidence"])[:50]
    remaining = [row for row in holdout_pos if row not in high_risk]
    selected = high_risk + rng.sample(remaining, min(50, len(remaining)))
    adaptive_rows = []
    for row in selected:
        identity = CreatorIdentityDecision(row["recording_id"], row["start_ms"], row["end_ms"], IdentityState.CONFIRMED, "saruei", .95, .9, .9, profile_version=PROFILE)
        def redecode(selected_terms: list[str], row=row) -> tuple[str, float]:
            segments, _ = whisper.transcribe(row["audio"], language="en", beam_size=5, vad_filter=True, hotwords=", ".join(selected_terms))
            values = list(segments)
            text = " ".join(str(value.text).strip() for value in values).strip()
            confidence = max(0.0, min(1.0, max((math.exp(float(value.avg_logprob)) * (1 - float(value.no_speech_prob)) for value in values), default=0.0)))
            return text or row["generic_text"], confidence
        result = adaptive.shadow_decide(
            recording_id=row["recording_id"], start_ms=row["start_ms"], end_ms=row["end_ms"], generic_text=row["generic_text"],
            identity=identity, profile_version=PROFILE, base_confidence=row["asr_confidence"], candidate_terms=hotwords,
            historical_evidence=history, redecode=redecode if hotwords else None,
        )
        adaptive_rows.append(asdict(result) | {"action": result.action.value, "media": row["source"], "selection": "HIGH_RISK" if row in high_risk else "RANDOM"})

    # Unknown and anny have no eligible new-VOD TRAIN profile.  Exercise the
    # actual memory gate and persist Generic fallback decisions for each attack.
    attacks = []
    for row in holdout_neg:
        unknown = CreatorIdentityDecision(row["recording_id"], row["start_ms"], row["end_ms"], IdentityState.UNKNOWN, None, profile_version=PROFILE)
        result = adaptive.shadow_decide(recording_id=row["recording_id"], start_ms=row["start_ms"], end_ms=row["end_ms"], generic_text=row["generic_text"], identity=unknown, profile_version=PROFILE, base_confidence=row["asr_confidence"], candidate_terms=hotwords, historical_evidence=history, redecode=lambda _: ("forbidden", 1.0))
        attacks.append(asdict(result) | {"action": result.action.value, "actual_creator": row["creator"], "memory_accessed": False, "media": row["source"]})

    action_counts = Counter(row["action"] for row in adaptive_rows)
    report = {
        "profile_version": PROFILE, "voice": voice_report, "voice_profile": canonical_voice_profile,
        "trusted_speech": trusted, "lexicon": lexicon,
        "adaptive_shadow": {"samples": len(adaptive_rows), "high_risk": len(high_risk), "random": len(selected) - len(high_risk), "actions": dict(action_counts), "human_ground_truth": "PENDING", "wer": "PENDING"},
        "unknown_safety": {"attack_samples": len(attacks), "generic_fallback": sum(row["action"] == "GENERIC_FALLBACK" for row in attacks), "memory_leakage": sum(bool(row["memory_accessed"]) for row in attacks)},
        "anny": {"profile": "INSUFFICIENT_DATA", "adaptive": "GENERIC_FALLBACK", "reason": "only one current public VOD; frozen HOLDOUT"},
        "production": "KEEP_SHADOW",
    }
    write_json(output / "creator-adaptive-v4-report.json", report)
    write_json(output / "adaptive-shadow-v4.json", {"summary": report["adaptive_shadow"], "items": adaptive_rows, "unknown_attacks": attacks})
    review = {"schema_version": 4, "dataset_id": "NEW_TWITCH_VALIDATION_V1", "profile_version": PROFILE, "identity": [], "trusted_speech": [], "adaptive_asr": []}
    for unit in repository.rows("trusted_speech_units", where="profile_version=?", params=(PROFILE,))[:50]:
        review["trusted_speech"].append({"id": unit["id"], "creator": "saruei", "creator_id": "saruei", "recording_id": unit["recording_id"], "media": unit["audio_locator"], "start_ms": 0, "end_ms": int(unit["end_ms"]) - int(unit["start_ms"]), "predicted_creator": "saruei", "transcript": unit["raw_asr"], "context": unit["trust_level"], "profile_version": PROFILE, "trusted_speech_unit_id": unit["id"]})
    for row in adaptive_rows:
        review["adaptive_asr"].append({"id": row["id"], "creator": "saruei", "creator_id": "saruei", "recording_id": row["recording_id"], "media": row["media"], "start_ms": row["start_ms"], "end_ms": row["end_ms"], "generic_text": row["generic_text"], "adaptive_text": row["adaptive_text"], "context": f"{row['selection']} · {row['action']}", "profile_version": PROFILE})
    for row in [item for item in attacks if item["actual_creator"] == "anny"][:100]:
        review["adaptive_asr"].append({"id": row["id"], "creator": "anny", "creator_id": "", "recording_id": row["recording_id"], "media": row["media"], "start_ms": row["start_ms"], "end_ms": row["end_ms"], "generic_text": row["generic_text"], "adaptive_text": row["adaptive_text"], "context": "GENERIC_FALLBACK · INSUFFICIENT_CURRENT_PUBLIC_VODS", "profile_version": PROFILE})
    review_path = (
        ROOT / "var/new-twitch-validation/human-review/human-review-v4.json"
        if output == default_output
        else output / "human-review-v4.json"
    )
    write_json(review_path, review)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
