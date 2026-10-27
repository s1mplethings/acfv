from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time
from typing import Any

import cv2
import psutil
import torch

from acfv.creator_adaptive.models import AvatarIdentityObservation
from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.creator_identity import CreatorIdentityService
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


def dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract(media: Path, regions: list[tuple[float, float, int]], output: Path) -> list[tuple[Path, int, int]]:
    rows: list[tuple[Path, int, int]] = []
    for region_index, (start, duration, count) in enumerate(regions):
        region = output / f"region-{region_index:02d}"
        region.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start),
            "-i", str(media), "-t", str(duration), "-vf", f"fps={count}/{duration},scale=960:-2",
            "-frames:v", str(count), "-q:v", "3", str(region / "%04d.jpg"),
        ]
        subprocess.run(command, check=True)
        files = sorted(region.glob("*.jpg"))
        if len(files) != count:
            raise RuntimeError(f"Expected {count} frames in region {region_index}, got {len(files)}")
        for index, path in enumerate(files):
            timestamp_ms = int((start + (index + 0.5) * duration / count) * 1000)
            rows.append((path, timestamp_ms, region_index))
    return rows


def infer(provider: UltralyticsAvatarProvider, samples: list[tuple[Path, int, int]], batch_size: int) -> tuple[list[AvatarIdentityObservation], dict[str, Any]]:
    observations: list[AvatarIdentityObservation] = []
    per_frame: list[dict[str, Any]] = []
    start = time.perf_counter()
    for offset in range(0, len(samples), batch_size):
        batch = samples[offset:offset + batch_size]
        frames = [cv2.imread(str(path)) for path, _, _ in batch]
        if any(frame is None for frame in frames):
            raise RuntimeError("OpenCV failed to read an extracted validation frame")
        outputs = provider.identify_frames(frames, [timestamp for _, timestamp, _ in batch])
        for (path, timestamp, region), raw_rows in zip(batch, outputs):
            frame_rows = []
            for raw in raw_rows:
                observation = AvatarIdentityObservation(
                    creator_external_id=str(raw["label"]), confidence=float(raw["confidence"]),
                    timestamp_ms=timestamp, model_version=str(raw["model_version"]),
                    provider=str(raw["provider"]), bbox=tuple(raw["bbox"]),
                    raw_metadata=dict(raw["raw_metadata"]),
                )
                observations.append(observation)
                frame_rows.append({"label": observation.creator_external_id, "confidence": observation.confidence, "bbox": list(observation.bbox or ())})
            per_frame.append({"sample": path.name, "timestamp_ms": timestamp, "region": region, "predictions": frame_rows})
    elapsed = time.perf_counter() - start
    return observations, {"elapsed_s": elapsed, "fps": len(samples) / elapsed, "frames": per_frame}


def summarize(samples: list[tuple[Path, int, int]], observations: list[AvatarIdentityObservation], detail: dict[str, Any]) -> dict[str, Any]:
    confidences = [row.confidence for row in observations]
    detected_timestamps = {row.timestamp_ms for row in observations}
    labels = Counter(row.creator_external_id for row in observations)
    return {
        "frames": len(samples),
        "regions": len({region for _, _, region in samples}),
        "detected_frames": sum(timestamp in detected_timestamps for _, timestamp, _ in samples),
        "unknown_identity_frames": len(samples),
        "identity_predictions": 0,
        "wrong_label_against_recording_prior": "NOT_APPLICABLE_PRESENCE_ONLY_MODEL",
        "prediction_labels": dict(labels),
        "confidence": {
            "min": min(confidences) if confidences else None,
            "median": statistics.median(confidences) if confidences else None,
            "mean": statistics.fmean(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
            "p10": sorted(confidences)[max(0, int(len(confidences) * .1) - 1)] if confidences else None,
            "p90": sorted(confidences)[min(len(confidences) - 1, int(len(confidences) * .9))] if confidences else None,
        },
        "temporal_presence_consistency": len(detected_timestamps) / len(samples),
        "elapsed_s": detail["elapsed_s"],
        "batch_fps": detail["fps"],
        "raw_prediction_semantics": "vtuber_presence_not_creator_identity",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--output", type=Path, default=ROOT / "var" / "avatar-phase3-final")
    args = parser.parse_args()
    output = args.output.resolve()
    temporary = output / "sampled-frames"
    if temporary.exists():
        shutil.rmtree(temporary)
    process = psutil.Process()
    ram_before = process.memory_info().rss
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    load_start = time.perf_counter()
    provider = UltralyticsAvatarProvider(MODEL)
    provider._load()
    load_elapsed = time.perf_counter() - load_start
    ram_after = process.memory_info().rss
    report: dict[str, Any] = {
        "model": str(MODEL), "device": "cuda:0" if torch.cuda.is_available() else "cpu",
        "load_time_s": load_elapsed, "load_ram_delta_mb": (ram_after - ram_before) / 1048576,
        "identity_capable": False, "class_mapping": {"0": "vtuber"}, "creators": {},
    }
    all_spans: dict[str, Any] = {}
    repository = CreatorAdaptiveRepository(output / "validation.sqlite")
    service = CreatorIdentityService(repository=repository)
    service.register_label_mapping(
        mapping_version="recovered-vtuber-presence-v1", model_version=provider._model_version,
        labels={"vtuber": None}, provenance={"source": "checkpoint metadata", "identity_capable": False},
    )
    try:
        for creator, config in MEDIA.items():
            samples = extract(config["path"], config["regions"], temporary / creator)
            observations, detail = infer(provider, samples, args.batch_size)
            summary = summarize(samples, observations, detail)
            spans = service.aggregate_visual(
                creator, {}, observations, mapping_version="recovered-vtuber-presence-v1",
                max_gap_ms=2500, minimum_support_frames=3,
            )
            service.record_avatar_observations(creator, {}, observations, mapping_version="recovered-vtuber-presence-v1")
            summary["visual_spans"] = len(spans)
            summary["visual_levels"] = dict(Counter(span.level.value for span in spans))
            report["creators"][creator] = summary
            all_spans[creator] = [asdict(span) | {"level": span.level.value} for span in spans]
            dump(output / f"avatar-frame-inference-{creator}.json", detail)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    report["gpu_peak_mb"] = torch.cuda.max_memory_allocated() / 1048576 if torch.cuda.is_available() else 0.0
    report["ram_final_mb"] = process.memory_info().rss / 1048576
    dump(output / "avatar-real-validation.json", report)
    dump(output / "visual-identity-spans.json", all_spans)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
