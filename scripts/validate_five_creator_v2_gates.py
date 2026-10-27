from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sqlite3
from typing import Any

from acfv.creator_adaptive.models import CreatorIdentityDecision, IdentityState
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_adaptive_asr import CreatorAdaptiveASRService
from acfv.voice_profile import CreatorVoiceProfileService


DEFAULT_CREATORS = ("anny", "atelieranoko", "laphipi", "saruei", "snuffy")


def select_profiles(
    old_profiles: dict[str, dict[str, Any]],
    new_profiles: dict[str, dict[str, Any]],
    creators: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    requested = tuple(sorted(set(creators)))
    if len(requested) < 2:
        raise ValueError("cross-creator validation requires at least two creators")
    all_profiles = {**old_profiles, **new_profiles}
    missing = sorted(set(requested) - set(all_profiles))
    if missing:
        raise ValueError(f"missing creator profiles: {missing}")
    return {creator: all_profiles[creator] for creator in requested}


def _load_embeddings(database: Path) -> dict[str, list[list[float]]]:
    result: dict[str, list[list[float]]] = {}
    with sqlite3.connect(database) as connection:
        for creator, payload in connection.execute(
            "SELECT creator_id,embedding_json FROM creator_voice_exemplars "
            "WHERE trust_level IN ('PSEUDO_TRUSTED','HUMAN_CONFIRMED')"
        ):
            result.setdefault(str(creator), []).append(json.loads(str(payload)))
    return result


def calibrate_gates(
    profiles: dict[str, dict[str, Any]],
    new_embeddings: dict[str, list[list[float]]],
) -> dict[str, Any]:
    creators = tuple(sorted(profiles))
    matrix: dict[str, dict[str, float]] = {}
    prototypes = {creator: list(profile["medoid"]) for creator, profile in profiles.items()}
    for actual, vector in prototypes.items():
        matrix[actual] = {
            target: float(CreatorVoiceProfileService.match(vector, profile)["score"])
            for target, profile in profiles.items()
        }
    gates: dict[str, float] = {}
    for target, profile in profiles.items():
        base = float(profile.get(
            "validation_strong_threshold",
            profile.get("production_strong_threshold", profile.get("strong_threshold", 1.0)),
        ))
        negatives = [matrix[actual][target] for actual in creators if actual != target]
        negatives.extend(
            float(CreatorVoiceProfileService.match(vector, profile)["score"])
            for actual, vectors in new_embeddings.items() if actual != target
            for vector in vectors
        )
        gates[target] = max(base, max(negatives, default=-1.0) + .001)
    confusion = {creator: {value: 0 for value in (*creators, "UNKNOWN")} for creator in creators}
    for actual, vector in prototypes.items():
        accepted = [
            target for target, profile in profiles.items()
            if CreatorVoiceProfileService.match(vector, profile)["score"] >= gates[target]
        ]
        predicted = max(
            accepted,
            key=lambda target: CreatorVoiceProfileService.match(vector, profiles[target])["score"] - gates[target],
            default="UNKNOWN",
        )
        confusion[actual][predicted] += 1
    cross_false_accepts = sum(
        count for actual, row in confusion.items() for predicted, count in row.items()
        if predicted not in {actual, "UNKNOWN"}
    )
    return {
        "score_matrix": matrix,
        "support_only_gates": gates,
        "prototype_confusion": confusion,
        "cross_false_accepts": cross_false_accepts,
        "status": "PASS" if cross_false_accepts == 0 else "FAIL",
        "claim": "PROFILE_PROTOTYPE_AND_TRAIN_NEGATIVE_AUDIT_NO_HOLDOUT",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-profiles", type=Path, required=True)
    parser.add_argument("--new-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--creators", nargs="+", default=DEFAULT_CREATORS,
        help="Explicit evaluation scope. Profiles outside this scope are ignored.",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    requested = tuple(sorted(set(args.creators)))
    profiles = select_profiles(
        json.loads(args.old_profiles.read_text(encoding="utf-8")),
        json.loads((args.new_run / "voice-profile-five-v2.json").read_text(encoding="utf-8")),
        requested,
    )
    new_embeddings = _load_embeddings(args.new_run / "creator-adaptive-five-v2.sqlite")
    cross = calibrate_gates(profiles, new_embeddings)

    repository = CreatorAdaptiveRepository(output / "gate-validation.sqlite")
    adaptive = CreatorAdaptiveASRService(repository=repository)
    poisoning = []
    for actual in requested:
        for target in requested:
            same = actual == target
            identity = CreatorIdentityDecision(
                f"gate-{actual}-{target}", 0, 1000,
                IdentityState.CONFIRMED if same else IdentityState.CONFLICT,
                target if same else None, visual_score=1.0 if same else .0,
                voice_score=1.0 if same else .0, recording_prior=1.0 if same else .0,
                profile_version="creator_profile_five_v2",
            )
            result = adaptive.shadow_decide(
                recording_id=identity.recording_id, start_ms=0, end_ms=1000,
                generic_text=f"safe-{actual}", identity=identity,
                profile_version="creator_profile_five_v2", base_confidence=.9,
                candidate_terms=(f"poison-{target}",),
                historical_evidence={f"poison-{target}": 10},
                redecode=lambda _terms, actual=actual: (f"safe-{actual}", .95),
            )
            poisoning.append({
                "actual": actual, "target_memory": target, "same_creator": same,
                "action": result.action.value,
                "memory_blocked": not same and result.action.value == "GENERIC_FALLBACK",
            })
    poison_failures = [row for row in poisoning if not row["same_creator"] and not row["memory_blocked"]]
    dimension = len(requested)
    cross_attacks = dimension * (dimension - 1)
    receipt = {
        "status": "PASS" if cross["status"] == "PASS" and not poison_failures else "FAIL",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "production_status": "SHADOW_CALIBRATION_ONLY",
        "evaluation_status": "NO_HOLDOUT_PROFILE_GATE_AUDIT",
        "ground_truth_opened": False, "holdout_samples": 0,
        "creator_scope": list(requested),
        f"cross_creator_{dimension}x{dimension}": cross,
        f"poisoning_{dimension}x{dimension}": {
            "cases": len(poisoning), "cross_creator_attacks": cross_attacks,
            "blocked": sum(row["memory_blocked"] for row in poisoning),
            "failures": poison_failures, "rows": poisoning,
        },
    }
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2)
    (output / "creator-gate-receipt.json").write_text(serialized, encoding="utf-8")
    if requested == DEFAULT_CREATORS:
        (output / "five-creator-gate-receipt.json").write_text(serialized, encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
