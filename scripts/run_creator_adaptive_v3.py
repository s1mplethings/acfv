from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import numpy as np
import soundfile as sf

from acfv.creator_adaptive.bootstrap import CreatorAdaptiveBootstrapService, TrustedSpeechCandidate
from acfv.creator_adaptive.models import CreatorIdentityDecision, IdentityObservation, IdentitySource, IdentityState
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive_asr import CreatorAdaptiveASRService
from acfv.creator_identity import CreatorIdentityService
from acfv.creator_visual_identity.model import LinearProbeIdentityModel
from acfv.voice_profile import CreatorVoiceProfileService, VoiceProfileInsufficientData

from build_creator_visual_dataset import sources


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "creator_profile_v3"


def activate_windows_cuda_runtime() -> object | None:
    if os.name != "nt":
        return None
    runtime = Path(sys.prefix) / "Library" / "bin"
    if not runtime.is_dir():
        return None
    os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
    add_directory = getattr(os, "add_dll_directory", None)
    return add_directory(str(runtime)) if callable(add_directory) else None


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[\w'-]+", value.casefold()))


def agreement(left: str, right: str) -> float:
    return SequenceMatcher(None, normalized(left), normalized(right)).ratio() if left and right else 0.0


def overlaps(start: int, end: int, spans: list[dict[str, Any]], offset: int) -> bool:
    for span in spans:
        left = int(span.get("start_ms", span.get("start", 0))) - offset
        right = int(span.get("end_ms", span.get("end", 0))) - offset
        if start < right and end > left:
            return True
    return False


def visual_consensus(manifest: Path, vectors_path: Path, model_path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    vectors = np.load(vectors_path)["embeddings"]
    model = LinearProbeIdentityModel.load(model_path)
    grouped: dict[str, list[tuple[dict[str, Any], Any]]] = defaultdict(list)
    for row, vector in zip(rows, vectors):
        if row["creator_id"]:
            grouped[row["recording_id"]].append((row, model.predict(vector)))
    report = {}
    for recording_id, values in grouped.items():
        expected = values[0][0]["creator_id"]
        strong = [prediction for _, prediction in values if prediction.state.value == "STRONG"]
        wrong = [prediction for prediction in strong if prediction.creator_id != expected]
        correct = [prediction for prediction in strong if prediction.creator_id == expected]
        report[recording_id] = {
            "creator_id": expected, "samples": len(values), "strong": len(strong),
            "strong_correct": len(correct), "strong_wrong": len(wrong),
            "strong_coverage": len(correct) / len(values),
            "eligible": len(correct) >= 3 and not wrong,
            "visual_confidence": .85 + .14 * min(1.0, len(correct) / max(1, len(values))),
        }
    return report


def existing_transcript(folder: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = json.loads((folder / "standard/manifest.json").read_text(encoding="utf-8"))
    transcript_path = next(folder.glob("final_transcript/*/final_event_transcript.json"))
    quality_path = next(folder.glob("final_transcript/*/final_transcript_quality.json"))
    return manifest, json.loads(transcript_path.read_text(encoding="utf-8")), json.loads(quality_path.read_text(encoding="utf-8"))


def expected_for_segment(transcript: dict[str, Any], clip_offset: int, start_ms: int, end_ms: int, *, tolerance_ms: int = 1500) -> tuple[str, tuple[str, ...]]:
    words, flags = [], []
    for word in transcript.get("aligned_words", []):
        local_start = int(word.get("start_ms", 0)) - clip_offset
        local_end = int(word.get("end_ms", 0)) - clip_offset
        if start_ms - tolerance_ms < local_end and end_ms + tolerance_ms > local_start:
            words.append(str(word.get("text", "")))
            flags.extend(str(value) for value in word.get("quality_flags", []) if value)
    return " ".join(words), tuple(sorted(set(flags)))


def extract_audio(media: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", str(target)], check=True)


def main() -> int:
    dll_handle = activate_windows_cuda_runtime()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/creator-adaptive-v3-real")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    repository = CreatorAdaptiveRepository(output / "creator-adaptive-v3.sqlite")
    identity_service = CreatorIdentityService(repository=repository)
    voice_service = CreatorVoiceProfileService(repository=repository)
    bootstrap = CreatorAdaptiveBootstrapService(repository)
    adaptive = CreatorAdaptiveASRService(repository=repository)
    consensus = visual_consensus(
        ROOT / "var/creator-visual-identity-v1/visual-dataset-manifest.jsonl",
        ROOT / "var/creator-visual-identity-v1/benchmark/resnet18-linear-embeddings.npz",
        ROOT / "var/creator-visual-identity-v1/benchmark/resnet18-linear-identity-model.joblib",
    )

    from faster_whisper import WhisperModel
    from resemblyzer import VoiceEncoder, preprocess_wav
    import torch

    whisper = WhisperModel("Systran/faster-whisper-large-v3", device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16" if torch.cuda.is_available() else "int8", local_files_only=True)
    speaker = VoiceEncoder(device="cuda" if torch.cuda.is_available() else "cpu")
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_rows = [source for source in sources() if source.creator_id]
    for source in source_rows:
        visual = consensus[source.recording_id]
        if not visual["eligible"]:
            continue
        folder = source.path.parents[1]
        manifest, prior_transcript, quality = existing_transcript(folder)
        wav = output / "audio" / f"{source.recording_id}.wav"
        extract_audio(source.path, wav)
        audio, sample_rate = sf.read(wav, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        segments, info = whisper.transcribe(str(wav), language="en", beam_size=5, word_timestamps=True, vad_filter=True, condition_on_previous_text=True)
        for segment in segments:
            start_ms, end_ms = int(segment.start * 1000), int(segment.end * 1000)
            if end_ms - start_ms < 900 or end_ms - start_ms > 15000:
                continue
            expected, critical_flags = expected_for_segment(prior_transcript, int(manifest["start_ms"]), start_ms, end_ms)
            text = str(segment.text).strip()
            redecode_agreement = agreement(text, expected)
            confidence = max(0.0, min(1.0, math.exp(float(segment.avg_logprob)) * (1 - float(segment.no_speech_prob))))
            music = overlaps(start_ms, end_ms, list(quality.get("music_spans", [])), int(manifest["start_ms"]))
            overlap = overlaps(start_ms, end_ms, list(quality.get("overlap_spans", [])), int(manifest["start_ms"]))
            left, right = max(0, int(segment.start * sample_rate)), min(len(audio), int(segment.end * sample_rate))
            utterance = preprocess_wav(audio[left:right], source_sr=sample_rate)
            if len(utterance) < sample_rate * .6:
                continue
            embedding = speaker.embed_utterance(utterance).astype(float).tolist()
            visual_observation = IdentityObservation(source.recording_id, start_ms, end_ms, source.creator_id, IdentitySource.VISUAL, float(visual["visual_confidence"]), "creator-visual-identity-v1", "resnet18-linear-open-set")
            prior = IdentityObservation(source.recording_id, start_ms, end_ms, source.creator_id, IdentitySource.RECORDING_PRIOR, .9, "library-recording-owner", "library-v1")
            initial = identity_service.fuse(source.recording_id, start_ms, end_ms, [visual_observation, prior], profile_version=PROFILE)
            # Voice identity is built from bounded 2-5 second utterance pieces;
            # long ASR segments otherwise under-count evidence and blur pauses.
            piece_ms = 3500
            for piece_start in range(start_ms, end_ms, piece_ms):
                piece_end = min(end_ms, piece_start + piece_ms)
                if piece_end - piece_start < 1500:
                    continue
                piece_left, piece_right = int(piece_start / 1000 * sample_rate), int(piece_end / 1000 * sample_rate)
                piece = preprocess_wav(audio[piece_left:piece_right], source_sr=sample_rate)
                if len(piece) < sample_rate * .6:
                    continue
                piece_embedding = speaker.embed_utterance(piece).astype(float).tolist()
                voice_service.add_exemplar(
                    creator_id=source.creator_id, recording_id=source.recording_id, start_ms=piece_start, end_ms=piece_end,
                    audio_locator=str(wav), embedding=piece_embedding, speech_quality=1 - float(segment.no_speech_prob),
                    identity_confidence=float(visual["visual_confidence"]), asr_confidence=confidence,
                    overlap_status="SUSPECT" if overlap else "CLEAN", music_status="SUSPECT" if music else "NONE",
                    trust_level="PSEUDO_TRUSTED" if initial.state is IdentityState.PROBABLE and not music and not overlap else "REJECTED",
                    profile_version=PROFILE, temporal_region=source.recording_id,
                )
            candidates[source.creator_id].append({
                "source": source, "wav": wav, "start_ms": start_ms, "end_ms": end_ms, "text": text,
                "expected": expected, "confidence": confidence, "agreement": redecode_agreement,
                "critical_flags": critical_flags, "music": music, "overlap": overlap,
                "embedding": embedding, "visual": visual, "initial_identity": initial,
                "words": tuple({"word": str(word.word).strip(), "start_ms": int(word.start * 1000), "end_ms": int(word.end * 1000), "probability": float(word.probability)} for word in (segment.words or [])),
            })

    profiles: dict[str, dict[str, Any]] = {}
    for creator in ("saruei", "anny"):
        try:
            profiles[creator] = voice_service.build(creator, profile_version=PROFILE)
        except VoiceProfileInsufficientData as exc:
            profiles[creator] = {"creator_id": creator, "profile_version": PROFILE, "status": "INSUFFICIENT_DATA", "reason": str(exc)}

    # Cross-Creator calibration keeps voice in a support-only role and forces a
    # zero false-accept threshold on the observed opposite-Creator candidates.
    for creator, profile in profiles.items():
        if "centroid" not in profile:
            continue
        own = [voice_service.match(row["embedding"], profile)["score"] for row in candidates[creator]]
        other = [voice_service.match(row["embedding"], profile)["score"] for key, rows in candidates.items() if key != creator for row in rows]
        threshold = max(float(profile["strong_threshold"]), (max(other) + .001) if other else -1.0)
        profile["production_strong_threshold"] = threshold
        profile["far_proxy"] = sum(score >= threshold for score in other) / len(other) if other else 0.0
        profile["frr_proxy"] = sum(score < threshold for score in own) / len(own) if own else 1.0

    trusted_reports, lexicon_reports = {}, {}
    trusted_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for creator, rows in candidates.items():
        profile = profiles[creator]
        if "centroid" not in profile:
            trusted_reports[creator] = {"candidates": len(rows), "pseudo_trusted": 0, "rejected": len(rows), "reason": "voice profile unavailable"}
            continue
        other_profile = profiles["anny" if creator == "saruei" else "saruei"]
        batch = []
        for row in rows:
            own_score = float(voice_service.match(row["embedding"], profile)["score"])
            other_score = float(voice_service.match(row["embedding"], other_profile)["score"]) if "centroid" in other_profile else -1.0
            voice_strong = own_score >= profile["production_strong_threshold"] and own_score - other_score >= .03
            voice_confidence = min(.99, .8 + max(0.0, own_score - profile["production_strong_threshold"])) if voice_strong else .0
            if voice_strong and row["confidence"] >= .70:
                second_segments, _ = whisper.transcribe(
                    str(row["wav"]), language="en", beam_size=5, word_timestamps=False, vad_filter=False,
                    condition_on_previous_text=False,
                    clip_timestamps=f"{max(0, row['start_ms']-500)/1000},{(row['end_ms']+500)/1000}",
                )
                second_text = " ".join(str(value.text).strip() for value in second_segments).strip()
                row["agreement"] = agreement(row["text"], second_text)
                row["second_decode"] = second_text
            visual_observation = IdentityObservation(row["source"].recording_id, row["start_ms"], row["end_ms"], creator, IdentitySource.VISUAL, float(row["visual"]["visual_confidence"]), "creator-visual-identity-v1", "resnet18-linear-open-set")
            prior = IdentityObservation(row["source"].recording_id, row["start_ms"], row["end_ms"], creator, IdentitySource.RECORDING_PRIOR, .9, "library-recording-owner", "library-v1")
            evidence = [visual_observation, prior]
            if voice_strong:
                evidence.append(IdentityObservation(row["source"].recording_id, row["start_ms"], row["end_ms"], creator, IdentitySource.VOICE, voice_confidence, "resemblyzer-v3", "resemblyzer-pretrained"))
            decision = identity_service.fuse(row["source"].recording_id, row["start_ms"], row["end_ms"], evidence, profile_version=PROFILE)
            candidate = TrustedSpeechCandidate(
                identity=decision, recording_id=row["source"].recording_id, start_ms=row["start_ms"], end_ms=row["end_ms"],
                audio_locator=str(row["wav"]), raw_asr=row["text"], word_timestamps=row["words"],
                asr_confidence=row["confidence"], redecode_agreement=row["agreement"],
                overlap_status="SUSPECT" if row["overlap"] else "CLEAN", music_status="SUSPECT" if row["music"] else "NONE",
                critical_flags=row["critical_flags"], independent_evidence=("visual-strong-span", "independent-final-asr"),
                provenance={"visual_model": "creator_visual_identity_v1", "generic_asr": "faster-whisper-large-v3", "comparison_transcript": "independent-local-large-v3" if row.get("second_decode") else "existing-final-asr", "second_decode": row.get("second_decode", ""), "voice_score": own_score, "voice_margin": own_score - other_score},
            )
            batch.append(candidate)
            trusted_rows[creator].append({"candidate": candidate, "voice_score": own_score, "voice_margin": own_score - other_score})
        trusted_reports[creator] = bootstrap.bootstrap_trusted_speech(creator, batch, profile_version=PROFILE)
        lexicon_reports[creator] = bootstrap.bootstrap_lexicon(creator, profile_version=PROFILE)

    adaptive_rows = []
    for creator in ("saruei", "anny"):
        terms = repository.rows("creator_lexicon_entries", where="creator_id=? AND profile_version=?", params=(creator, PROFILE))
        trusted_units = repository.rows("trusted_speech_units", where="creator_id=? AND profile_version=?", params=(creator, PROFILE))
        ephemeral = Counter(
            token for unit in trusted_units if unit["trust_level"] in {"TRUSTED_PSEUDO_LABEL", "HUMAN_CONFIRMED"}
            for token in normalized(str(unit["raw_asr"])).split() if len(token) >= 5
        )
        history = {str(row["text"]): int(row["trusted_occurrences"]) for row in terms}
        history.update({token: max(count, history.get(token, 0)) for token, count in ephemeral.items()})
        hotwords = [term for term, _ in sorted(history.items(), key=lambda item: (-item[1], item[0]))[:30]]
        for index, unit in enumerate(trusted_units[:20]):
            identity = CreatorIdentityDecision(str(unit["recording_id"]), int(unit["start_ms"]), int(unit["end_ms"]), IdentityState.CONFIRMED, creator, .9, .85, .9, profile_version=PROFILE)
            generic = str(unit["raw_asr"])
            # Real local re-decode is bounded to the same audio span. The full
            # WAV and timestamps are retained as provenance in the review item.
            def redecode(selected: list[str], unit=unit) -> tuple[str, float]:
                segments, _ = whisper.transcribe(str(unit["audio_locator"]), language="en", beam_size=5, vad_filter=True, clip_timestamps=f"{int(unit['start_ms'])/1000},{int(unit['end_ms'])/1000}", hotwords=", ".join(selected))
                values = list(segments)
                text = " ".join(str(value.text).strip() for value in values).strip()
                confidence = max([math.exp(float(value.avg_logprob)) * (1 - float(value.no_speech_prob)) for value in values], default=0.0)
                return text or generic, min(1.0, confidence)
            result = adaptive.shadow_decide(recording_id=str(unit["recording_id"]), start_ms=int(unit["start_ms"]), end_ms=int(unit["end_ms"]), generic_text=generic, identity=identity, profile_version=PROFILE, base_confidence=float(unit["asr_confidence"]), candidate_terms=hotwords, historical_evidence=history, redecode=redecode if hotwords and index < 5 else None)
            adaptive_rows.append(asdict(result) | {"action": result.action.value, "identity_state": result.identity_state.value, "media": str(unit["audio_locator"])})

    review = {"schema_version": 4, "profile_version": PROFILE, "identity": [], "trusted_speech": [], "adaptive_asr": []}
    visual_report = json.loads((ROOT / "var/creator-visual-identity-v1/real-validation/creator-visual-real-validation.json").read_text(encoding="utf-8"))
    for creator, details in visual_report["creators"].items():
        for index, row in enumerate(details["predictions"]):
            if len(review["identity"]) >= 150:
                break
            if row["state"] == "STRONG" or index % 10 == 0:
                review["identity"].append({"id": f"visual-{creator}-{index}", "creator": creator, "creator_id": creator, "recording_id": f"{creator}-real-holdout", "media": details["source"], "start_ms": row["timestamp_ms"], "end_ms": row["timestamp_ms"] + 1000, "predicted_creator": row["selected_creator"] or row["state"], "profile_version": PROFILE, "visual_score": row["score"], "context": f"state={row['state']} margin={row['margin']:.3f} support={row['support']:.3f}"})
    for creator in ("saruei", "anny"):
        units = repository.rows("trusted_speech_units", where="creator_id=? AND profile_version=?", params=(creator, PROFILE))[:50]
        for unit in units:
            review["trusted_speech"].append({"id": unit["id"], "creator": creator, "creator_id": creator, "recording_id": unit["recording_id"], "media": unit["audio_locator"], "start_ms": unit["start_ms"], "end_ms": unit["end_ms"], "predicted_creator": creator, "transcript": unit["raw_asr"], "context": unit["trust_level"], "profile_version": PROFILE, "trusted_speech_unit_id": unit["id"]})
    for row in adaptive_rows:
        review["adaptive_asr"].append({"id": row["id"], "creator": row["creator_id"], "creator_id": row["creator_id"], "recording_id": row["recording_id"], "media": row["media"], "start_ms": row["start_ms"], "end_ms": row["end_ms"], "generic_text": row["generic_text"], "adaptive_text": row["adaptive_text"], "context": row["action"], "profile_version": PROFILE})

    profiles_summary = {}
    for creator, profile in profiles.items():
        repository.ensure_profile(creator, PROFILE, visual_status="READY", voice_status="READY" if "centroid" in profile else "INSUFFICIENT_DATA", trusted_speech_status="READY" if trusted_reports.get(creator, {}).get("pseudo_trusted", 0) else "INSUFFICIENT_DATA", lexicon_status="READY" if lexicon_reports.get(creator, {}).get("promoted", 0) else "INSUFFICIENT_DATA")
        profiles_summary[creator] = repository.profile_summary(creator)
    shadow_counts = Counter(row["action"] for row in adaptive_rows)
    receipt = {
        "profile_version": PROFILE, "visual_consensus": consensus, "voice_profiles": profiles,
        "trusted_speech": trusted_reports, "lexicon": lexicon_reports,
        "adaptive_shadow": {"items": len(adaptive_rows), "actions": dict(shadow_counts), "official_transcript_mutations": 0},
        "profiles": profiles_summary, "raw_media_mutations": 0, "human_ground_truth": "NOT_EVALUATED",
        "recommendation": {"saruei": "KEEP_SHADOW", "anny": "KEEP_SHADOW"},
    }
    dump(output / "creator-identity-v3-real.json", {"visual_consensus": consensus, "decisions": repository.rows("creator_identity_decisions")})
    dump(output / "voice-profile-v3-real.json", profiles)
    dump(output / "trusted-speech-v3-real.json", trusted_reports)
    dump(output / "creator-lexicon-v3-real.json", {key: {**value, "entries": repository.rows("creator_lexicon_entries", where="creator_id=? AND profile_version=?", params=(key, PROFILE))} for key, value in lexicon_reports.items()})
    dump(output / "adaptive-shadow-v3-real.json", {"summary": receipt["adaptive_shadow"], "items": adaptive_rows})
    dump(output / "human-review-v4.json", review)
    dump(output / "creator-adaptive-full-test-receipt.json", receipt)
    print(json.dumps({"voice": {key: {field: value.get(field) for field in ("segments", "duration_ms", "retained", "far_proxy", "frr_proxy")} for key, value in profiles.items()}, "trusted": trusted_reports, "lexicon": lexicon_reports, "adaptive": receipt["adaptive_shadow"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
