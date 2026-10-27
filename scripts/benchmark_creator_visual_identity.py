from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
from typing import Any
import gc

import cv2
import numpy as np

from acfv.creator_visual_identity.encoders import OpenClipVisionEncoder, TransformersVisionEncoder, TimmVisionEncoder, TorchvisionEncoder, timed_encode
from acfv.creator_visual_identity.model import LinearProbeIdentityModel, PrototypeIdentityModel, VisualIdentityState


ROOT = Path(__file__).resolve().parents[1]


def load_manifest(path: Path) -> tuple[list[dict[str, Any]], list[np.ndarray]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    images = []
    for row in rows:
        image = cv2.imread(row["crop_path"], cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"dataset manifest contains an unreadable crop: {row['crop_path']}")
        # Every benchmark encoder resizes to roughly 224px.  Retaining source
        # resolution for thousands of crops wastes many GB without changing
        # model input; keep the manifest's original dimensions as provenance.
        images.append(cv2.resize(image, (256, 256), interpolation=cv2.INTER_AREA))
    return rows, images


def raw_prediction(model: Any, vector: np.ndarray) -> tuple[str, float, float]:
    if isinstance(model, PrototypeIdentityModel):
        value = PrototypeIdentityModel._normalize(vector)[0]
        ranked = []
        for creator, prototypes in model.prototypes.items():
            ranked.append((float(np.max(prototypes @ value)), creator))
        ranked.sort(reverse=True)
        return ranked[0][1], ranked[0][0], ranked[0][0] - ranked[1][0]
    value = PrototypeIdentityModel._normalize(vector)
    probabilities = model.classifier.predict_proba(value)[0]
    order = np.argsort(probabilities)[::-1]
    return str(model.classifier.classes_[order[0]]), float(probabilities[order[0]]), float(probabilities[order[0]] - probabilities[order[1]])


def calibrate(model: Any, vectors: np.ndarray, rows: list[dict[str, Any]]) -> tuple[float, float, dict[str, Any]]:
    eligible = [index for index, row in enumerate(rows) if row["dataset_split"] == "validation" or (row["dataset_split"] == "unknown" and row["track_group_id"] == "validation-unknown")]
    raw = [raw_prediction(model, vectors[index]) for index in eligible]
    if isinstance(model, LinearProbeIdentityModel):
        known_support, unknown_support = [], []
        for index, prediction in zip(eligible, raw):
            support = float(vectors[index] @ model.support_prototypes[prediction[0]])
            (known_support if rows[index]["creator_id"] is not None else unknown_support).append(support)
        if known_support and unknown_support and min(known_support) > max(unknown_support):
            model.min_support = (min(known_support) + max(unknown_support)) / 2
        elif unknown_support:
            model.min_support = min(.99, max(unknown_support) + .001)
    # Do not form the Cartesian product of every observed score and margin:
    # thousands of validation rows make that O(n^3).  A fixed grid plus bounded
    # observed quantiles preserves data-adaptive operating points in O(n).
    score_values = np.asarray([value[1] for value in raw], dtype=np.float32)
    margin_values = np.asarray([value[2] for value in raw], dtype=np.float32)
    quantiles = np.linspace(0, 1, 21)
    score_grid = sorted(set(np.linspace(.45, .99, 55).round(3).tolist() + np.quantile(score_values, quantiles).round(4).tolist()))
    margin_grid = sorted(set(np.linspace(0, .60, 61).round(3).tolist() + np.quantile(margin_values, quantiles).round(4).tolist()))
    best: tuple[tuple[int, float, float, float], float, float, dict[str, Any]] | None = None
    for score in score_grid:
        for margin in margin_grid:
            accepted = [(idx, prediction) for idx, prediction in zip(eligible, raw) if prediction[1] >= score and prediction[2] >= margin and (not isinstance(model, LinearProbeIdentityModel) or float(vectors[idx] @ model.support_prototypes[prediction[0]]) >= model.min_support)]
            false = sum(rows[idx]["creator_id"] != prediction[0] for idx, prediction in accepted)
            correct = len(accepted) - false
            known = sum(rows[idx]["creator_id"] is not None for idx in eligible)
            unknown = sum(rows[idx]["creator_id"] is None for idx in eligible)
            unknown_accepted = sum(rows[idx]["creator_id"] is None for idx, _ in accepted)
            metrics = {
                "samples": len(eligible), "known": known, "unknown": unknown,
                "strong": len(accepted), "strong_correct": correct, "strong_false": false,
                "strong_precision": correct / len(accepted) if accepted else 1.0,
                "strong_known_coverage": correct / known if known else 0.0,
                "unknown_rejection": 1 - unknown_accepted / unknown if unknown else 1.0,
            }
            # A zero false-strong operating point is mandatory; then maximize useful
            # coverage, unknown rejection, and margin while preferring lower score.
            rank = (-false, metrics["strong_known_coverage"], metrics["unknown_rejection"], -score)
            if best is None or rank > best[0]:
                best = (rank, score, margin, metrics)
    assert best is not None
    return best[1], best[2], best[3]


def set_thresholds(model: Any, score: float, margin: float) -> None:
    model.strong_score = score
    model.strong_margin = margin
    model.probable_score = max(.35, score - .15)
    model.probable_margin = max(.01, margin - .05)


def evaluate(model: Any, vectors: np.ndarray, rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [index for index, row in enumerate(rows) if row["dataset_split"] == "holdout" or (row["dataset_split"] == "unknown" and row["track_group_id"] == "holdout-unknown")]
    results = []
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    creator_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    group_top1: dict[str, list[str]] = defaultdict(list)
    for index in eligible:
        row = rows[index]
        top1, raw_score, raw_margin = raw_prediction(model, vectors[index])
        prediction = model.predict(vectors[index])
        actual = row["creator_id"] or "UNKNOWN"
        strong_label = prediction.creator_id if prediction.state is VisualIdentityState.STRONG else "REJECT"
        confusion[actual][strong_label] += 1
        group_top1[row["track_group_id"]].append(top1)
        if row["creator_id"]:
            creator_stats[actual]["samples"] += 1
            creator_stats[actual]["top1_correct"] += int(top1 == actual)
            creator_stats[actual]["strong_correct"] += int(strong_label == actual)
            creator_stats[actual]["strong_wrong"] += int(strong_label not in {actual, "REJECT"})
        results.append({"actual": actual, "top1": top1, "score": raw_score, "margin": raw_margin, "support": prediction.support_score, "state": prediction.state.value, "selected": prediction.creator_id})
    known = [row for row in results if row["actual"] != "UNKNOWN"]
    unknown = [row for row in results if row["actual"] == "UNKNOWN"]
    strong = [row for row in results if row["state"] == "STRONG"]
    strong_correct = [row for row in strong if row["selected"] == row["actual"]]
    temporal_agree, transitions = 0, 0
    for values in group_top1.values():
        temporal_agree += sum(a == b for a, b in zip(values, values[1:]))
        transitions += max(0, len(values) - 1)
    all_known = np.asarray([vectors[index] for index in eligible if rows[index]["creator_id"] is not None])
    all_labels = [rows[index]["creator_id"] for index in eligible if rows[index]["creator_id"] is not None]
    same, cross = [], []
    for left in range(len(all_known)):
        for right in range(left + 1, min(len(all_known), left + 75)):
            (same if all_labels[left] == all_labels[right] else cross).append(float(all_known[left] @ all_known[right]))
    return {
        "samples": len(results), "known_samples": len(known), "unknown_samples": len(unknown),
        "closed_set_top1": sum(row["top1"] == row["actual"] for row in known) / len(known) if known else 0,
        "strong_precision": len(strong_correct) / len(strong) if strong else 1.0,
        "strong_coverage": len(strong_correct) / len(known) if known else 0,
        "false_strong_identity_rate": (len(strong) - len(strong_correct)) / len(results) if results else 0,
        "unknown_rejection": sum(row["state"] != "STRONG" for row in unknown) / len(unknown) if unknown else 1.0,
        "temporal_top1_consistency": temporal_agree / transitions if transitions else 1.0,
        "margin": summary([row["margin"] for row in results]),
        "same_creator_similarity": summary(same), "cross_creator_similarity": summary(cross),
        "per_creator": {creator: {
            **values,
            "recall_top1": values["top1_correct"] / values["samples"],
            "recall_strong": values["strong_correct"] / values["samples"],
        } for creator, values in creator_stats.items()},
        "confusion_matrix_strong": {key: dict(value) for key, value in confusion.items()},
        "rows": results,
    }


def summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0, "median": 0, "max": 0}
    return {"min": min(values), "median": float(np.median(values)), "max": max(values)}


def contact_sheet(rows: list[dict[str, Any]], target: Path, *, limit: int = 100) -> None:
    rng = random.Random(20261013)
    chosen = list(rows)
    rng.shuffle(chosen)
    chosen = chosen[:limit]
    tile_w, tile_h, columns = 180, 140, 10
    canvas = np.zeros((((len(chosen) + columns - 1) // columns) * tile_h, columns * tile_w, 3), dtype=np.uint8)
    for index, row in enumerate(chosen):
        image = cv2.imread(row["crop_path"])
        if image is None:
            continue
        image = cv2.resize(image, (tile_w, tile_h - 22), interpolation=cv2.INTER_AREA)
        x, y = index % columns * tile_w, index // columns * tile_h
        canvas[y:y + tile_h - 22, x:x + tile_w] = image
        cv2.putText(canvas, f"{row['recording_id']} {row['timestamp_ms']/1000:.1f}s", (x + 2, y + tile_h - 6), cv2.FONT_HERSHEY_SIMPLEX, .28, (255, 255, 255), 1, cv2.LINE_AA)
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), canvas)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "var/creator-visual-identity-v1/visual-dataset-manifest.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "var/creator-visual-identity-v1/benchmark")
    parser.add_argument("--supplemental-train-manifest", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, images = load_manifest(args.manifest)
    supplemental_count = 0
    if args.supplemental_train_manifest:
        extra_rows, extra_images = load_manifest(args.supplemental_train_manifest)
        extra = [
            (row, image) for row, image in zip(extra_rows, extra_images)
            if row.get("dataset_split") == "train" and row.get("creator_id") == "anny"
        ]
        supplemental_count = len(extra)
        rows.extend(row for row, _ in extra)
        images.extend(image for _, image in extra)
    sheet_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        # Unknown Creator names are intentionally absent from classifier labels;
        # the VOD/recording id still gives each open-set Creator its own sheet.
        label = str(row.get("creator_id") or f"unknown-{row['recording_id']}")
        sheet_groups[f"{label}-{row['dataset_split']}"].append(row)
    for label, group in sheet_groups.items():
        contact_sheet(group, args.output / "contact-sheets" / f"{label}.jpg")
    train = [index for index, row in enumerate(rows) if row["dataset_split"] == "train" and row["creator_id"]]
    # Construct one encoder at a time.  Holding DINOv2, CLIP, ResNet and both
    # timm backbones on the GPU together can exhaust consumer VRAM before the
    # first benchmark batch is encoded.
    candidates = [
        ("dinov2", lambda: TransformersVisionEncoder("facebook/dinov2-small", kind="dinov2", local_files_only=True), "prototype"),
        ("openclip", lambda: OpenClipVisionEncoder("ViT-B-32-quickgelu", pretrained="openai"), "prototype"),
        ("resnet18-linear", lambda: TorchvisionEncoder(weights_path=Path.home() / ".cache/torch/hub/checkpoints/resnet18-f37072fd.pth"), "linear"),
        ("mobilenetv3-linear", lambda: TimmVisionEncoder("mobilenetv3_large_100.ra_in1k"), "linear"),
        ("convnext-tiny-linear", lambda: TimmVisionEncoder("convnext_tiny.fb_in1k"), "linear"),
    ]
    reports: dict[str, Any] = {}
    for name, encoder_factory, method in candidates:
        encoder = encoder_factory()
        cache = args.output / f"{name}-embeddings.npz"
        if cache.is_file():
            vectors = np.load(cache)["embeddings"]
            performance = json.loads((args.output / f"{name}-performance.json").read_text(encoding="utf-8"))
        else:
            vectors, performance = timed_encode(encoder, images, batch_size=32)
            np.savez_compressed(cache, embeddings=vectors)
            (args.output / f"{name}-performance.json").write_text(json.dumps(performance, indent=2), encoding="utf-8")
        labels = [rows[index]["creator_id"] for index in train]
        if method == "prototype":
            model = PrototypeIdentityModel.fit(vectors[train], labels, encoder_version=encoder.model_version, prototypes_per_creator=6)
        else:
            model = LinearProbeIdentityModel.fit(vectors[train], labels, encoder_version=encoder.model_version)
        score, margin, validation = calibrate(model, vectors, rows)
        set_thresholds(model, score, margin)
        holdout = evaluate(model, vectors, rows)
        reports[name] = {
            "encoder_version": encoder.model_version, "embedding_dim": int(vectors.shape[1]),
            "method": method, "strong_score": score, "strong_margin": margin,
            "minimum_support": getattr(model, "min_support", None),
            "validation": validation, "holdout": holdout, "performance": performance,
            "prototype_counts": {key: len(value) for key, value in model.prototypes.items()} if method == "prototype" else {},
            "supplemental_historical_anny_train_samples": supplemental_count,
        }
        curves = {}
        for fraction in (.25, .50, 1.0):
            subset = []
            for creator in sorted(set(labels)):
                creator_rows = [index for index in train if rows[index]["creator_id"] == creator]
                subset.extend(creator_rows[:max(1, int(round(len(creator_rows) * fraction)))])
            curve_labels = [rows[index]["creator_id"] for index in subset]
            curve_model = (
                PrototypeIdentityModel.fit(vectors[subset], curve_labels, encoder_version=encoder.model_version, prototypes_per_creator=6)
                if method == "prototype"
                else LinearProbeIdentityModel.fit(vectors[subset], curve_labels, encoder_version=encoder.model_version)
            )
            curve_score, curve_margin, curve_validation = calibrate(curve_model, vectors, rows)
            set_thresholds(curve_model, curve_score, curve_margin)
            curves[str(fraction)] = {
                "train_samples": len(subset),
                "validation": curve_validation,
                "holdout": evaluate(curve_model, vectors, rows),
            }
        reports[name]["learning_curve"] = curves
        if isinstance(model, LinearProbeIdentityModel):
            # Binary softmax margins below 0.20 are too close to a coin flip for
            # durable Creator memory. This model-family safety floor is applied
            # after candidate evaluation and before the production artifact.
            model.strong_margin = max(model.strong_margin, .20)
            reports[name]["production_safety_floor"] = {"strong_margin": .20, "reason": "reject near-boundary binary softmax predictions"}
            reports[name]["production_holdout"] = evaluate(model, vectors, rows)
        if isinstance(model, PrototypeIdentityModel):
            model.save(args.output / f"{name}-identity-model.json")
        else:
            model.save(args.output / f"{name}-identity-model.joblib")
        del model, vectors, encoder
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    has_holdout = any(report["holdout"]["samples"] for report in reports.values())
    evaluation = {
        key: report.get("production_holdout", report["holdout"]) if has_holdout else report["validation"]
        for key, report in reports.items()
    }
    ranked = sorted(reports, key=lambda key: (
        evaluation[key]["strong_precision"], evaluation[key]["unknown_rejection"],
        evaluation[key].get("strong_coverage", evaluation[key].get("strong_known_coverage", 0.0)),
        evaluation[key].get("closed_set_top1", 0.0),
        reports[key]["performance"]["fps"],
    ), reverse=True)
    selection = {
        "winner": ranked[0], "ranking": ranked,
        "policy": ["strong_precision", "unknown_rejection", "strong_coverage", "holdout_top1", "fps"] if has_holdout else ["validation_strong_precision", "validation_strong_known_coverage", "fps"],
        "production_status": "SHADOW_VISUAL_IDENTITY" if has_holdout else "SHADOW_CALIBRATION_ONLY",
        "evaluation_status": "INDEPENDENT_HOLDOUT" if has_holdout else "VALIDATION_ONLY_NO_HOLDOUT_CLAIM",
        "human_precision_status": "NOT_EVALUATED",
        "training_data_note": (
            "New Twitch Saruei TRAIN plus historical anny TRAIN only; current Twitch exposes one anny archive, "
            "which remains new-VOD HOLDOUT. All validation/holdout metrics are from NEW_TWITCH_VALIDATION_V1."
            if supplemental_count else (
                "TRAIN plus independent-by-VOD VALIDATION; no HOLDOUT rows were opened or evaluated."
                if not has_holdout else "NEW_TWITCH_VALIDATION_V1 only"
            )
        ),
    }
    (args.output / "visual-model-benchmark.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "visual-model-selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "visual-holdout-results.json").write_text(json.dumps({key: value.get("production_holdout", value["holdout"]) for key, value in reports.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "visual-evaluation-results.json").write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selection": selection, "summary": evaluation}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
