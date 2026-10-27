from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import time

import cv2
import numpy as np
import psutil
import torch

from acfv.creator_adaptive.models import AvatarIdentityObservation
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_identity import CreatorIdentityService
from acfv.creator_visual_identity.encoders import TorchvisionEncoder
from acfv.creator_visual_identity.model import CreatorVisualIdentityService, LinearProbeIdentityModel
from acfv.creator_visual_identity.provider import calibrated_observation_confidence
from acfv.providers.ultralytics_avatar import UltralyticsAvatarProvider


ROOT = Path(__file__).resolve().parents[1]
MODEL = Path(r"G:\Cliper\acfv\model\best.pt")
MEDIA = {
    "saruei": {
        "path": Path(r"G:\Cliper\acfv\var\processing\stream_monitor\stream_monitor\twitch\saruei\saruei-saruei-20251026-161020.mp4"),
        "regions": [(value, 60.0, 50) for value in (60, 840, 1620, 2400, 3180, 3960, 4740, 5520, 6300, 7080)],
    },
    "anny": {
        "path": Path(r"G:\Cliper\acfv\var\replay_tests\brat_2025-11-02_3min.mp4"),
        "regions": [(value, 36.0, 100) for value in (0, 36, 72, 108, 144)],
    },
}


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract(media: Path, regions: list[tuple[float, float, int]], output: Path) -> list[tuple[Path, int, int]]:
    rows = []
    for region_index, (start, duration, count) in enumerate(regions):
        region = output / f"region-{region_index:02d}"
        region.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(media),
            "-t", str(duration), "-vf", f"fps={count}/{duration},scale=960:-2", "-frames:v", str(count),
            "-q:v", "3", str(region / "%04d.jpg"),
        ], check=True)
        files = sorted(region.glob("*.jpg"))
        if len(files) != count:
            raise RuntimeError(f"expected {count} frames, got {len(files)} from {media}")
        rows.extend((path, int((start + (index + .5) * duration / count) * 1000), region_index) for index, path in enumerate(files))
    return rows


def crop(frame: np.ndarray, bbox: list[float] | tuple[float, ...], padding: float = .08) -> np.ndarray | None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (float(value) for value in bbox)
    px, py = (x2 - x1) * padding, (y2 - y1) * padding
    left, top, right, bottom = max(0, int(x1 - px)), max(0, int(y1 - py)), min(width, int(x2 + px)), min(height, int(y2 + py))
    value = frame[top:bottom, left:right]
    return value if value.size and min(value.shape[:2]) >= 48 else None


def contact_sheet(items: list[tuple[np.ndarray, str]], target: Path, limit: int) -> None:
    chosen = items[:limit]
    width, height, columns = 180, 140, 10
    canvas = np.zeros((((len(chosen) + columns - 1) // columns) * height, columns * width, 3), np.uint8)
    for index, (image, label) in enumerate(chosen):
        tile = cv2.resize(image, (width, height - 22), interpolation=cv2.INTER_AREA)
        x, y = index % columns * width, index // columns * height
        canvas[y:y + height - 22, x:x + width] = tile
        cv2.putText(canvas, label[:26], (x + 2, y + height - 6), cv2.FONT_HERSHEY_SIMPLEX, .31, (255, 255, 255), 1, cv2.LINE_AA)
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), canvas)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/creator-visual-identity-v1/real-validation")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    output = args.output.resolve()
    temporary = output / "sampled-frames"
    if temporary.exists():
        shutil.rmtree(temporary)
    presence = UltralyticsAvatarProvider(MODEL)
    encoder = TorchvisionEncoder(weights_path=Path.home() / ".cache/torch/hub/checkpoints/resnet18-f37072fd.pth")
    identity_model = LinearProbeIdentityModel.load(ROOT / "var/creator-visual-identity-v1/benchmark/resnet18-linear-identity-model.joblib")
    identity = CreatorVisualIdentityService(encoder, identity_model)
    repository = CreatorAdaptiveRepository(output / "creator-adaptive-v3.sqlite")
    span_service = CreatorIdentityService(repository=repository)
    model_version = f"{presence._model_version}+{identity_model.model_version}"
    span_service.register_label_mapping(mapping_version="creator-visual-v1", model_version=model_version, labels={"saruei": "saruei", "anny": "anny", "unknown": None, "ambiguous": None}, provenance={"source": "open-set visual benchmark", "profile_version": "creator_profile_v3"})
    process = psutil.Process()
    started = time.perf_counter()
    report = {"profile_version": "creator_profile_v3", "model_version": model_version, "thresholds": {"strong_score": identity_model.strong_score, "strong_margin": identity_model.strong_margin, "minimum_support": identity_model.min_support}, "creators": {}}
    all_spans = {}
    review_strong: list[tuple[np.ndarray, str]] = []
    review_uncertain: list[tuple[np.ndarray, str]] = []
    try:
        for creator, config in MEDIA.items():
            samples = extract(config["path"], config["regions"], temporary / creator)
            frames = [cv2.imread(str(path)) for path, _, _ in samples]
            timestamps = [timestamp for _, timestamp, _ in samples]
            presence_rows = []
            detect_started = time.perf_counter()
            for offset in range(0, len(frames), args.batch_size):
                presence_rows.extend(presence.identify_frames(frames[offset:offset + args.batch_size], timestamps[offset:offset + args.batch_size]))
            detect_elapsed = time.perf_counter() - detect_started
            crop_rows, crop_meta = [], []
            for frame, timestamp, detections in zip(frames, timestamps, presence_rows):
                usable = [row for row in detections if float(row["confidence"]) >= .70]
                if len(usable) != 1:
                    continue
                value = crop(frame, usable[0]["bbox"])
                if value is not None:
                    crop_rows.append(value); crop_meta.append((timestamp, usable[0]))
            encode_started = time.perf_counter()
            predictions = identity.identify_crops(crop_rows)
            encode_elapsed = time.perf_counter() - encode_started
            observations = []
            rows = []
            for visual_crop, (timestamp, detected), prediction in zip(crop_rows, crop_meta, predictions):
                label = prediction.creator_id or prediction.state.value.lower()
                observation = AvatarIdentityObservation(
                    label, calibrated_observation_confidence(prediction), timestamp, model_version,
                    "two-stage-creator-visual-identity", bbox=tuple(detected["bbox"]),
                    raw_metadata={
                        "raw_presence_label": detected["label"], "presence_confidence": detected["confidence"],
                        "identity_state": prediction.state.value, "identity_score": prediction.score,
                        "identity_margin": prediction.margin, "identity_support": prediction.support_score,
                        "second_creator_id": prediction.second_creator_id, "prototype_id": prediction.prototype_id,
                        "encoder_version": encoder.model_version, "detector_version": presence._model_version,
                        "identity_model_version": identity_model.model_version,
                    },
                )
                observations.append(observation)
                row = {"timestamp_ms": timestamp, "expected_creator": creator, "selected_creator": prediction.creator_id, "state": prediction.state.value, "score": prediction.score, "margin": prediction.margin, "support": prediction.support_score, "presence_confidence": detected["confidence"]}
                rows.append(row)
                target = review_strong if prediction.state.value == "STRONG" else review_uncertain
                target.append((visual_crop, f"{creator}->{prediction.creator_id or prediction.state.value} {timestamp/1000:.1f}s"))
            spans = span_service.aggregate_visual(creator + "-real-holdout", {"saruei": "saruei", "anny": "anny"}, observations, mapping_version="creator-visual-v1", max_gap_ms=2500, minimum_support_frames=3)
            counts = Counter(row["state"] for row in rows)
            strong = [row for row in rows if row["state"] == "STRONG"]
            report["creators"][creator] = {
                "source": str(config["path"]), "frames": len(frames), "regions": len(config["regions"]),
                "presence_single_dominant": len(crop_rows), "identity_states": dict(counts),
                "strong": len(strong), "strong_correct": sum(row["selected_creator"] == creator for row in strong),
                "strong_false": sum(row["selected_creator"] not in {None, creator} for row in strong),
                "strong_precision_proxy": sum(row["selected_creator"] == creator for row in strong) / len(strong) if strong else 1.0,
                "strong_coverage": sum(row["selected_creator"] == creator for row in strong) / len(frames),
                "presence_fps": len(frames) / detect_elapsed, "identity_fps": len(crop_rows) / encode_elapsed if encode_elapsed else 0,
                "predictions": rows,
            }
            all_spans[creator] = [asdict(span) | {"level": span.level.value} for span in spans]
        contact_sheet(review_strong, output / "human-review-strong-100.jpg", 100)
        contact_sheet(review_uncertain, output / "human-review-uncertain-50.jpg", 50)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    report["elapsed_s"] = time.perf_counter() - started
    report["ram_mb"] = process.memory_info().rss / 1048576
    report["gpu_peak_mb"] = torch.cuda.max_memory_allocated() / 1048576 if torch.cuda.is_available() else 0
    report["raw_media_mutations"] = 0
    report["official_transcript_mutations"] = 0
    report["ground_truth"] = "single-creator recording proxy; frame-level human review pending"
    dump(output / "creator-visual-real-validation.json", report)
    dump(output / "visual-identity-spans-real.json", all_spans)
    print(json.dumps({"thresholds": report["thresholds"], "creators": {key: {field: value[field] for field in ("frames", "presence_single_dominant", "identity_states", "strong", "strong_correct", "strong_false", "strong_precision_proxy", "strong_coverage", "presence_fps", "identity_fps")} for key, value in report["creators"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
