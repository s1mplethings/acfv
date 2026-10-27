from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from acfv.creator_visual_identity import CreatorVisualDatasetBuilder, RecordingSource
from acfv.providers.avatar_identity import ExistingAvatarModelAdapter


ROOT = Path(__file__).resolve().parents[1]


def sources(quality_root: Path, unknown_root: Path) -> list[RecordingSource]:
    return [
        RecordingSource("saruei", "saruei-clean-01", quality_root / "Saruei/01-8d310288/standard/clip_clean.mp4", "train", True, sample_fps=12),
        RecordingSource("saruei", "saruei-clean-02", quality_root / "Saruei/02-0c6e3e2a/standard/clip_clean.mp4", "validation", True, sample_fps=12),
        RecordingSource("saruei", "saruei-clean-03", quality_root / "Saruei/03-0e04994c/standard/clip_clean.mp4", "holdout", True, sample_fps=12),
        RecordingSource("anny", "anny-clean-01", quality_root / "anny/01-5a9caed4/standard/clip_clean.mp4", "train", True, sample_fps=8),
        RecordingSource("anny", "anny-clean-02", quality_root / "anny/02-0861efd7/standard/clip_clean.mp4", "train", True, sample_fps=8),
        RecordingSource("anny", "anny-clean-03", quality_root / "anny/03-5f5dd861/standard/clip_clean.mp4", "train", True, sample_fps=8),
        RecordingSource("anny", "anny-clean-04", quality_root / "anny/04-3ad97744/standard/clip_clean.mp4", "validation", True, sample_fps=12),
        RecordingSource("anny", "anny-clean-05", quality_root / "anny/05-877e635c/standard/clip_clean.mp4", "holdout", True, sample_fps=12),
        RecordingSource(None, "unknown-q8pilot-a", unknown_root / "Q8Pilot/a44ae0f8.mp4", "unknown", sample_fps=2, group_id="validation-unknown", allow_full_frame_unknown=True),
        RecordingSource(None, "unknown-q8pilot-b", unknown_root / "Q8Pilot/ee4ae953.mp4", "unknown", sample_fps=2, group_id="holdout-unknown", allow_full_frame_unknown=True),
        RecordingSource(None, "unknown-tpp-a", unknown_root / "twitchplayspokemon/646fc49d.mp4", "unknown", sample_fps=2, group_id="validation-unknown", allow_full_frame_unknown=True),
        RecordingSource(None, "unknown-tpp-b", unknown_root / "twitchplayspokemon/1f0cef20.mp4", "unknown", sample_fps=2, group_id="holdout-unknown", allow_full_frame_unknown=True),
    ]


def manifest_sources(
    plan_path: Path,
    receipts_path: Path,
    *,
    known_sample_fps: float,
    unknown_sample_fps: float,
) -> list[RecordingSource]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if receipts_path.is_dir():
        receipt_rows = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(receipts_path.glob("v2-download-*-receipt.json"))
        ]
    else:
        receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
        receipt_rows = list(receipts.get("rows", []))
    completed = {
        str(row["vod_id"]): row for row in receipt_rows
        if (row.get("status") == "DOWNLOADED" or row.get("result") == "PASS")
        and Path(str(row.get("local_path") or row.get("output_path") or "")).is_file()
    }
    result = []
    for item in plan.get("vods", plan.get("rows", [])):
        vod_id = str(item["vod_id"])
        receipt = completed.get(vod_id)
        if receipt is None:
            continue
        role = str(item["role"]).casefold()
        creator = str(item["creator"]).casefold() if role != "unknown" else None
        partition = str(item.get("unknown_partition") or "").casefold()
        group = f"{partition}-unknown" if role == "unknown" else vod_id
        result.append(RecordingSource(
            creator,
            vod_id,
            Path(receipt.get("local_path") or receipt["output_path"]),
            role,
            single_creator_confirmed=creator is not None,
            collab=False,
            sample_fps=known_sample_fps if creator else unknown_sample_fps,
            group_id=group,
            allow_full_frame_unknown=False,
        ))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var/creator-visual-identity-v1")
    parser.add_argument("--max-per-recording", type=int, default=None)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--model", type=Path, default=os.environ.get("ACFV_AVATAR_MODEL_PATH"))
    parser.add_argument("--legacy-quality-root", type=Path, default=os.environ.get("ACFV_LEGACY_VISUAL_QUALITY_ROOT"))
    parser.add_argument("--legacy-unknown-root", type=Path, default=os.environ.get("ACFV_LEGACY_VISUAL_UNKNOWN_ROOT"))
    parser.add_argument("--dataset-version", default="creator-visual-v1")
    parser.add_argument("--known-sample-fps", type=float, default=2.0)
    parser.add_argument("--unknown-sample-fps", type=float, default=1.0)
    args = parser.parse_args()
    if args.model is None:
        parser.error("--model or ACFV_AVATAR_MODEL_PATH is required")
    provider = ExistingAvatarModelAdapter(
        args.model,
        entrypoint=ROOT / "src/acfv/providers/ultralytics_avatar.py",
    )
    selected_sources = (
        manifest_sources(
            args.plan,
            args.receipts,
            known_sample_fps=args.known_sample_fps,
            unknown_sample_fps=args.unknown_sample_fps,
        )
        if args.plan and args.receipts else (
            sources(args.legacy_quality_root, args.legacy_unknown_root)
            if args.legacy_quality_root is not None and args.legacy_unknown_root is not None
            else parser.error(
                "legacy mode requires --legacy-quality-root and --legacy-unknown-root "
                "(or matching ACFV_LEGACY_VISUAL_* environment variables)"
            )
        )
    )
    builder = CreatorVisualDatasetBuilder(
        provider,
        args.output,
        dedup_hamming=2,
        dataset_version=args.dataset_version,
    )
    report = builder.build(selected_sources, max_samples_per_recording=args.max_per_recording)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
