from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable


DATASET_ID = "ACTIVE_CREATOR_FINAL_HOLDOUT_V1"
ACTIVE_CREATORS = ("saruei", "atelieranoko", "snuffy", "laphipi")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def collect_vod_ids(payload: object) -> set[str]:
    result: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"vod_id", "external_vod_id", "recording_id"}:
                    text = str(item)
                    if text.isdigit():
                        result.add(text)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return result


def validate_candidates(
    candidates: Iterable[dict[str, Any]], *, forbidden_vod_ids: set[str]
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in candidates]
    creators = [str(row.get("creator", "")).casefold() for row in rows]
    if sorted(creators) != sorted(ACTIVE_CREATORS):
        raise ValueError("Final candidates must contain exactly one row per active creator")
    vod_ids = [str(row.get("vod_id", "")) for row in rows]
    if any(not value.isdigit() for value in vod_ids) or len(set(vod_ids)) != len(vod_ids):
        raise ValueError("Final candidate VOD IDs must be unique numeric values")
    overlap = sorted(set(vod_ids) & forbidden_vod_ids)
    if overlap:
        raise PermissionError(f"Final candidates overlap prior evidence: {overlap}")
    required = {"url", "published_at", "duration_seconds", "title"}
    for row in rows:
        missing = sorted(key for key in required if not row.get(key))
        if missing:
            raise ValueError(f"Final candidate {row.get('vod_id')} missing {missing}")
        row.update({
            "creator": str(row["creator"]).casefold(),
            "selected_quality": "best",
            "prior_seen": False,
            "training_used": False,
            "validation_used": False,
            "memory_used": False,
            "review_used": False,
            "run_count": 0,
            "ground_truth_opened": False,
            "rerun_allowed": False,
        })
    return sorted(rows, key=lambda row: ACTIVE_CREATORS.index(row["creator"]))


def build_manifest(
    candidates: Iterable[dict[str, Any]], *, forbidden_vod_ids: set[str],
    repository: Path, frozen_artifacts: Iterable[Path], reserved_at: str | None = None,
) -> dict[str, Any]:
    rows = validate_candidates(candidates, forbidden_vod_ids=forbidden_vod_ids)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=repository, text=True
    ).strip()
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repository, text=True
    ).strip():
        raise RuntimeError("Final freeze requires a clean committed worktree")
    artifacts = []
    for path in frozen_artifacts:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        artifacts.append({
            "path": str(resolved), "bytes": resolved.stat().st_size,
            "sha256": file_sha256(resolved),
        })
    timestamp = reserved_at or utc_now()
    for row in rows:
        row["reserved_at"] = timestamp
    return {
        "schema_version": "1.0",
        "dataset_id": DATASET_ID,
        "scope": list(ACTIVE_CREATORS),
        "excluded_creators": {"anny": "OUT_OF_SCOPE_INACTIVE_CREATOR"},
        "state": "RESERVED_UNOPENED",
        "run_count": 0,
        "ground_truth_opened": False,
        "rerun_allowed": False,
        "quality": "best",
        "bandwidth_kib_s": 8192,
        "concurrency": 1,
        "git_commit_sha": commit,
        "git_tree_sha": tree,
        "frozen_artifacts": artifacts,
        "rows": rows,
        "forbidden_vod_count": len(forbidden_vod_ids),
        "reserved_at": timestamp,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--prior-manifest", type=Path, action="append", default=[])
    parser.add_argument("--freeze-artifact", type=Path, action="append", default=[])
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate_payload = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = candidate_payload.get("rows", candidate_payload)
    if not isinstance(candidates, list):
        raise ValueError("candidate payload must be a list or contain rows")
    forbidden: set[str] = set()
    prior_receipts = []
    for path in args.prior_manifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids = collect_vod_ids(payload)
        forbidden.update(ids)
        prior_receipts.append({"path": str(path.resolve()), "sha256": file_sha256(path), "vod_ids": sorted(ids)})
    manifest = build_manifest(
        candidates, forbidden_vod_ids=forbidden, repository=args.repository.resolve(),
        frozen_artifacts=args.freeze_artifact,
    )
    manifest["prior_evidence"] = prior_receipts
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite frozen Final manifest: {args.output}")
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "manifest": str(args.output.resolve()), "sha256": file_sha256(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
