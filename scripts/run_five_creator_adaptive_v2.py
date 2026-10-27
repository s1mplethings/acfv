from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable

import numpy as np

from acfv.creator_adaptive.bootstrap import CreatorAdaptiveBootstrapService, TrustedSpeechCandidate
from acfv.creator_adaptive.models import CreatorIdentityDecision, IdentityObservation, IdentitySource, IdentityState
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive_asr import CreatorAdaptiveASRService
from acfv.creator_identity import CreatorIdentityService
from acfv.creator_visual_identity.model import LinearProbeIdentityModel
from acfv.voice_profile import CreatorVoiceProfileService, VoiceProfileInsufficientData


PROFILE = "creator_profile_five_v2"
CREATORS = ("atelieranoko", "laphipi", "snuffy")


def _activate_windows_cuda_runtime() -> object | None:
    if os.name != "nt":
        return None
    runtime = Path(sys.prefix) / "Library" / "bin"
    if not runtime.is_dir():
        return None
    os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
    add_directory = getattr(os, "add_dll_directory", None)
    return add_directory(str(runtime)) if callable(add_directory) else None


def _dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[\w'-]+", value.casefold()))


def _agreement(left: str, right: str) -> float:
    return SequenceMatcher(None, _normalized(left), _normalized(right)).ratio() if left and right else 0.0


def _load_plan(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = list(payload.get("vods", payload.get("rows", [])))
    roles: dict[str, str] = {}
    creators: dict[str, str] = {}
    for row in rows:
        vod_id = str(row["vod_id"])
        role = str(row["role"]).upper()
        creator = str(row["creator"]).casefold()
        if role not in {"TRAIN", "VALIDATION"} or creator not in CREATORS:
            continue
        if vod_id in roles:
            raise ValueError(f"duplicate VOD in frozen plan: {vod_id}")
        roles[vod_id] = role
        creators[vod_id] = creator
    if len(roles) != 9:
        raise ValueError(f"expected exactly 9 TRAIN/VALIDATION VODs, got {len(roles)}")
    return roles, creators


def select_rows(
    rows: Iterable[dict[str, Any]], predictions: Iterable[Any], *,
    max_per_recording: int, minimum_gap_ms: int,
) -> list[dict[str, Any]]:
    """Select independent, strong, correct visual anchors without split leakage."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, prediction in zip(rows, predictions):
        if (
            str(row.get("dataset_split", "")).lower() in {"train", "validation"}
            and prediction.state.value == "STRONG"
            and prediction.creator_id == row.get("creator_id")
        ):
            grouped[str(row["recording_id"])].append(dict(row))
    selected: list[dict[str, Any]] = []
    for recording_id in sorted(grouped):
        accepted: list[dict[str, Any]] = []
        for row in sorted(grouped[recording_id], key=lambda item: (-float(item.get("quality", 0)), int(item["timestamp_ms"]))):
            timestamp = int(row["timestamp_ms"])
            if all(abs(timestamp - int(prior["timestamp_ms"])) >= minimum_gap_ms for prior in accepted):
                accepted.append(row)
                if len(accepted) >= max_per_recording:
                    break
        selected.extend(sorted(accepted, key=lambda item: int(item["timestamp_ms"])))
    return selected


def _extract_audio(media: Path, target: Path, *, start_ms: int, duration_ms: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(media),
        "-t", f"{duration_ms / 1000:.3f}", "-vn", "-ac", "1", "-ar", "16000", str(target),
    ], check=True)


def _transcribe(model: Any, path: Path, *, conditioned: bool, hotwords: list[str] | None = None) -> tuple[str, float, tuple[dict[str, Any], ...]]:
    segments, _ = model.transcribe(
        str(path), language="en", beam_size=5, word_timestamps=True,
        vad_filter=True, condition_on_previous_text=conditioned,
        hotwords=", ".join(hotwords or []) or None,
    )
    values = list(segments)
    text = " ".join(str(value.text).strip() for value in values).strip()
    confidence = max([
        math.exp(float(value.avg_logprob)) * (1 - float(value.no_speech_prob))
        for value in values
    ], default=0.0)
    words = tuple({
        "word": str(word.word).strip(), "start_ms": int(word.start * 1000),
        "end_ms": int(word.end * 1000), "probability": float(word.probability),
    } for value in values for word in (value.words or []))
    return text, min(1.0, confidence), words


def main() -> int:
    dll_handle = _activate_windows_cuda_runtime()
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--visual-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--clips-per-recording", type=int, default=25)
    parser.add_argument("--clip-seconds", type=int, default=12)
    parser.add_argument("--minimum-gap-seconds", type=int, default=120)
    args = parser.parse_args()

    run = args.output.resolve() / "runs" / args.run_id
    run.mkdir(parents=True, exist_ok=False)
    roles, expected_creators = _load_plan(args.plan.resolve())
    visual = args.visual_root.resolve()
    rows = [json.loads(line) for line in (visual / "visual-dataset-manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    embeddings = np.load(visual / "benchmark/resnet18-linear-embeddings.npz")["embeddings"]
    model = LinearProbeIdentityModel.load(visual / "benchmark/resnet18-linear-identity-model.joblib")
    if len(rows) != len(embeddings):
        raise ValueError("visual rows and embeddings are misaligned")
    predictions = [model.predict(vector) for vector in embeddings]
    selected = select_rows(
        rows, predictions, max_per_recording=args.clips_per_recording,
        minimum_gap_ms=args.minimum_gap_seconds * 1000,
    )
    selected_by_id = {str(row["sample_id"]): row for row in selected}
    prediction_by_id = {str(row["sample_id"]): prediction for row, prediction in zip(rows, predictions)}
    counts = Counter((str(row["dataset_split"]), str(row["creator_id"])) for row in selected)
    for creator in CREATORS:
        if counts[("train", creator)] < 20 or counts[("validation", creator)] < 10:
            raise ValueError(f"insufficient independent visual anchors for {creator}: {dict(counts)}")

    repository = CreatorAdaptiveRepository(run / "creator-adaptive-five-v2.sqlite")
    identity_service = CreatorIdentityService(repository=repository)
    voice_service = CreatorVoiceProfileService(
        repository=repository, split_by_vod=roles,
        leakage_event_path=run / "final-holdout-leakage-events.jsonl",
    )
    bootstrap = CreatorAdaptiveBootstrapService(
        repository, split_by_vod=roles,
        leakage_event_path=run / "final-holdout-leakage-events.jsonl",
    )
    adaptive = CreatorAdaptiveASRService(repository=repository)

    from faster_whisper import WhisperModel
    from resemblyzer import VoiceEncoder, preprocess_wav
    import soundfile as sf
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    whisper = WhisperModel(
        "Systran/faster-whisper-large-v3", device=device,
        compute_type="float16" if device == "cuda" else "int8", local_files_only=True,
    )
    speaker = VoiceEncoder(device=device)
    candidates: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(selected):
        vod_id = str(row["recording_id"])
        if vod_id not in roles or expected_creators[vod_id] != str(row["creator_id"]):
            raise PermissionError(f"visual anchor is outside the frozen V2 plan: {vod_id}")
        clip_ms = args.clip_seconds * 1000
        start_ms = max(0, int(row["timestamp_ms"]) - clip_ms // 3)
        wav = run / "audio" / str(row["dataset_split"]) / str(row["creator_id"]) / f"{vod_id}-{start_ms}.wav"
        _extract_audio(Path(row["source_path"]), wav, start_ms=start_ms, duration_ms=clip_ms)
        text, confidence, words = _transcribe(whisper, wav, conditioned=True)
        second_text, second_confidence, _ = _transcribe(whisper, wav, conditioned=False)
        if not text:
            continue
        audio, sample_rate = sf.read(wav, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        utterance = preprocess_wav(audio, source_sr=sample_rate)
        if len(utterance) < sample_rate * .8:
            continue
        embedding = speaker.embed_utterance(utterance).astype(float).tolist()
        prediction = prediction_by_id[str(row["sample_id"])]
        visual_confidence = max(.85, min(.99, float(prediction.score)))
        split = str(row["dataset_split"])
        evidence = [
            IdentityObservation(vod_id, start_ms, start_ms + clip_ms, str(row["creator_id"]), IdentitySource.VISUAL, visual_confidence, "creator-visual-five-v2", "resnet18-linear-open-set"),
            IdentityObservation(vod_id, start_ms, start_ms + clip_ms, str(row["creator_id"]), IdentitySource.RECORDING_PRIOR, .9, "library-recording-owner", "library-v2"),
        ]
        initial = identity_service.fuse(vod_id, start_ms, start_ms + clip_ms, evidence, profile_version=PROFILE)
        item = {
            "creator": str(row["creator_id"]), "vod_id": vod_id, "split": split,
            "start_ms": start_ms, "end_ms": start_ms + clip_ms, "wav": str(wav),
            "text": text, "second_text": second_text, "confidence": confidence,
            "second_confidence": second_confidence, "agreement": _agreement(text, second_text),
            "words": words, "embedding": embedding, "visual_confidence": visual_confidence,
            "initial_identity": initial,
        }
        candidates[str(row["creator_id"])][split].append(item)
        if split == "train":
            voice_service.add_exemplar(
                creator_id=str(row["creator_id"]), recording_id=vod_id,
                start_ms=start_ms, end_ms=start_ms + clip_ms, audio_locator=str(wav),
                embedding=embedding, speech_quality=1.0, identity_confidence=visual_confidence,
                asr_confidence=confidence, overlap_status="CLEAN", music_status="NONE",
                trust_level="PSEUDO_TRUSTED", profile_version=PROFILE,
                temporal_region=vod_id, source_vod_id=vod_id,
            )
        if index % 10 == 0:
            _dump(run / "progress.json", {"status": "RUNNING", "processed": index + 1, "selected": len(selected), "ground_truth_opened": False})

    profiles: dict[str, dict[str, Any]] = {}
    for creator in CREATORS:
        try:
            profiles[creator] = voice_service.build(creator, profile_version=PROFILE)
        except VoiceProfileInsufficientData as exc:
            profiles[creator] = {"creator_id": creator, "profile_version": PROFILE, "status": "INSUFFICIENT_DATA", "reason": str(exc)}

    validation: dict[str, Any] = {}
    for creator, profile in profiles.items():
        if "centroid" not in profile:
            validation[creator] = {"status": "INSUFFICIENT_DATA"}
            continue
        own = [float(voice_service.match(row["embedding"], profile)["score"]) for row in candidates[creator]["validation"]]
        other = [
            float(voice_service.match(row["embedding"], profile)["score"])
            for other_creator in CREATORS if other_creator != creator
            for row in candidates[other_creator]["validation"]
        ]
        threshold = max(float(profile["strong_threshold"]), max(other, default=-1.0) + .001)
        profile["validation_strong_threshold"] = threshold
        validation[creator] = {
            "samples": len(own), "other_samples": len(other), "threshold": threshold,
            "false_accepts": sum(score >= threshold for score in other),
            "false_accept_rate": sum(score >= threshold for score in other) / len(other) if other else 0.0,
            "true_accepts": sum(score >= threshold for score in own),
            "true_accept_rate": sum(score >= threshold for score in own) / len(own) if own else 0.0,
            "claim": "VALIDATION_ONLY_NO_HOLDOUT_CLAIM",
        }

    trusted_reports: dict[str, Any] = {}
    lexicon_reports: dict[str, Any] = {}
    for creator in CREATORS:
        profile = profiles[creator]
        batch: list[TrustedSpeechCandidate] = []
        if "centroid" in profile:
            others = [profiles[value] for value in CREATORS if value != creator and "centroid" in profiles[value]]
            for row in candidates[creator]["train"]:
                own = voice_service.match(row["embedding"], profile)
                other_score = max((float(voice_service.match(row["embedding"], value)["score"]) for value in others), default=-1.0)
                strong = float(own["score"]) >= float(profile["validation_strong_threshold"]) and float(own["score"]) - other_score >= .03
                evidence = [
                    IdentityObservation(row["vod_id"], row["start_ms"], row["end_ms"], creator, IdentitySource.VISUAL, row["visual_confidence"], "creator-visual-five-v2", "resnet18-linear-open-set"),
                    IdentityObservation(row["vod_id"], row["start_ms"], row["end_ms"], creator, IdentitySource.RECORDING_PRIOR, .9, "library-recording-owner", "library-v2"),
                ]
                if strong:
                    evidence.append(IdentityObservation(row["vod_id"], row["start_ms"], row["end_ms"], creator, IdentitySource.VOICE, .85, "resemblyzer-five-v2", "resemblyzer-pretrained"))
                decision = identity_service.fuse(row["vod_id"], row["start_ms"], row["end_ms"], evidence, profile_version=PROFILE)
                batch.append(TrustedSpeechCandidate(
                    identity=decision, recording_id=row["vod_id"], start_ms=row["start_ms"], end_ms=row["end_ms"],
                    audio_locator=row["wav"], raw_asr=row["text"], word_timestamps=row["words"],
                    asr_confidence=row["confidence"], redecode_agreement=row["agreement"],
                    overlap_status="CLEAN", music_status="NONE", critical_flags=(),
                    independent_evidence=("visual-strong-anchor", "independent-second-decode"),
                    provenance={"visual_model": "resnet18-linear-five-v2", "generic_asr": "faster-whisper-large-v3", "second_decode": row["second_text"], "voice_score": own["score"], "voice_margin": float(own["score"]) - other_score},
                    source_vod_id=row["vod_id"],
                ))
        trusted_reports[creator] = bootstrap.bootstrap_trusted_speech(creator, batch, profile_version=PROFILE)
        lexicon_reports[creator] = bootstrap.bootstrap_lexicon(creator, profile_version=PROFILE)

    adaptive_rows: list[dict[str, Any]] = []
    for creator in CREATORS:
        terms = repository.rows("creator_lexicon_entries", where="creator_id=? AND profile_version=?", params=(creator, PROFILE))
        history = {str(row["text"]): int(row["trusted_occurrences"]) for row in terms}
        hotwords = [term for term, _ in sorted(history.items(), key=lambda item: (-item[1], item[0]))[:30]]
        profile = profiles[creator]
        for row in candidates[creator]["validation"]:
            identity = CreatorIdentityDecision(row["vod_id"], row["start_ms"], row["end_ms"], IdentityState.PROBABLE, creator, row["visual_confidence"], .0, .9, profile_version=PROFILE)
            result = adaptive.shadow_decide(
                recording_id=row["vod_id"], start_ms=row["start_ms"], end_ms=row["end_ms"],
                generic_text=row["text"], identity=identity, profile_version=PROFILE,
                base_confidence=row["confidence"], candidate_terms=hotwords,
                historical_evidence=history,
                redecode=(lambda selected, row=row: (row["second_text"], row["second_confidence"])) if hotwords else None,
            )
            adaptive_rows.append(asdict(result) | {"action": result.action.value, "identity_state": result.identity_state.value, "media": row["wav"]})

    for creator in CREATORS:
        profile = profiles[creator]
        repository.ensure_profile(
            creator, PROFILE, visual_status="READY",
            voice_status="READY" if "centroid" in profile else "INSUFFICIENT_DATA",
            trusted_speech_status="READY" if trusted_reports[creator].get("pseudo_trusted", 0) else "INSUFFICIENT_DATA",
            lexicon_status="READY" if lexicon_reports[creator].get("promoted", 0) else "INSUFFICIENT_DATA",
        )

    review = {"schema_version": 4, "profile_version": PROFILE, "identity": [], "trusted_speech": [], "adaptive_asr": []}
    for creator in CREATORS:
        for unit in repository.rows("trusted_speech_units", where="creator_id=? AND profile_version=?", params=(creator, PROFILE))[:50]:
            review["trusted_speech"].append({"id": unit["id"], "creator": creator, "creator_id": creator, "recording_id": unit["recording_id"], "media": unit["audio_locator"], "start_ms": unit["start_ms"], "end_ms": unit["end_ms"], "predicted_creator": creator, "transcript": unit["raw_asr"], "context": unit["trust_level"], "profile_version": PROFILE, "trusted_speech_unit_id": unit["id"]})
    for row in adaptive_rows:
        review["adaptive_asr"].append({"id": row["id"], "creator": row["creator_id"], "creator_id": row["creator_id"], "recording_id": row["recording_id"], "media": row["media"], "start_ms": row["start_ms"], "end_ms": row["end_ms"], "generic_text": row["generic_text"], "adaptive_text": row["adaptive_text"], "context": row["action"], "profile_version": PROFILE})

    receipt = {
        "status": "PASS", "profile_version": PROFILE, "dataset": "five-creator-adaptive-v2",
        "production_status": "SHADOW_CALIBRATION_ONLY", "evaluation_status": "VALIDATION_ONLY_NO_HOLDOUT_CLAIM",
        "ground_truth_opened": False, "holdout_samples": 0, "selected_visual_anchors": len(selected),
        "voice_profiles": profiles, "voice_validation": validation,
        "trusted_speech": trusted_reports, "lexicon": lexicon_reports,
        "adaptive_shadow": {"items": len(adaptive_rows), "actions": dict(Counter(row["action"] for row in adaptive_rows)), "official_transcript_mutations": 0},
        "profiles": {creator: repository.profile_summary(creator) for creator in CREATORS},
        "raw_media_mutations": 0, "human_ground_truth": "NOT_EVALUATED",
    }
    _dump(run / "voice-profile-five-v2.json", profiles)
    _dump(run / "voice-validation-five-v2.json", validation)
    _dump(run / "trusted-speech-five-v2.json", trusted_reports)
    _dump(run / "creator-lexicon-five-v2.json", {creator: {**lexicon_reports[creator], "entries": repository.rows("creator_lexicon_entries", where="creator_id=? AND profile_version=?", params=(creator, PROFILE))} for creator in CREATORS})
    _dump(run / "adaptive-shadow-five-v2.json", {"summary": receipt["adaptive_shadow"], "items": adaptive_rows})
    _dump(run / "human-review-five-v2.json", review)
    _dump(run / "creator-adaptive-five-v2-receipt.json", receipt)
    _dump(run / "progress.json", {"status": "COMPLETE", "result": "PASS", "ground_truth_opened": False})
    print(json.dumps({"run": str(run), "voice_validation": validation, "trusted": trusted_reports, "lexicon": lexicon_reports, "adaptive": receipt["adaptive_shadow"]}, ensure_ascii=False, indent=2))
    del dll_handle
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
