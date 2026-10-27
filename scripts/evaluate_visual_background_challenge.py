from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
from typing import Any

import cv2
import numpy as np

from acfv.creator_visual_identity.encoders import OpenClipVisionEncoder, TransformersVisionEncoder, TimmVisionEncoder, TorchvisionEncoder
from acfv.creator_visual_identity.model import LinearProbeIdentityModel, PrototypeIdentityModel, VisualIdentityState


ROOT = Path(__file__).resolve().parents[1]


def encoder_for(name: str) -> Any:
    if name == "dinov2":
        return TransformersVisionEncoder("facebook/dinov2-small", kind="dinov2", local_files_only=True)
    if name == "openclip":
        return OpenClipVisionEncoder("ViT-B-32-quickgelu", pretrained="openai")
    if name == "resnet18-linear":
        return TorchvisionEncoder(weights_path=Path.home() / ".cache/torch/hub/checkpoints/resnet18-f37072fd.pth")
    if name == "mobilenetv3-linear":
        return TimmVisionEncoder("mobilenetv3_large_100.ra_in1k")
    if name == "convnext-tiny-linear":
        return TimmVisionEncoder("convnext_tiny.fb_in1k")
    raise ValueError(name)


def variants(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tight = cv2.imread(row["crop_path"], cv2.IMREAD_COLOR)
    capture = cv2.VideoCapture(row["source_path"])
    capture.set(cv2.CAP_PROP_POS_MSEC, int(row["timestamp_ms"]))
    ok, frame = capture.read()
    capture.release()
    if tight is None or not ok or frame is None:
        raise RuntimeError(f"unreadable challenge sample {row['sample_id']}")
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(value)) for value in row["bbox"]]
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    pad_x, pad_y = int(bw * .5), int(bh * .5)
    left, top, right, bottom = max(0, x1 - pad_x), max(0, y1 - pad_y), min(width, x2 + pad_x), min(height, y2 + pad_y)
    context = frame[top:bottom, left:right].copy()
    masked = np.zeros_like(context)
    mx1, my1, mx2, my2 = x1 - left, y1 - top, x2 - left, y2 - top
    masked[max(0, my1):min(masked.shape[0], my2), max(0, mx1):min(masked.shape[1], mx2)] = context[max(0, my1):min(context.shape[0], my2), max(0, mx1):min(context.shape[1], mx2)]
    return tight, context, masked


def summarize(model: Any, vectors: np.ndarray, rows: list[dict[str, Any]]) -> dict[str, Any]:
    strong = correct = known = unknown = unknown_rejected = 0
    per_creator: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row, vector in zip(rows, vectors):
        prediction = model.predict(vector)
        actual = row.get("creator_id") or "UNKNOWN"
        if actual == "UNKNOWN":
            unknown += 1
            unknown_rejected += int(prediction.state is not VisualIdentityState.STRONG)
        else:
            known += 1
            per_creator[actual]["samples"] += 1
        if prediction.state is VisualIdentityState.STRONG:
            strong += 1
            correct += int(prediction.creator_id == row.get("creator_id"))
            if actual != "UNKNOWN":
                per_creator[actual]["strong_correct"] += int(prediction.creator_id == actual)
    return {
        "samples": len(rows), "known": known, "unknown": unknown, "strong": strong,
        "strong_precision": correct / strong if strong else 1.0,
        "strong_known_coverage": correct / known if known else 0.0,
        "unknown_rejection": unknown_rejected / unknown if unknown else 1.0,
        "per_creator": {key: dict(value) for key, value in per_creator.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples-per-recording", type=int, default=50)
    args = parser.parse_args()
    selection = json.loads((args.benchmark / "visual-model-selection.json").read_text(encoding="utf-8"))
    winner = selection["winner"]
    model_path = args.benchmark / (f"{winner}-identity-model.json" if winner in {"dinov2", "openclip"} else f"{winner}-identity-model.joblib")
    model = PrototypeIdentityModel.load(model_path) if winner in {"dinov2", "openclip"} else LinearProbeIdentityModel.load(model_path)
    encoder = encoder_for(winner)
    all_rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    eligible = [row for row in all_rows if row["dataset_split"] == "holdout" or (row["dataset_split"] == "unknown" and row["track_group_id"] == "holdout-unknown")]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        grouped[row["recording_id"]].append(row)
    rng = random.Random(20261014)
    rows = []
    for values in grouped.values():
        rng.shuffle(values)
        rows.extend(values[:args.samples_per_recording])
    batches = {"tight_avatar_crop": [], "wide_context": [], "background_masked": []}
    for row in rows:
        tight, context, masked = variants(row)
        batches["tight_avatar_crop"].append(tight)
        batches["wide_context"].append(context)
        batches["background_masked"].append(masked)
    report = {"model": winner, "samples": len(rows), "conditions": {}}
    for condition, images in batches.items():
        vectors = encoder.encode(images, batch_size=32)
        report["conditions"][condition] = summarize(model, vectors, rows)
    tight = report["conditions"]["tight_avatar_crop"]
    masked = report["conditions"]["background_masked"]
    report["conclusion"] = {
        "background_leakage_flag": masked["strong_precision"] + .05 < tight["strong_precision"],
        "precision_delta_masked_minus_tight": masked["strong_precision"] - tight["strong_precision"],
        "coverage_delta_masked_minus_tight": masked["strong_known_coverage"] - tight["strong_known_coverage"],
        "scale_context_sensitivity": masked["strong_known_coverage"] + .10 < tight["strong_known_coverage"],
        "interpretation": "Precision does not show false-strong background leakage, but coverage loss under wide/masked context is reported separately as crop-scale sensitivity; human frame truth remains pending.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
