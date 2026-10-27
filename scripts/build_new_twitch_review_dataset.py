from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "creator_profile_v4_new_twitch"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--adaptive-review", type=Path, default=ROOT / "var/new-twitch-validation/human-review/human-review-v4.json")
    parser.add_argument("--output", type=Path, default=ROOT / "var/new-twitch-validation/human-review/human-review-v4.json")
    args = parser.parse_args()
    selection = json.loads((args.benchmark / "visual-model-selection.json").read_text(encoding="utf-8"))
    winner = selection["winner"]
    holdout = json.loads((args.benchmark / "visual-holdout-results.json").read_text(encoding="utf-8"))[winner]
    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    eligible = [row for row in rows if row["dataset_split"] == "holdout" or (row["dataset_split"] == "unknown" and row["track_group_id"] == "holdout-unknown")]
    predictions = holdout["rows"]
    if len(eligible) != len(predictions):
        raise RuntimeError("holdout prediction order/count does not match manifest")
    paired = list(zip(eligible, predictions))
    buckets: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {
        "saruei": [], "anny": [], "unknown": [], "ambiguous": [],
    }
    for row, prediction in paired:
        creator = row.get("creator_id")
        if creator in {"saruei", "anny"} and prediction["state"] == "STRONG":
            buckets[creator].append((row, prediction))
        if creator is None:
            buckets["unknown"].append((row, prediction))
        if prediction["state"] != "STRONG" or prediction["margin"] < .20:
            buckets["ambiguous"].append((row, prediction))
    rng = random.Random(20261014)
    limits = {"saruei": 100, "anny": 100, "unknown": 100, "ambiguous": 50}
    chosen = []
    selected_ids: set[str] = set()
    for bucket, values in buckets.items():
        values = [value for value in values if value[0]["sample_id"] not in selected_ids]
        rng.shuffle(values)
        selected = values[:limits[bucket]]
        chosen.extend((bucket, *value) for value in selected)
        selected_ids.update(value[0]["sample_id"] for value in selected)
    payload = (
        json.loads(args.adaptive_review.read_text(encoding="utf-8"))
        if args.adaptive_review.is_file() else
        {"schema_version": 4, "dataset_id": "NEW_TWITCH_VALIDATION_V1", "profile_version": PROFILE, "identity": [], "trusted_speech": [], "adaptive_asr": []}
    )
    payload["dataset_id"] = "NEW_TWITCH_VALIDATION_V1"
    payload["visual_model"] = winner
    payload["human_ground_truth"] = "PENDING"
    payload["identity"] = []
    for index, (bucket, row, prediction) in enumerate(chosen, 1):
        payload["identity"].append({
            "id": f"new-twitch-visual-{index:04d}", "creator": row.get("creator_id") or "UNKNOWN",
            "creator_id": row.get("creator_id") or "", "recording_id": row["recording_id"],
            "media": row["source_path"], "start_ms": row["timestamp_ms"], "end_ms": row["timestamp_ms"] + 1000,
            "predicted_creator": prediction.get("selected") or "UNKNOWN", "profile_version": PROFILE,
            "visual_score": prediction["score"], "context": f"bucket={bucket} state={prediction['state']} margin={prediction['margin']:.4f}; RECORDING_LEVEL_PROXY",
        })
    payload["selection_counts"] = {key: sum(item[0] == key for item in chosen) for key in limits}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dataset_id": payload["dataset_id"], "visual_model": winner, "counts": payload["selection_counts"], "adaptive_asr": len(payload.get("adaptive_asr", [])), "trusted_speech": len(payload.get("trusted_speech", []))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
