from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from acfv.library import LibraryService, RecordingStatus
from acfv.providers.download import (
    download_twitch_vod_to,
    fetch_twitch_vod_metadata,
    validate_downloaded_media,
)
from acfv.utils.twitch_downloader_setup import ensure_cli_on_path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BULK_ROOT = (
    Path(os.environ["ACFV_BULK_ROOT"])
    if os.environ.get("ACFV_BULK_ROOT")
    else None
)
MAX_RATE_KIB_S = 8192
SAFE_RESERVE_BYTES = 300_057_152_102
FFMPEG = "ffmpeg"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_manifest(payload: dict[str, Any]) -> None:
    expected = str(payload.get("sha256") or "")
    body = {key: value for key, value in payload.items() if key != "sha256"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != expected:
        raise RuntimeError("train-validation-v2-manifest SHA256 mismatch")
    if not payload.get("frozen_before_training"):
        raise RuntimeError("TRAIN/VALIDATION V2 split is not frozen")


def fetch_metadata_with_retry(vod_id: str, cli: str):
    """Retry Twitch's transient 20-second info timeout without duplicating work."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return fetch_twitch_vod_metadata(vod_id, cli_path=cli)
        except RuntimeError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def disk_guard(bulk_root: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(bulk_root)
    passed = usage.free >= SAFE_RESERVE_BYTES
    result = {
        "checked_at": now(), "capacity_bytes": usage.total, "free_bytes": usage.free,
        "safe_reserve_bytes": SAFE_RESERVE_BYTES, "passed": passed,
    }
    if not passed:
        raise RuntimeError(f"disk reserve breached: free={usage.free} reserve={SAFE_RESERVE_BYTES}")
    return result


def spot_decode(path: Path, duration_seconds: float) -> list[dict[str, Any]]:
    positions = (0.0, duration_seconds / 2.0, max(0.0, duration_seconds - 5.0))
    rows = []
    for position in positions:
        completed = subprocess.run(
            [FFMPEG, "-hide_banner", "-v", "error", "-ss", f"{position:.3f}",
             "-i", str(path), "-t", "3", "-map", "0:v:0", "-map", "0:a:0",
             # These probes validate decoded content, not the source packet
             # timeline (the full integrity gate audits that separately).
             # Recovered VFR material can yield duplicate frame timestamps at
             # an arbitrary seek point, which the null muxer rejects despite a
             # successful decode, so assign validation-only monotonic clocks.
             "-vf", "setpts=N/(60*TB)", "-af", "asetpts=N/SR/TB",
             "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        rows.append({
            "position_seconds": position,
            "passed": completed.returncode == 0 and not completed.stderr.strip(),
            "error": completed.stderr.strip() or None,
        })
    return rows


def integrity(path: Path, expected_seconds: int) -> dict[str, Any]:
    result = validate_downloaded_media(path)
    actual = float(result["duration_ms"]) / 1000.0
    tolerance = max(120.0, expected_seconds * 0.01)
    spots = spot_decode(path, actual)
    passed = abs(actual - expected_seconds) <= tolerance and all(row["passed"] for row in spots)
    return {
        "schema_version": "1.0", "result": "PASS" if passed else "FAIL",
        "path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path),
        "expected_duration_seconds": expected_seconds, "actual_duration_seconds": actual,
        "duration_tolerance_seconds": tolerance, "duration_matches": abs(actual - expected_seconds) <= tolerance,
        "ffprobe": "PASS", "full_sequential_decode": "PASS",
        "decode_probes": spots, "media": result, "validated_at": now(),
        "ground_truth_opened": False,
    }


def download_chat(cli: str, vod_id: str, output: Path) -> dict[str, Any]:
    if output.is_file() and output.stat().st_size > 0:
        return {"result": "REUSED", "path": str(output), "bytes": output.stat().st_size}
    completed = subprocess.run(
        [cli, "chatdownload", "--id", vod_id, "--output", str(output),
         "--threads", "1", "--embed-images", "false", "--collision", "Exit",
         "--banner=false", "--log-level", "None"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
    )
    return {
        "result": "PASS" if completed.returncode == 0 and output.is_file() else "UNAVAILABLE",
        "path": str(output), "bytes": output.stat().st_size if output.is_file() else 0,
        "exit_code": completed.returncode,
        "error": completed.stderr.strip() or None,
    }


def ingest(library: LibraryService, row: dict[str, Any], media: Path,
           integrity_path: Path) -> dict[str, Any]:
    creator_name = str(row["creator"])
    creator = library.create_creator(creator_name, slug=creator_name)
    source = library.add_source(
        creator.id, platform="twitch", external_id=creator_name,
        channel_name=creator_name, source_type="vod_channel",
        channel_url=f"https://www.twitch.tv/{creator_name}",
        metadata={"dataset_id": "FIVE_CREATOR_TRAIN_VALIDATION_V2"},
    )
    recording = library.register_recording(
        creator_id=creator.id, source_id=source.id, title=str(row["title"]),
        local_path=media, source_type="vod_download", source_url=str(row["source_url"]),
        recording_status=RecordingStatus.COMPLETE, content_type="other",
    )
    recording.external_vod_id = str(row["vod_id"])
    recording.provider = "TwitchDownloaderCLI"
    recording.download_metadata_json = json.dumps({
        "dataset_id": "FIVE_CREATOR_TRAIN_VALIDATION_V2", "role": row["role"],
        "quality": "best", "bandwidth_kib_s": MAX_RATE_KIB_S,
        "media_integrity": str(integrity_path), "is_partial_source": False,
    }, ensure_ascii=False, sort_keys=True)
    recording = library.repository.save(recording)
    duplicate = library.register_recording(
        creator_id=creator.id, source_id=source.id, title=recording.title,
        local_path=media, source_type="vod_download", source_url=recording.source_url,
        recording_status=RecordingStatus.COMPLETE,
    )
    if duplicate.id != recording.id:
        raise RuntimeError(f"LibraryService duplicate prevention failed for {row['vod_id']}")
    return {
        "result": "PASS", "service": "LibraryService", "manual_sql": False,
        "creator_id": creator.id, "source_id": source.id, "recording_id": recording.id,
        "external_vod_id": row["vod_id"], "local_path": recording.local_path,
        "recording_status": recording.recording_status.value, "duplicate_prevention": "PASS",
        "ingested_at": now(), "ground_truth_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bulk-root", type=Path, default=DEFAULT_BULK_ROOT)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.bulk_root is None:
        parser.error("--bulk-root or ACFV_BULK_ROOT is required")
    bulk_root = args.bulk_root.resolve()
    evidence = bulk_root / "evidence"
    manifest = json.loads((evidence / "train-validation-v2-manifest.json").read_text(encoding="utf-8"))
    check_manifest(manifest)
    reservations = json.loads((evidence / "final-v2-reservation-candidates.json").read_text(encoding="utf-8"))
    reserved = {str(row.get("vod_id")) for row in reservations["rows"] if row.get("vod_id")}
    cli = ensure_cli_on_path(auto_install=False)
    if not cli:
        raise RuntimeError("TwitchDownloaderCLI is unavailable")
    selected: list[dict[str, Any]] = []
    for item in manifest["selection"]:
        vod_id = str(item["vod_id"])
        if vod_id in reserved:
            raise RuntimeError(f"FINAL V2 candidate leaked into download plan: {vod_id}")
        metadata = fetch_metadata_with_retry(vod_id, cli)
        if metadata.creator_login != str(item["creator_login"]).casefold():
            raise RuntimeError(f"Twitch owner mismatch for {vod_id}")
        selected.append({
            **item, "creator": str(item["creator_login"]).casefold(),
            "title": metadata.title, "source_url": metadata.source_url,
            "language": metadata.language, "category": metadata.category,
            "provider_duration_seconds": metadata.duration_ms // 1000,
        })
    preflight = {
        "schema_version": "1.0", "result": "PASS", "checked_at": now(),
        "provider": "TwitchDownloaderCLI", "quality": "best",
        "bandwidth_kib_s": MAX_RATE_KIB_S, "threads": 1,
        "disk": disk_guard(bulk_root), "selected": selected,
        "reserved_v2_ids_accessed": [], "ground_truth_opened": False,
    }
    write_json(evidence / "five-creator-v2-download-preflight.json", preflight)
    if args.check_only:
        return 0

    progress_path = evidence / "five-creator-v2-download-progress.json"
    library = LibraryService(ROOT / "var" / "acfv.db")
    completed_ids: list[str] = []
    for index, row in enumerate(selected, start=1):
        vod_id = str(row["vod_id"])
        final_dir = bulk_root / "raw" / str(row["creator"]) / vod_id
        final_media = final_dir / f"{row['creator']}_{vod_id}_highest.mp4"
        receipt_path = evidence / f"v2-download-{vod_id}-receipt.json"
        integrity_path = evidence / f"v2-media-integrity-{vod_id}.json"
        ingest_path = evidence / f"v2-library-ingest-{vod_id}.json"
        if receipt_path.is_file() and integrity_path.is_file() and ingest_path.is_file():
            prior = json.loads(receipt_path.read_text(encoding="utf-8"))
            if prior.get("result") == "PASS" and final_media.is_file():
                completed_ids.append(vod_id)
                continue
        disk_guard(bulk_root)
        final_dir.mkdir(parents=True, exist_ok=True)
        transfer_dir = bulk_root / "temp" / "five-creator-v2" / vod_id
        transfer_dir.mkdir(parents=True, exist_ok=True)
        candidate = transfer_dir / f"download-attempt-{now().replace(':', '').replace('-', '')}.mp4"
        started_at = now()

        def update(provider: dict[str, Any]) -> None:
            write_json(progress_path, {
                "schema_version": "1.0", "state": "TRANSFER",
                "current_index": index, "total": len(selected), "creator": row["creator"],
                "vod_id": vod_id, "completed_vod_ids": completed_ids,
                "provider": provider, "disk": disk_guard(bulk_root),
                "updated_at": now(), "ground_truth_opened": False,
            })

        try:
            if final_media.is_file() and final_media.stat().st_size > 0:
                candidate = final_media
                transfer_state = "REUSED_EXISTING_CANONICAL"
            else:
                download_twitch_vod_to(
                    vod_id, candidate, quality="best", threads=1,
                    bandwidth_kib_s=MAX_RATE_KIB_S,
                    temp_path=transfer_dir / "cache", trim_mode="Safe", cli_path=cli,
                    progress_callback=update, timeout=14 * 3600,
                )
                transfer_state = "TRANSFER_COMPLETED"
            checked = integrity(candidate, int(row["duration_seconds"]))
            if checked["result"] != "PASS":
                raise RuntimeError(f"media integrity failed for VOD {vod_id}")
            if candidate != final_media:
                if final_media.exists():
                    raise FileExistsError(f"refusing to overwrite canonical Raw: {final_media}")
                candidate.replace(final_media)
                checked["path"] = str(final_media)
            write_json(integrity_path, checked)
            chat = download_chat(cli, vod_id, final_dir / "chat.json")
            ingested = ingest(library, row, final_media, integrity_path)
            write_json(ingest_path, ingested)
            receipt = {
                "schema_version": "1.0", "result": "PASS", "creator": row["creator"],
                "vod_id": vod_id, "role": row["role"], "quality_requested": "best",
                "quality_actual": f"{checked['media']['width']}x{checked['media']['height']}@{checked['media']['frame_rate']}",
                "configured_limit_mib_s": 8, "native_bandwidth_kib_s": MAX_RATE_KIB_S,
                "cli_threads": 1, "started_at": started_at, "finished_at": now(),
                "transfer_state": transfer_state, "media_state": "READY",
                "output_path": str(final_media), "bytes": checked["bytes"], "sha256": checked["sha256"],
                "media_integrity": str(integrity_path), "library_ingest": str(ingest_path),
                "chat": chat, "disk": disk_guard(bulk_root), "ground_truth_opened": False,
            }
            write_json(receipt_path, receipt)
            completed_ids.append(vod_id)
        except BaseException as exc:
            write_json(evidence / f"v2-download-{vod_id}-failure-{os.getpid()}.json", {
                "schema_version": "1.0", "result": "FAIL", "vod_id": vod_id,
                "failed_at": now(), "error": f"{type(exc).__name__}: {exc}",
                "nonzero_candidate_preserved": str(candidate) if candidate.exists() else None,
                "ground_truth_opened": False,
            })
            raise
    write_json(progress_path, {
        "schema_version": "1.0", "state": "COMPLETE", "result": "PASS",
        "completed_vod_ids": completed_ids, "total": len(selected),
        "disk": disk_guard(bulk_root), "finished_at": now(), "ground_truth_opened": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
