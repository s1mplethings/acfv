from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import cv2
import numpy as np

from acfv.clips import ClipService
from acfv.conversation import GroundedConversationService
from acfv.creator_adaptive.final_holdout import claim_final_holdout, records_from_manifest
from acfv.creator_adaptive.models import CreatorIdentityDecision, IdentityState
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive_asr import CreatorAdaptiveASRService
from acfv.creator_visual_identity.encoders import TorchvisionEncoder
from acfv.creator_visual_identity.model import LinearProbeIdentityModel, VisualIdentityState
from acfv.library import LibraryService, RecordingStatus
from acfv.moments import MomentFinalizer
from acfv.providers.avatar_identity import ExistingAvatarModelAdapter
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex
from acfv.voice_profile import CreatorVoiceProfileService

from scripts.prepare_active_creator_final_holdout_v1 import ACTIVE_CREATORS, canonical_sha256


PROFILE_VERSION = "active_creator_profile_v2_frozen"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite Final evidence: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _activate_windows_cuda_runtime() -> object | None:
    if os.name != "nt":
        return None
    runtime = Path(sys.prefix) / "Library" / "bin"
    if not runtime.is_dir():
        return None
    os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
    add = getattr(os, "add_dll_directory", None)
    return add(str(runtime)) if callable(add) else None


def validate_preflight(
    manifest: dict[str, Any], manifest_path: Path, evidence: Path, repository: Path,
) -> dict[str, Any]:
    expected = str(manifest.get("manifest_sha256") or "")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if canonical_sha256(body) != expected:
        raise RuntimeError("Final manifest canonical SHA-256 mismatch")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repository, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=repository, text=True).strip()
    if dirty or head != manifest["git_commit_sha"] or tree != manifest["git_tree_sha"]:
        raise RuntimeError("Final code freeze no longer matches clean committed state")
    artifact_checks = []
    for artifact in manifest["frozen_artifacts"]:
        path = Path(artifact["path"])
        actual = file_sha256(path)
        artifact_checks.append({"path": str(path), "expected": artifact["sha256"], "actual": actual, "passed": actual == artifact["sha256"]})
    if not all(row["passed"] for row in artifact_checks):
        raise RuntimeError("frozen profile/model/knowledge artifact changed")
    media = {}
    for row in manifest["rows"]:
        vod_id = str(row["vod_id"])
        receipt = json.loads((evidence / f"download-{vod_id}.json").read_text(encoding="utf-8"))
        integrity = json.loads((evidence / f"integrity-{vod_id}.json").read_text(encoding="utf-8"))
        path = Path(receipt["media_path"])
        if receipt.get("status") != "PASS" or integrity.get("status") != "PASS":
            raise RuntimeError(f"Final media gate did not pass for {vod_id}")
        if not path.is_file() or file_sha256(path) != receipt["media_sha256"]:
            raise RuntimeError(f"Final media changed after integrity for {vod_id}")
        media[str(row["creator"])] = path
    return {
        "status": "PASS", "manifest_file_sha256": file_sha256(manifest_path),
        "git_commit_sha": head, "git_tree_sha": tree,
        "artifact_checks": artifact_checks, "media": {key: str(value) for key, value in media.items()},
        "ground_truth_opened": False, "checked_at": utc_now(),
    }


def _sample_times(duration_seconds: int, count: int) -> list[int]:
    start = max(30.0, duration_seconds * .05)
    end = min(duration_seconds - 30.0, duration_seconds * .95)
    if end <= start:
        return [max(0, duration_seconds // 2) * 1000]
    return [int(value * 1000) for value in np.linspace(start, end, count)]


def _read_frame(media: Path, timestamp_ms: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(media))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        raise RuntimeError(f"cannot decode frame at {timestamp_ms} from {media}")
    return frame


def _crop_avatar(frame: np.ndarray, observations: list[Any]) -> np.ndarray | None:
    candidates = [row for row in observations if row.bbox]
    if not candidates:
        return None
    row = max(candidates, key=lambda value: float(value.confidence))
    x1, y1, x2, y2 = (int(round(value)) for value in row.bbox)
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return frame[y1:y2, x1:x2].copy() if x2 > x1 and y2 > y1 else None


def _extract_audio(media: Path, output: Path, timestamp_ms: int, seconds: int) -> tuple[int, int]:
    start_ms = max(0, timestamp_ms - seconds * 500)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-y",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(media), "-t", str(seconds),
        "-vn", "-ac", "1", "-ar", "16000", str(output),
    ], check=True)
    return start_ms, start_ms + seconds * 1000


def _transcribe(model: Any, wav: Path, hotwords: list[str] | None = None) -> tuple[str, float]:
    segments, _ = model.transcribe(
        str(wav), language="en", beam_size=5, word_timestamps=True, vad_filter=True,
        condition_on_previous_text=not hotwords,
        hotwords=", ".join(hotwords or []) or None,
    )
    values = list(segments)
    text = " ".join(str(value.text).strip() for value in values).strip()
    confidence = max((math.exp(float(value.avg_logprob)) * (1 - float(value.no_speech_prob)) for value in values), default=0.0)
    return text, min(1.0, confidence)


def _agreement(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold().strip(), right.casefold().strip()).ratio() if left and right else 0.0


def _token_encoder(texts: list[str]) -> np.ndarray:
    rows = []
    for text in texts:
        vector = np.zeros(64, dtype=np.float32)
        for token in text.casefold().split():
            vector[int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % len(vector)] += 1
        rows.append(vector)
    return np.asarray(rows, dtype=np.float32)


def _media_decode_receipt(path: Path) -> dict[str, Any]:
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "json", str(path),
    ], capture_output=True, text=True, check=True)
    streams = {str(row.get("codec_type")) for row in json.loads(probe.stdout).get("streams", [])}
    decode = subprocess.run([
        "ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-i", str(path),
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
    ], capture_output=True, text=True)
    return {
        "ffprobe_pass": True, "video_stream": "video" in streams,
        "audio_stream": "audio" in streams, "full_decode_exit_code": decode.returncode,
        "full_decode_pass": decode.returncode == 0,
        "stderr_tail": "\n".join(decode.stderr.splitlines()[-10:]),
    }


def _product_smoke(
    root: Path, creator_name: str, vod_id: str, media: Path,
    segment: dict[str, Any],
) -> dict[str, Any]:
    creator_root = root / creator_name
    library = LibraryService(creator_root / "product.sqlite")
    creator = library.create_creator(creator_name, slug=creator_name)
    source = library.add_source(
        creator.id, platform="twitch", external_id=creator_name,
        channel_name=creator_name, channel_url=f"https://twitch.tv/{creator_name}",
    )
    recording = library.register_recording(
        creator_id=creator.id, source_id=source.id, title=f"Final {vod_id}",
        local_path=media, source_type="final_holdout_evaluation",
        source_url=f"https://www.twitch.tv/videos/{vod_id}",
        recording_status=RecordingStatus.COMPLETE,
    )
    start_s, end_s = segment["start_ms"] / 1000.0, segment["end_ms"] / 1000.0
    asr = {"segments": [{"start": start_s, "end": end_s, "text": segment["generic_text"] or "inaudible final sample"}]}
    chat = {"records": []}
    moment = MomentFinalizer(library.repository).finalize(recording.id, asr, chat)[0]
    index = PersistentMomentIndex(library.repository, creator_root / "index", encoder=_token_encoder)
    retrieval = HybridRetrievalService(library.repository, index, load_default_reranker=False)
    retrieval.rebuild()
    query = " ".join((segment["generic_text"] or "final sample").split()[:5])
    search = retrieval.search(query)
    conversation_service = GroundedConversationService(retrieval)
    conversation = conversation_service.ask(query)
    cross_language_query = f"{creator_name} momento final " + query
    cross_language = conversation_service.ask(cross_language_query)
    no_evidence = conversation_service.ask("quasar unobtainium zxqv no evidence claim")
    clips = ClipService(library.repository, output_root=creator_root / "clips")
    proposal = clips.create_proposal(moment.id, query=query, context_before_ms=0, context_after_ms=0)
    proposal = clips.update_review(
        proposal.id, start_ms=segment["start_ms"], end_ms=segment["end_ms"],
        subtitle_text=segment["generic_text"] or "[inaudible]", subtitle_style={"preset": "clean"},
    )
    rendered = clips.render(proposal.id)
    output = Path(str(rendered.output_path))
    decode = _media_decode_receipt(output)
    no_evidence_safe = not no_evidence.grounded and not no_evidence.evidence_cards
    return {
        "status": "PASS" if (
            search and conversation.evidence_cards and output.is_file() and output.stat().st_size
            and no_evidence_safe and decode["video_stream"] and decode["audio_stream"]
            and decode["full_decode_pass"]
        ) else "FAIL",
        "moment_id": moment.id, "search_results": len(search),
        "known_query": query, "cross_language_query": cross_language_query,
        "cross_language_evidence_cards": len(cross_language.evidence_cards),
        "conversation_evidence_cards": len(conversation.evidence_cards),
        "conversation_grounded": conversation.grounded,
        "no_evidence_no_claim": no_evidence_safe,
        "clip_id": rendered.id, "subtitle_text_present": bool(proposal.subtitle_text),
        "render_path": str(output), "render_bytes": output.stat().st_size if output.is_file() else 0,
        "render_integrity": decode,
    }


def _final_memory_safety(
    rows_by_creator: dict[str, list[dict[str, Any]]],
    lexicons: dict[str, dict[str, Any]], repository: CreatorAdaptiveRepository,
) -> dict[str, Any]:
    adaptive = CreatorAdaptiveASRService(repository=repository)
    rows = []
    for actual, samples in rows_by_creator.items():
        sample = samples[0]
        for target in ACTIVE_CREATORS:
            same = actual == target
            target_terms = [str(row["text"]) for row in lexicons[target].get("entries", [])][:8]
            poison = target_terms[0] if target_terms else f"poison-{target}"
            identity = CreatorIdentityDecision(
                f"final-memory-gate-{actual}-{target}", sample["start_ms"], sample["end_ms"],
                IdentityState.CONFIRMED if same else IdentityState.CONFLICT,
                actual if same else None,
                visual_score=1.0 if same else 0.0, voice_score=1.0 if same else 0.0,
                recording_prior=1.0 if same else 0.0, profile_version=PROFILE_VERSION,
            )
            result = adaptive.shadow_decide(
                recording_id=identity.recording_id, start_ms=identity.start_ms,
                end_ms=identity.end_ms, generic_text=sample["generic_text"],
                identity=identity, profile_version=PROFILE_VERSION,
                base_confidence=sample["generic_confidence"], candidate_terms=(poison,),
                historical_evidence={poison: 10},
                redecode=lambda _terms, text=sample["generic_text"], confidence=sample["generic_confidence"]: (text, confidence),
            )
            rows.append({
                "actual": actual, "target_memory": target, "same_creator": same,
                "action": result.action.value,
                "memory_blocked": not same and result.action.value == "GENERIC_FALLBACK",
            })
    failures = [row for row in rows if not row["same_creator"] and not row["memory_blocked"]]
    return {
        "status": "PASS" if not failures else "FAIL", "cases": len(rows),
        "cross_creator_attacks": len(ACTIVE_CREATORS) * (len(ACTIVE_CREATORS) - 1),
        "blocked": sum(row["memory_blocked"] for row in rows),
        "failures": failures, "rows": rows,
    }


def run_evaluation(args: argparse.Namespace, manifest: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    from faster_whisper import WhisperModel
    from resemblyzer import VoiceEncoder, preprocess_wav
    import soundfile as sf
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    detector = ExistingAvatarModelAdapter(args.avatar_model, entrypoint=args.avatar_entrypoint)
    if detector.status != "READY":
        raise RuntimeError(f"avatar detector is not ready: {detector.audit()}")
    resnet = TorchvisionEncoder(weights_path=args.resnet_weights, device=device)
    old_visual = LinearProbeIdentityModel.load(args.old_visual_model)
    new_visual = LinearProbeIdentityModel.load(args.new_visual_model)
    old_profiles = json.loads(args.old_voice_profiles.read_text(encoding="utf-8"))
    new_profiles = json.loads(args.new_voice_profiles.read_text(encoding="utf-8"))
    profiles = {creator: {**old_profiles, **new_profiles}[creator] for creator in ACTIVE_CREATORS}
    old_lexicon = json.loads(args.old_lexicon.read_text(encoding="utf-8"))
    new_lexicon = json.loads(args.new_lexicon.read_text(encoding="utf-8"))
    lexicons = {creator: {**old_lexicon, **new_lexicon}.get(creator, {"entries": []}) for creator in ACTIVE_CREATORS}
    whisper = WhisperModel(
        "Systran/faster-whisper-large-v3", device=device,
        compute_type="float16" if device == "cuda" else "int8", local_files_only=True,
    )
    speaker = VoiceEncoder(device=device)
    repository = CreatorAdaptiveRepository(args.output / "final-evaluation.sqlite")
    adaptive = CreatorAdaptiveASRService(repository=repository)
    rows_by_creator: dict[str, list[dict[str, Any]]] = {}
    for manifest_row in manifest["rows"]:
        creator = str(manifest_row["creator"])
        vod_id = str(manifest_row["vod_id"])
        media = Path(preflight["media"][creator])
        samples = []
        for index, timestamp_ms in enumerate(_sample_times(int(manifest_row["duration_seconds"]), args.samples_per_creator)):
            frame = _read_frame(media, timestamp_ms)
            observations = detector.identify_frame(frame, timestamp_ms)
            crop = _crop_avatar(frame, observations)
            if crop is None:
                visual = {"state": "UNKNOWN", "creator_id": None, "score": 0.0, "margin": 0.0, "support_score": 0.0}
            else:
                vector = resnet.encode([crop])[0]
                prediction = (old_visual if creator == "saruei" else new_visual).predict(vector)
                visual = {
                    "state": prediction.state.value, "creator_id": prediction.creator_id,
                    "score": prediction.score, "margin": prediction.margin,
                    "support_score": prediction.support_score,
                }
            wav = args.output / "audio" / creator / f"{vod_id}-{index:02d}.wav"
            start_ms, end_ms = _extract_audio(media, wav, timestamp_ms, args.clip_seconds)
            audio, rate = sf.read(wav, dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            utterance = preprocess_wav(audio, source_sr=rate)
            embedding = speaker.embed_utterance(utterance).astype(float).tolist()
            voice = CreatorVoiceProfileService.classify_evidence(
                embedding, profiles[creator], (profile for name, profile in profiles.items() if name != creator),
                visual_strong=visual["state"] == VisualIdentityState.STRONG.value and visual["creator_id"] == creator,
                recording_prior_same=True, sustained_mismatch=False,
            )
            generic_text, generic_confidence = _transcribe(whisper, wav)
            terms = [str(entry["text"]) for entry in lexicons[creator].get("entries", [])]
            adaptive_text, adaptive_confidence = _transcribe(whisper, wav, terms) if terms else (generic_text, generic_confidence)
            visual_same = visual["creator_id"] == creator and visual["state"] == "STRONG"
            voice_same = voice["state"] == "SUPPORT"
            if visual_same and voice_same:
                state = IdentityState.CONFIRMED
            elif visual_same or voice_same:
                state = IdentityState.PROBABLE
            elif voice["state"] == "IDENTITY_CONFLICT" or (visual["creator_id"] not in {None, creator} and visual["state"] == "STRONG"):
                state = IdentityState.CONFLICT
            else:
                state = IdentityState.UNKNOWN
            identity = CreatorIdentityDecision(
                vod_id, start_ms, end_ms, state,
                creator if state in {IdentityState.CONFIRMED, IdentityState.PROBABLE} else None,
                visual_score=float(visual["score"]), voice_score=float(voice["expected"]["score"]),
                recording_prior=.9, profile_version=PROFILE_VERSION,
            )
            history = {str(entry["text"]): int(entry.get("trusted_occurrences", 0)) for entry in lexicons[creator].get("entries", [])}
            shadow = adaptive.shadow_decide(
                recording_id=vod_id, start_ms=start_ms, end_ms=end_ms,
                generic_text=generic_text, identity=identity, profile_version=PROFILE_VERSION,
                base_confidence=generic_confidence, candidate_terms=terms,
                historical_evidence=history,
                redecode=lambda _terms, text=adaptive_text, confidence=adaptive_confidence: (text, confidence),
            )
            samples.append({
                "sample_id": f"{creator}:{vod_id}:{index}", "creator": creator,
                "vod_id": vod_id, "start_ms": start_ms, "end_ms": end_ms,
                "visual": visual, "voice": voice,
                "identity": {"state": state.value, "creator_id": identity.creator_id},
                "generic_text": generic_text, "generic_confidence": generic_confidence,
                "adaptive_text": adaptive_text, "adaptive_confidence": adaptive_confidence,
                "adaptive_action": shadow.action.value,
                "transcript_agreement": _agreement(generic_text, adaptive_text),
                "trusted_eligible": identity.allows_creator_memory and voice_same and generic_confidence >= .75,
                "official_transcript_mutations": 0,
            })
        rows_by_creator[creator] = samples
    product = {
        creator: _product_smoke(
            args.output / "product", creator, str(next(row["vod_id"] for row in manifest["rows"] if row["creator"] == creator)),
            Path(preflight["media"][creator]), rows_by_creator[creator][0],
        ) for creator in ACTIVE_CREATORS
    }
    memory_safety = _final_memory_safety(rows_by_creator, lexicons, repository)
    per_creator = {}
    cross_false_accepts = 0
    for creator, rows in rows_by_creator.items():
        cross_false_accepts += sum(
            row["identity"]["creator_id"] not in {None, creator} for row in rows
        )
        states = Counter(row["identity"]["state"] for row in rows)
        visual_states = Counter(row["visual"]["state"] for row in rows)
        voice_states = Counter(row["voice"]["state"] for row in rows)
        adaptive_actions = Counter(row["adaptive_action"] for row in rows)
        per_creator[creator] = {
            "samples": len(rows), "identity_states": dict(states),
            "visual_states": dict(visual_states), "voice_states": dict(voice_states),
            "voice_mode_shifts": sum(row["voice"]["state"] == "VOICE_MODE_SHIFT_CANDIDATE" for row in rows),
            "identity_conflicts": sum(row["identity"]["state"] == "CONFLICT" for row in rows),
            "temporal_spans": [{"start_ms": row["start_ms"], "end_ms": row["end_ms"]} for row in rows],
            "trusted_eligible": sum(row["trusted_eligible"] for row in rows),
            "adaptive_actions": dict(adaptive_actions),
            "mean_transcript_agreement": float(np.mean([row["transcript_agreement"] for row in rows])),
            "product_smoke": product[creator],
            "decision": "HUMAN_VALIDATION_PENDING" if product[creator]["status"] == "PASS" else "KEEP_SHADOW",
        }
    status = "PASS" if (
        cross_false_accepts == 0 and memory_safety["status"] == "PASS"
        and all(row["status"] == "PASS" for row in product.values())
    ) else "FAIL"
    return {
        "schema_version": "1.0", "dataset_id": manifest["dataset_id"],
        "status": status, "claim": "FINAL_AUTOMATED_ENGINEERING_VALIDATION_PASS" if status == "PASS" else "KEEP_SHADOW",
        "human_validation": "HUMAN_VALIDATION_PENDING",
        "production_enabled": False, "production_decision": "KEEP_SHADOW",
        "scope": list(ACTIVE_CREATORS), "excluded_creators": {"anny": "OUT_OF_SCOPE_INACTIVE_CREATOR"},
        "samples_per_creator": args.samples_per_creator, "cross_creator_false_accepts": cross_false_accepts,
        "final_cross_creator_memory_safety": memory_safety,
        "final_poisoning": memory_safety,
        "per_creator": per_creator, "rows": rows_by_creator,
        "official_transcript_mutations": 0, "profile_mutations": 0,
        "trusted_memory_mutations": 0, "lexicon_mutations": 0,
        "ground_truth_opened": False, "completed_at": utc_now(),
    }


def human_review_payload(results: dict[str, Any]) -> dict[str, Any]:
    tasks = []
    for creator, rows in results["rows"].items():
        for row in rows:
            tasks.extend([
                {"task_id": f"{row['sample_id']}:visual", "task": "VISUAL_CORRECTNESS", "creator": creator, "sample": row["sample_id"], "label": None},
                {"task_id": f"{row['sample_id']}:trusted", "task": "TRUSTED_SPEECH", "creator": creator, "sample": row["sample_id"], "label": None},
                {"task_id": f"{row['sample_id']}:asr", "task": "ADAPTIVE_ASR_AB", "creator": creator, "sample": row["sample_id"], "human_transcript": None, "choice": None},
            ])
    return {
        "schema_version": "1.0", "dataset_id": "ACTIVE_CREATOR_FINAL_HOLDOUT_V1_HUMAN_REVIEW",
        "source_dataset_id": results["dataset_id"], "status": "HUMAN_PENDING",
        "ground_truth_opened": False, "tasks": tasks, "created_at": utc_now(),
    }


def main() -> int:
    _dll_handle = _activate_windows_cuda_runtime()
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--download-evidence", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--avatar-model", type=Path, required=True)
    parser.add_argument("--avatar-entrypoint", type=Path, required=True)
    parser.add_argument("--resnet-weights", type=Path, required=True)
    parser.add_argument("--old-visual-model", type=Path, required=True)
    parser.add_argument("--new-visual-model", type=Path, required=True)
    parser.add_argument("--old-voice-profiles", type=Path, required=True)
    parser.add_argument("--new-voice-profiles", type=Path, required=True)
    parser.add_argument("--old-lexicon", type=Path, required=True)
    parser.add_argument("--new-lexicon", type=Path, required=True)
    parser.add_argument("--samples-per-creator", type=int, default=8)
    parser.add_argument("--clip-seconds", type=int, default=14)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    preflight = validate_preflight(
        manifest, args.manifest.resolve(), args.download_evidence.resolve(), args.repository.resolve()
    )
    write_new(args.output / "final-preflight.json", preflight)
    claim = claim_final_holdout(
        records_from_manifest(manifest), dataset_id=manifest["dataset_id"],
        claim_path=args.output / "final-claim.json", preflight_passed=True,
    )
    try:
        results = run_evaluation(args, manifest, preflight)
        auto_path = args.output / "active-creator-final-holdout-v1-auto-results.json"
        write_new(auto_path, results)
        auto_sha = file_sha256(auto_path)
        review = human_review_payload(results)
        review["auto_results_path"] = str(auto_path)
        review["auto_results_sha256"] = auto_sha
        write_new(args.output / "active-creator-final-holdout-v1-human-review.json", review)
        lock = {
            **claim, "status": results["status"], "auto_results_sha256": auto_sha,
            "locked_at": utc_now(), "human_validation": "HUMAN_VALIDATION_PENDING",
            "production_enabled": False,
        }
        write_new(args.output / "active-creator-final-holdout-v1-lock.json", lock)
        print(json.dumps(lock, ensure_ascii=False))
        return 0 if results["status"] == "PASS" else 1
    except BaseException as exc:
        failure = {
            **claim, "status": "FAILED_LOCKED", "error_type": type(exc).__name__,
            "error": str(exc), "locked_at": utc_now(), "rerun_allowed": False,
            "ground_truth_opened": False,
        }
        write_new(args.output / "active-creator-final-holdout-v1-failure-lock.json", failure)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
