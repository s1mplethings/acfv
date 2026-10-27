from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from acfv.human_review import HumanReviewRepository
from acfv.human_review.models import ReviewSample, ReviewTask


DATASET_ID = "MULTI_CREATOR_TWITCH_V1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipts", type=Path, required=True)
    parser.add_argument("--visual-manifest", type=Path, required=True)
    parser.add_argument("--asr-report", type=Path, required=True)
    parser.add_argument("--corpus-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    receipts = json.loads(args.receipts.read_text(encoding="utf-8"))
    corpus = json.loads(args.corpus_plan.read_text(encoding="utf-8"))
    roles = {str(row["vod_id"]): str(row["role"]) for row in corpus.get("vods") or []}
    media = {str(row["vod_id"]): str(row["local_path"]) for row in receipts.get("rows") or []}
    samples: list[ReviewSample] = []

    visual_counts: Counter[str] = Counter()
    for line in args.visual_manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        creator = str(row["creator_id"])
        if visual_counts[creator] >= 100:
            continue
        visual_counts[creator] += 1
        timestamp = int(row["timestamp_ms"])
        samples.append(ReviewSample(
            sample_id=f"{DATASET_ID}:identity:{creator}:{row['recording_id']}:{timestamp}",
            task=ReviewTask.IDENTITY, creator=creator, content_type="twitch_vod_probe",
            title=f"Identity · {creator} · {visual_counts[creator]:03d}",
            media_a=media[str(row["recording_id"])], start_ms=max(0, timestamp - 2000), end_ms=timestamp + 2000,
            prompt={"predicted_creator": creator, "context": "New independent Twitch HOLDOUT probe"},
            private={"dataset_id": DATASET_ID, "split": roles.get(str(row["recording_id"]), "PROBE_UNFINALIZED"), "crop_path": row["crop_path"]},
            source_path=str(args.visual_manifest),
        ))

    asr = json.loads(args.asr_report.read_text(encoding="utf-8"))
    asr_counts: Counter[str] = Counter()
    trusted_counts: Counter[str] = Counter()
    for row in asr.get("rows") or []:
        creator = str(row["creator"])
        for index, segment in enumerate(row.get("segments") or []):
            if asr_counts[creator] < 50:
                asr_counts[creator] += 1
                samples.append(ReviewSample(
                    sample_id=f"{DATASET_ID}:asr:{creator}:{row['vod_id']}:{index:03d}",
                    task=ReviewTask.ASR, creator=creator, content_type="twitch_vod_probe",
                    title=f"ASR · {creator} · {asr_counts[creator]:03d}", media_a=media[str(row["vod_id"])],
                    start_ms=int(segment["start_ms"]), end_ms=int(segment["end_ms"]),
                    prompt={"current_asr": segment["text"], "context": "Blind human transcript and optional voice-style review"},
                    private={"dataset_id": DATASET_ID, "split": roles.get(str(row["vod_id"]), "PROBE_UNFINALIZED"), "engineering_confidence": segment["engineering_confidence"]},
                    source_path=str(args.asr_report),
                ))
            if trusted_counts[creator] < 50:
                trusted_counts[creator] += 1
                samples.append(ReviewSample(
                    sample_id=f"{DATASET_ID}:trusted:{creator}:{row['vod_id']}:{index:03d}",
                    task=ReviewTask.TRUSTED_SPEECH, creator=creator, content_type="twitch_vod_probe",
                    title=f"Trusted candidate · {creator} · {trusted_counts[creator]:03d}", media_a=media[str(row["vod_id"])],
                    start_ms=int(segment["start_ms"]), end_ms=int(segment["end_ms"]),
                    prompt={"predicted_creator": creator, "transcript": segment["text"], "context": "HOLDOUT review only; cannot enter TRAIN memory"},
                    private={"dataset_id": DATASET_ID, "split": roles.get(str(row["vod_id"]), "PROBE_UNFINALIZED"), "memory_eligible": False},
                    source_path=str(args.asr_report),
                ))

    metadata = {
        "dataset_version": DATASET_ID, "active_dataset_id": DATASET_ID,
        "sample_count": len(samples), "counts": dict(Counter(row.task.value for row in samples)),
        "creators": sorted({row.creator for row in samples}),
        "old_annotations_policy": "MERGE_ONLY_NEVER_REPLACE",
        "human_ground_truth": "PENDING", "adaptive_samples": 0,
        "adaptive_reason": "No TRAIN memory for new creators while bulk corpus is storage-blocked",
        "unfinalized_probe_creator": [row["creator"] for row in receipts.get("rows") or [] if str(row["vod_id"]) not in roles],
        "source_hashes": {"receipts": sha256(args.receipts), "visual": sha256(args.visual_manifest), "asr": sha256(args.asr_report), "corpus_plan": sha256(args.corpus_plan)},
    }
    repository = HumanReviewRepository(args.output / "human_review_multi_creator_v1.sqlite")
    inserted = repository.merge_dataset(samples, metadata)
    repository.close()
    public_samples = [{
        "sample_id": row.sample_id, "task": row.task.value, "creator": row.creator,
        "content_type": row.content_type, "start_ms": row.start_ms, "end_ms": row.end_ms,
        "dataset_id": DATASET_ID,
    } for row in samples]
    (args.output / "human-review-dataset-manifest.json").write_text(
        json.dumps({**metadata, "inserted": inserted, "samples": public_samples}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**metadata, "inserted": inserted}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
