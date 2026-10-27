from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


ACTIVE_CREATORS = ("saruei", "atelieranoko", "snuffy", "laphipi")
ALLOWED_ROLES = {"TRAIN", "VALIDATION"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _even_times(duration_ms: int, count: int) -> list[int]:
    start, end = min(60_000, duration_ms // 10), max(60_000, duration_ms - 60_000)
    if end <= start:
        return [duration_ms // 2]
    return [int(start + (end - start) * index / max(1, count - 1)) for index in range(count)]


def _manifest_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "vods", "selection", "recordings", "entries"):
        if isinstance(payload.get(key), list):
            return [dict(row) for row in payload[key]]
    return []


def build_calibration(
    *, visual_rows: list[dict[str, Any]], adaptive_review: dict[str, Any],
    corpus_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    roles = {
        str(row.get("vod_id") or row.get("external_vod_id") or row.get("recording_id")): str(row.get("role", "")).upper()
        for row in corpus_rows
    }
    roles.update({
        str(row["recording_id"]): str(row.get("dataset_split", "")).upper()
        for row in visual_rows if row.get("recording_id")
    })
    tasks: list[dict[str, Any]] = []
    for creator in ACTIVE_CREATORS[1:]:
        candidates = [
            row for row in visual_rows
            if row.get("creator_id") == creator and str(row.get("dataset_split", "")).lower() in {"train", "validation"}
        ]
        for row in candidates[:30]:
            tasks.append({
                "task": "VISUAL_STRONG", "creator": creator,
                "recording_id": str(row["recording_id"]), "start_ms": int(row["timestamp_ms"]),
                "media": row.get("crop_path"), "label": None,
            })
        trusted = [row for row in adaptive_review.get("trusted_speech", []) if row.get("creator_id") == creator]
        for row in trusted[:20]:
            tasks.append({
                "task": "TRUSTED_SPEECH", "creator": creator,
                "recording_id": str(row["recording_id"]), "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]), "media": row.get("media"), "label": None,
            })
        adaptive = [row for row in adaptive_review.get("adaptive_asr", []) if row.get("creator_id") == creator]
        for row in adaptive[:30]:
            tasks.append({
                "task": "ADAPTIVE_ASR", "creator": creator,
                "recording_id": str(row["recording_id"]), "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]), "media": row.get("media"),
                "human_transcript": None, "choice": None,
            })
    saruei_sources = [
        row for row in corpus_rows
        if str(row.get("creator") or row.get("creator_id", "")).casefold() == "saruei"
        and str(row.get("role", "")).upper() in ALLOWED_ROLES
    ]
    if not saruei_sources:
        raise ValueError("saruei TRAIN/VALIDATION corpus evidence is required")
    source = next((row for row in saruei_sources if str(row.get("role", "")).upper() == "VALIDATION"), saruei_sources[0])
    recording_id = str(source.get("vod_id") or source.get("external_vod_id") or source.get("recording_id"))
    duration_ms = int(source.get("duration_ms") or int(source.get("duration_seconds", 0)) * 1000)
    media = source.get("raw_path") or source.get("local_path") or source.get("path") or source.get("media_path")
    for task, count in (("VISUAL_STRONG", 30), ("TRUSTED_SPEECH", 20), ("ADAPTIVE_ASR", 30)):
        for timestamp in _even_times(duration_ms, count):
            row = {
                "task": task, "creator": "saruei", "recording_id": recording_id,
                "start_ms": timestamp, "end_ms": min(duration_ms, timestamp + 12_000),
                "media": media,
            }
            if task == "ADAPTIVE_ASR":
                row.update({"human_transcript": None, "choice": None})
            else:
                row["label"] = None
            tasks.append(row)
    leaks = sorted({row["recording_id"] for row in tasks if roles.get(row["recording_id"]) not in ALLOWED_ROLES})
    if leaks:
        raise PermissionError(f"calibration task references non TRAIN/VALIDATION VODs: {leaks}")
    counts = Counter((row["creator"], row["task"]) for row in tasks)
    return {
        "schema_version": "1.0", "dataset_id": "ACTIVE_CREATOR_V2_CALIBRATION",
        "scope": list(ACTIVE_CREATORS), "excluded_creators": {"anny": "OUT_OF_SCOPE_INACTIVE_CREATOR"},
        "source_roles": sorted(ALLOWED_ROLES), "final_holdout_used": False,
        "status": "HUMAN_PENDING", "ground_truth_opened": False,
        "counts": {f"{creator}:{task}": value for (creator, task), value in sorted(counts.items())},
        "tasks": tasks, "created_at": utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--visual-manifest", type=Path, required=True)
    parser.add_argument("--adaptive-review", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    visual = [json.loads(line) for line in args.visual_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    adaptive = json.loads(args.adaptive_review.read_text(encoding="utf-8"))
    corpus = json.loads(args.corpus_manifest.read_text(encoding="utf-8"))
    payload = build_calibration(visual_rows=visual, adaptive_review=adaptive, corpus_rows=_manifest_rows(corpus))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite calibration evidence: {args.output}")
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "path": str(args.output.resolve()), "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
