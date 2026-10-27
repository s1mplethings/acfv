from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from acfv.library import LibraryService
from acfv.library.vod_download import VodDownloadService
from acfv.providers.download import (
    download_twitch_vod_to,
    fetch_twitch_vod_metadata,
    validate_downloaded_media,
)
from acfv.utils.twitch_downloader_setup import ensure_cli_on_path

from scripts.prepare_active_creator_final_holdout_v1 import canonical_sha256


SAFE_RESERVE_BYTES = 300_057_152_102


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_timestamp(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def console_json(payload: object) -> str:
    """Return console-safe JSON even when Windows stdout uses a legacy code page."""
    return json.dumps(payload, ensure_ascii=True)


def write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite Final evidence: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_manifest(payload: dict[str, Any]) -> None:
    expected = str(payload.get("manifest_sha256") or "")
    body = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if canonical_sha256(body) != expected:
        raise RuntimeError("Final manifest canonical SHA-256 mismatch")
    if payload.get("state") != "RESERVED_UNOPENED" or payload.get("run_count") != 0:
        raise PermissionError("Final manifest is not reserved and unopened")


def disk_guard(root: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(root)
    passed = usage.free >= SAFE_RESERVE_BYTES
    result = {
        "free_bytes": usage.free, "capacity_bytes": usage.total,
        "safe_reserve_bytes": SAFE_RESERVE_BYTES, "passed": passed,
    }
    if not passed:
        raise RuntimeError(f"disk reserve breached: {usage.free} < {SAFE_RESERVE_BYTES}")
    return result


def strict_integrity(path: Path, expected_seconds: int) -> dict[str, Any]:
    basic = validate_downloaded_media(path)
    actual_seconds = float(basic["duration_ms"]) / 1000.0
    tolerance = max(120.0, expected_seconds * .01)
    probes = []
    for position in (
        0.0,
        actual_seconds * 0.25,
        actual_seconds * 0.50,
        actual_seconds * 0.75,
        max(0.0, actual_seconds - 5.0),
    ):
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-v", "error", "-ss", f"{position:.3f}",
            "-i", str(path), "-t", "3", "-map", "0:v:0", "-map", "0:a:0",
            "-vf", "setpts=N/(60*TB)", "-af", "asetpts=N/SR/TB", "-f", "null", "-",
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        probes.append({
            "position_seconds": position, "passed": result.returncode == 0,
            "stderr": result.stderr.strip() or None,
        })
    sequential = subprocess.run([
        "ffmpeg", "-hide_banner", "-v", "error", "-i", str(path),
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    passed = (
        abs(actual_seconds - expected_seconds) <= tolerance
        and all(row["passed"] for row in probes)
        and sequential.returncode == 0
        and not sequential.stderr.strip()
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "path": str(path.resolve()), "bytes": path.stat().st_size,
        "sha256": file_sha256(path), "expected_duration_seconds": expected_seconds,
        "actual_duration_seconds": actual_seconds, "duration_tolerance_seconds": tolerance,
        "duration_matches": abs(actual_seconds - expected_seconds) <= tolerance,
        "streams": basic, "decode_probes": probes,
        "full_sequential_decode": "PASS" if sequential.returncode == 0 and not sequential.stderr.strip() else "FAIL",
        "sequential_decode_stderr": sequential.stderr.strip() or None,
        "ground_truth_opened": False, "validated_at": utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bulk-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify_manifest(manifest)
    bulk = args.bulk_root.resolve()
    evidence = args.evidence_root.resolve()
    disk = disk_guard(bulk)
    cli = ensure_cli_on_path(auto_install=False)
    if not cli:
        raise RuntimeError("TwitchDownloaderCLI is unavailable")
    metadata_rows = []
    for row in manifest["rows"]:
        metadata = fetch_twitch_vod_metadata(str(row["vod_id"]), cli_path=cli)
        if metadata.creator_login.casefold() != str(row["creator"]).casefold():
            raise RuntimeError(f"Twitch owner mismatch for {row['vod_id']}")
        if abs(metadata.duration_ms // 1000 - int(row["duration_seconds"])) > 5:
            raise RuntimeError(f"Twitch duration changed for {row['vod_id']}")
        metadata_rows.append({
            "creator": row["creator"], "vod_id": row["vod_id"],
            "title": metadata.title, "duration_seconds": metadata.duration_ms // 1000,
            "source_url": metadata.source_url,
            "created_at": json_timestamp(metadata.created_at),
        })
    preflight = {
        "status": "PASS", "dataset_id": manifest["dataset_id"],
        "manifest_file_sha256": file_sha256(args.manifest),
        "quality": "best", "bandwidth_kib_s": 8192, "concurrency": 1,
        "disk": disk, "metadata": metadata_rows, "ground_truth_opened": False,
        "checked_at": utc_now(),
    }
    preflight_path = evidence / "download-preflight.json"
    if not preflight_path.exists():
        write_new(preflight_path, preflight)
    if args.check_only:
        print(console_json(preflight))
        return 0

    library = LibraryService(evidence / "final-download-library.sqlite")
    downloader = partial(
        download_twitch_vod_to, quality="best", threads=1,
        bandwidth_kib_s=8192, cli_path=cli, timeout=14 * 3600,
    )
    service = VodDownloadService(
        library, media_root=bulk / "raw" / "active-creator-final-holdout-v1",
        metadata_fetcher=lambda source: fetch_twitch_vod_metadata(source, cli_path=cli),
        downloader=downloader,
    )
    completed = []
    for row in manifest["rows"]:
        vod_id = str(row["vod_id"])
        receipt_path = evidence / f"download-{vod_id}.json"
        integrity_path = evidence / f"integrity-{vod_id}.json"
        if receipt_path.exists() and integrity_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
            if receipt.get("status") == "PASS" and integrity.get("status") == "PASS" and Path(receipt["media_path"]).is_file():
                completed.append(vod_id)
                continue
        disk_guard(bulk)
        job = service.discover(str(row["url"]), provider="TwitchDownloaderCLI")
        job = service.download(job.id, auto_process=False, max_retries=2)
        media = Path(str(job.final_path))
        checked = strict_integrity(media, int(row["duration_seconds"]))
        write_new(integrity_path, checked)
        if checked["status"] != "PASS":
            raise RuntimeError(f"strict Final integrity failed for VOD {vod_id}")
        receipt = {
            "status": "PASS", "dataset_id": manifest["dataset_id"],
            "creator": row["creator"], "vod_id": vod_id,
            "download_id": job.id, "recording_id": job.recording_id,
            "media_path": str(media.resolve()), "media_bytes": media.stat().st_size,
            "media_sha256": checked["sha256"], "integrity_receipt": str(integrity_path),
            "quality": "best", "bandwidth_kib_s": 8192, "concurrency": 1,
            "ground_truth_opened": False, "completed_at": utc_now(),
        }
        write_new(receipt_path, receipt)
        completed.append(vod_id)
    summary = {
        "status": "PASS", "dataset_id": manifest["dataset_id"],
        "completed_vod_ids": completed, "count": len(completed),
        "all_media_integrity_passed": len(completed) == len(manifest["rows"]),
        "ground_truth_opened": False, "completed_at": utc_now(),
    }
    write_new(evidence / "download-complete.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
