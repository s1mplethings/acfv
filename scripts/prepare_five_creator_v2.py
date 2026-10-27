from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Iterable

from acfv.creator_adaptive import CorpusRole, CorpusVod, split_payload
from acfv.providers.download import TwitchChannelVideo, discover_public_twitch_vods


CREATORS = ("saruei", "anny", "atelieranoko", "snuffy", "laphipi")
MISSING_CREATORS = ("atelieranoko", "snuffy", "laphipi")
DATASET_ID = "FIVE_CREATOR_TRAIN_VALIDATION_V2"
V1_DATASET_ID = "MULTI_CREATOR_TWITCH_FINAL_HOLDOUT_V1"
V2_CANDIDATE_DATASET_ID = "FINAL_FROZEN_HOLDOUT_V2_CANDIDATES"
SAFE_RESERVE_BYTES = 300_057_152_102  # max(15% of canonical 2 TB F:, 200 GiB)

# Chosen before any V2 training.  Each role is a distinct archive VOD and no
# range from a V1/profile VOD is reused.
ROLE_PLAN = {
    "atelieranoko": {
        "2900664508": "TRAIN", "2891965462": "TRAIN", "2889950670": "VALIDATION",
    },
    "snuffy": {
        "2869209311": "TRAIN", "2862010067": "TRAIN", "2870885313": "VALIDATION",
    },
    "laphipi": {
        "2901558938": "TRAIN", "2900623293": "TRAIN", "2891675873": "VALIDATION",
    },
}
RESERVATION_PLAN = {
    "saruei": "2904151786",
    "anny": None,  # only public archive is the consumed V1 VOD
    "atelieranoko": "2904375027",
    "snuffy": "2901762827",
    "laphipi": "2903484569",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_once(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite immutable evidence: {path}")
        return
    path.write_text(rendered, encoding="utf-8")


def walk_json(value: Any, source: Path, rows: dict[str, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        vod_id = str(value.get("vod_id") or value.get("stream_id") or "")
        if not vod_id:
            for key in ("video_path", "output_path", "source_url", "url"):
                match = re.search(r"(?<!\d)(\d{10})(?!\d)", str(value.get(key) or ""))
                if match:
                    vod_id = match.group(1)
                    break
        if vod_id.isdigit():
            row = rows.setdefault(vod_id, {"vod_id": vod_id, "evidence_files": []})
            row["evidence_files"].append(str(source))
            for key in ("creator", "role", "sha256", "hash", "raw_path", "video_path", "output_path"):
                if value.get(key) not in (None, ""):
                    row.setdefault(key, value[key])
        for child in value.values():
            walk_json(child, source, rows)
    elif isinstance(value, list):
        for child in value:
            walk_json(child, source, rows)


def build_registry(bulk_root: Path) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    evidence = bulk_root / "evidence"
    for path in sorted(evidence.glob("*.json")):
        try:
            walk_json(json.loads(path.read_text(encoding="utf-8")), path, rows)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    for creator_dir in sorted((bulk_root / "raw").glob("*")):
        if not creator_dir.is_dir():
            continue
        for vod_dir in sorted(creator_dir.glob("*")):
            if not vod_dir.is_dir() or not vod_dir.name.isdigit():
                continue
            row = rows.setdefault(vod_dir.name, {"vod_id": vod_dir.name, "evidence_files": []})
            row.setdefault("creator", creator_dir.name)
            media = [path for path in vod_dir.glob("*.mp4") if "INCOMPLETE_RAW_EVIDENCE" not in path.name]
            if media:
                row["raw_path"] = str(media[0])
                row["bytes"] = media[0].stat().st_size
            integrity = evidence / f"media-integrity-{vod_dir.name}.json"
            if integrity.exists():
                payload = json.loads(integrity.read_text(encoding="utf-8"))
                row["sha256"] = payload.get("sha256")
                row["integrity_result"] = payload.get("result")

    for row in rows.values():
        row["evidence_files"] = sorted(set(row.get("evidence_files") or []))
        row["v1_final_holdout"] = row["vod_id"] in {
            "2853235966", "2898984086", "2897831198", "2897884895", "2884984247",
        }
    result = {
        "schema_version": "1.0",
        "dataset_id": "FIVE_CREATOR_V2_EXISTING_VOD_REGISTRY",
        "created_at": now(),
        "rules": ["duplicate VOD ID rejected", "identical media SHA256 rejected"],
        "rows": sorted(rows.values(), key=lambda row: row["vod_id"]),
    }
    result["sha256"] = canonical_hash(result)
    return result


def discover_with_retry(creator: str) -> list[TwitchChannelVideo]:
    last: Exception | None = None
    for attempt in range(4):
        try:
            return discover_public_twitch_vods(creator, limit=30)
        except Exception as exc:  # Twitch public metadata is occasionally transient.
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Twitch discovery failed for {creator}: {last}")


def metadata_row(row: TwitchChannelVideo) -> dict[str, Any]:
    payload = asdict(row)
    payload["metadata_sha256"] = canonical_hash(payload)
    return payload


def build_discovery(existing_ids: set[str]) -> tuple[dict[str, Any], dict[str, TwitchChannelVideo]]:
    channels: dict[str, Any] = {}
    lookup: dict[str, TwitchChannelVideo] = {}
    for creator in CREATORS:
        videos = discover_with_retry(creator)
        for row in videos:
            lookup[row.vod_id] = row
        channels[creator] = {
            "videos_discovered": len(videos),
            "new": sum(row.vod_id not in existing_ids for row in videos),
            "duplicate": sum(row.vod_id in existing_ids for row in videos),
            "videos": [metadata_row(row) for row in videos],
        }
    payload = {
        "schema_version": "1.0",
        "dataset_id": "FIVE_CREATOR_V2_TWITCH_DISCOVERY",
        "discovered_at": now(),
        "provider": "PUBLIC_TWITCH_GQL_METADATA_DISCOVERY_ONLY",
        "channels": channels,
    }
    payload["sha256"] = canonical_hash(payload)
    return payload, lookup


def build_split(lookup: dict[str, TwitchChannelVideo], existing_ids: set[str]) -> dict[str, Any]:
    rows: list[CorpusVod] = []
    detail: list[dict[str, Any]] = []
    for creator, planned in ROLE_PLAN.items():
        for vod_id, role in planned.items():
            if vod_id in existing_ids:
                raise ValueError(f"planned V2 VOD is already registered: {vod_id}")
            row = lookup.get(vod_id)
            if row is None or row.creator_login != creator or row.vod_type != "archive":
                raise ValueError(f"planned V2 VOD is unavailable or mismatched: {creator}/{vod_id}")
            corpus = CorpusVod(
                creator=creator, vod_id=vod_id, role=CorpusRole(role),
                url=row.source_url, published_at=row.published_at,
                duration_seconds=row.duration_seconds, vod_type=row.vod_type,
            )
            rows.append(corpus)
            detail.append({
                **metadata_row(row), "role": role, "quality_requested": "best",
                "download_state": "PENDING", "media_sha256": None,
            })
    payload = split_payload(rows, dataset_id=DATASET_ID, dataset_version="v2")
    payload["selection"] = detail
    payload["download_policy"] = {
        "quality": "highest available", "max_rate_bytes_per_second": 8 * 1024 * 1024,
        "concurrency": 1, "safe_reserve_bytes": SAFE_RESERVE_BYTES,
    }
    payload["sha256"] = canonical_hash({key: value for key, value in payload.items() if key != "sha256"})
    return payload


def build_reservations(lookup: dict[str, TwitchChannelVideo], existing_ids: set[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for creator, vod_id in RESERVATION_PLAN.items():
        if vod_id is None:
            rows.append({
                "creator": creator, "status": "UNAVAILABLE_NO_NEW_PUBLIC_VOD",
                "reason": "the only public archive is consumed V1 VOD 2853235966",
            })
            continue
        if vod_id in existing_ids:
            raise ValueError(f"V2 reservation candidate already exists in registry: {vod_id}")
        row = lookup.get(vod_id)
        if row is None or row.creator_login != creator:
            raise ValueError(f"V2 reservation candidate unavailable: {creator}/{vod_id}")
        item = metadata_row(row)
        rows.append({
            "creator": creator, "vod_id": vod_id, "url": row.source_url,
            "published_at": row.published_at, "duration_seconds": row.duration_seconds,
            "metadata_sha256": item["metadata_sha256"], "status": "RESERVED_METADATA_ONLY",
            "materialized": False, "decoded": False, "ground_truth_opened": False,
            "run_count": 0, "rerun_allowed": False,
        })
    payload = {
        "schema_version": "1.0", "dataset_id": V2_CANDIDATE_DATASET_ID,
        "created_at": now(), "state": "CANDIDATE_RESERVATION_INCOMPLETE",
        "final_manifest_created": False,
        "blocking_reason": "anny has no new public VOD independent of consumed V1",
        "rows": rows,
    }
    payload["sha256"] = canonical_hash(payload)
    return payload


def storage_payload(bulk_root: Path, split: dict[str, Any]) -> dict[str, Any]:
    usage = shutil.disk_usage(bulk_root)
    seconds = sum(int(row["duration_seconds"]) for row in split["selection"])
    estimate = seconds * 6_400_000 // 8
    return {
        "schema_version": "1.0", "captured_at": now(), "bulk_root": str(bulk_root),
        "capacity_bytes": usage.total, "free_before_bytes": usage.free,
        "safe_reserve_bytes": max(int(usage.total * 0.15), 200 * 1024 ** 3),
        "estimated_download_bytes": estimate,
        "projected_free_bytes": usage.free - estimate,
        "passed": usage.free - estimate >= max(int(usage.total * 0.15), 200 * 1024 ** 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    default_bulk_root = (
        Path(os.environ["ACFV_BULK_ROOT"])
        if os.environ.get("ACFV_BULK_ROOT")
        else None
    )
    parser.add_argument("--bulk-root", type=Path, default=default_bulk_root)
    args = parser.parse_args()
    if args.bulk_root is None:
        parser.error("--bulk-root or ACFV_BULK_ROOT is required")
    bulk_root = args.bulk_root.resolve()
    evidence = bulk_root / "evidence"
    registry = build_registry(bulk_root)
    existing_ids = {str(row["vod_id"]) for row in registry["rows"]}
    discovery, lookup = build_discovery(existing_ids)
    split = build_split(lookup, existing_ids)
    reservations = build_reservations(lookup, existing_ids)
    storage = storage_payload(bulk_root, split)
    if not storage["passed"]:
        raise RuntimeError("V2 download selection would breach the safe disk reserve")
    write_once(evidence / "five-creator-v2-existing-vod-registry.json", registry)
    write_once(evidence / "five-creator-v2-vod-discovery.json", discovery)
    write_once(evidence / "train-validation-v2-manifest.json", split)
    write_once(evidence / "final-v2-reservation-candidates.json", reservations)
    write_once(evidence / "five-creator-v2-storage-audit.json", storage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
