from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

from acfv.creator_adaptive import CorpusRole, CorpusVod, split_payload, write_frozen_split
from acfv.library import LibraryService
from acfv.providers.download import discover_public_twitch_vods
from acfv.runtime.bulk_storage import GIB, StorageVolume, select_bulk_storage


ROOT = Path(__file__).resolve().parents[1]
CREATORS = ("saruei", "anny", "atelieranoko", "snuffy", "laphipi")
DATASET_ID = "MULTI_CREATOR_TWITCH_V1"
DATASET_VERSION = "multi_creator_twitch_v1"
PROFILE_VERSION = "creator_profile_v5_multi_creator"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_windows_storage() -> dict[str, Any]:
    command = r"""
$snapshot = [ordered]@{
  captured_at = (Get-Date).ToUniversalTime().ToString('o')
  volumes = @(Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining,HealthStatus,OperationalStatus,DriveType)
  partitions = @(Get-Partition | Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,Size,IsBoot,IsSystem,IsReadOnly,IsOffline)
  disks = @(Get-Disk | Select-Object Number,FriendlyName,BusType,PartitionStyle,OperationalStatus,HealthStatus,Size,IsBoot,IsSystem,IsOffline,IsReadOnly)
  physical_disks = @(Get-PhysicalDisk | Select-Object DeviceId,FriendlyName,MediaType,BusType,Size,HealthStatus,OperationalStatus)
}
$snapshot | ConvertTo-Json -Depth 5 -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command], capture_output=True,
        text=True, encoding="utf-8-sig", errors="replace", timeout=120, check=True,
    )
    return json.loads(result.stdout)


def storage_volumes(snapshot: dict[str, Any]) -> list[StorageVolume]:
    partitions = {str(row.get("DriveLetter") or "").upper(): row for row in snapshot.get("partitions", []) if row.get("DriveLetter")}
    disks = {int(row["Number"]): row for row in snapshot.get("disks", [])}
    physical = {str(row.get("DeviceId")): row for row in snapshot.get("physical_disks", [])}
    rows: list[StorageVolume] = []
    for volume in snapshot.get("volumes", []):
        letter = str(volume.get("DriveLetter") or "").upper()
        if not letter:
            continue
        partition = partitions.get(letter, {})
        number = partition.get("DiskNumber")
        disk = disks.get(int(number), {}) if number is not None else {}
        physical_row = physical.get(str(number), {})
        operational = volume.get("OperationalStatus") or disk.get("OperationalStatus") or "Unknown"
        if isinstance(operational, list):
            operational = ",".join(str(value) for value in operational)
        rows.append(StorageVolume(
            drive_letter=letter,
            capacity_bytes=int(volume.get("Size") or disk.get("Size") or 0),
            free_bytes=int(volume.get("SizeRemaining") or 0),
            health_status=str(volume.get("HealthStatus") or disk.get("HealthStatus") or "Unknown"),
            operational_status=str(operational),
            drive_type=str(volume.get("DriveType") or "Unknown"),
            disk_number=int(number) if number is not None else None,
            friendly_name=str(disk.get("FriendlyName") or physical_row.get("FriendlyName") or ""),
            bus_type=str(disk.get("BusType") or physical_row.get("BusType") or ""),
            media_type=str(physical_row.get("MediaType") or "Unspecified"),
            is_boot=bool(partition.get("IsBoot") or disk.get("IsBoot")),
            is_system=bool(partition.get("IsSystem") or disk.get("IsSystem")),
            file_system=str(volume.get("FileSystem") or ""),
            file_system_label=str(volume.get("FileSystemLabel") or ""),
        ))
    return rows


def discover(output: Path) -> dict[str, Any]:
    channels = {}
    for creator in CREATORS:
        videos = discover_public_twitch_vods(creator, limit=20)
        channels[creator] = {
            "channel_resolved": bool(videos),
            "creator_id": videos[0].creator_id if videos else None,
            "display_name": videos[0].creator_name if videos else creator,
            "videos": [asdict(row) for row in videos],
        }
    payload = {
        "schema_version": "1.0",
        "dataset_id": DATASET_ID,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "provider": "PUBLIC_TWITCH_GQL_METADATA_DISCOVERY_ONLY",
        "formal_download_provider": "VodDownloadService+TwitchDownloaderCLI",
        "channels": channels,
    }
    write_json(output / "twitch-metadata-discovery.json", payload)
    return payload


def _existing_registry(prior_receipts: Path, prior_registry: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if prior_registry.is_file():
        result.extend(json.loads(prior_registry.read_text(encoding="utf-8")).get("rows") or [])
    if prior_receipts.is_file():
        for row in json.loads(prior_receipts.read_text(encoding="utf-8")).get("rows") or []:
            result.append({
                "creator": row.get("creator"), "vod_id": str(row.get("vod_id") or ""),
                "url": row.get("url"), "date": row.get("date"), "duration_ms": row.get("source_duration_seconds", 0) * 1000,
                "hash": row.get("sha256"), "recording_id": row.get("recording_id"),
                "role": row.get("role"), "dataset_version": "NEW_TWITCH_VALIDATION_V1",
                "library_root_id": "NEW_TWITCH_VALIDATION_LOCAL", "relative_locator": None,
            })
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in result:
        key = (str(row.get("creator") or "").casefold(), str(row.get("vod_id") or row.get("stream_id") or ""))
        deduped[key] = row
    return list(deduped.values())


def freeze(output: Path, discovery: dict[str, Any], prior_config: Path, prior_receipts: Path,
           prior_registry: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    prior_split_path = output / "multi-creator-vod-split-v1.json"
    prior_split_sha = None
    if prior_split_path.is_file():
        prior_split_sha = json.loads(prior_split_path.read_text(encoding="utf-8")).get("sha256")
    prior = json.loads(prior_config.read_text(encoding="utf-8"))
    existing = _existing_registry(prior_receipts, prior_registry)
    existing_ids = {str(row.get("vod_id") or "") for row in existing}
    selected: list[dict[str, Any]] = []
    limitations: dict[str, str] = {}
    rejected: list[dict[str, str]] = []
    unfinalized: set[str] = set()
    probe_receipts = output / "manifests/download-receipts-probe.json"
    if probe_receipts.is_file():
        for row in json.loads(probe_receipts.read_text(encoding="utf-8")).get("rows") or []:
            status = str(((row.get("metadata") or {}).get("provider_metadata") or {}).get("status") or "")
            if status == "RECORDING":
                unfinalized.add(str(row.get("vod_id") or ""))
                rejected.append({"vod_id": str(row.get("vod_id") or ""), "reason": "ACTIVE_RECORDING_NOT_FINALIZED"})

    # Preserve the already-frozen, independently validated Saruei/anny corpus.
    for row in prior.get("vods") or []:
        if str(row.get("creator") or "").casefold() not in {"saruei", "anny"}:
            continue
        selected.append({**row, "source_dataset": "NEW_TWITCH_VALIDATION_V1", "download_state": "EXISTING"})

    for creator in ("atelieranoko", "snuffy", "laphipi"):
        candidates = [
            row for row in discovery["channels"][creator]["videos"]
            if row["vod_id"] not in existing_ids and row["vod_id"] not in unfinalized
        ]
        # Four distinct VODs: two older TRAIN, one VALIDATION, newest HOLDOUT.
        chosen = list(reversed(candidates[:4]))
        if len(chosen) < 3:
            limitations[creator] = "LIMITED_VOD_DIVERSITY"
        roles = (["TRAIN"] * max(0, len(chosen) - 2)) + (["VALIDATION", "HOLDOUT"] if len(chosen) >= 2 else (["HOLDOUT"] if chosen else []))
        for item, role in zip(chosen, roles):
            selected.append({
                "creator": creator, "user_id": item["creator_id"], "vod_id": item["vod_id"],
                "url": item["source_url"], "title": item["title"], "created_at": item["created_at"],
                "published_at": item["published_at"], "duration_seconds": item["duration_seconds"],
                "language": None, "accent": "NOT_HUMAN_LABELLED", "type": item["vod_type"],
                "viewable": True, "role": role, "quality": "720p", "range_start_ms": 0,
                "range_end_ms": item["duration_seconds"] * 1000, "probe_start_ms": min(600_000, max(0, item["duration_seconds"] * 500)),
                "source_dataset": DATASET_ID, "download_state": "BLOCKED_PENDING_STORAGE",
            })
    if sum(1 for row in selected if str(row["creator"]).casefold() == "anny") < 3:
        limitations["anny"] = "LIMITED_VOD_DIVERSITY"
    if not any(row["creator"].casefold() == "saruei" and row.get("source_dataset") == DATASET_ID for row in selected):
        limitations["saruei"] = "NO_NEWER_VOD_AFTER_EXISTING_CORPUS"

    corpus_rows = [CorpusVod(
        creator=str(row["creator"]), vod_id=str(row["vod_id"]), role=CorpusRole(str(row["role"])),
        url=str(row["url"]), published_at=str(row.get("published_at") or row.get("created_at") or ""),
        duration_seconds=int(row.get("duration_seconds") or 0), vod_type=str(row.get("type") or "archive"),
    ) for row in selected]
    frozen = split_payload(corpus_rows, dataset_id=DATASET_ID, dataset_version=DATASET_VERSION)
    write_frozen_split(output / "multi-creator-vod-split-v1.json", frozen)
    (output / "multi-creator-vod-split-v1.sha256").write_text(f"{frozen['sha256']}  multi-creator-vod-split-v1.json\n", encoding="ascii")

    estimated = sum(int(row.get("duration_seconds") or 0) for row in selected) * 6_000_000 // 8
    decision = select_bulk_storage(storage_volumes(snapshot), estimated_corpus_bytes=estimated)
    plan = {
        "schema_version": "1.0", "dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION,
        "profile_version": PROFILE_VERSION, "root_alias": "BULK_MEDIA_ROOT",
        "estimated_bitrate_bps": 6_000_000, "estimated_corpus_size": estimated,
        "estimated_corpus_gib": estimated / GIB, **decision.as_dict(),
    }
    write_json(output / "download-storage-plan.json", plan)
    write_json(output / "existing-vod-registry-v2.json", {"schema_version": "2.0", "rows": existing})
    manifest = {
        "schema_version": "1.0", "dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION,
        "profile_version": PROFILE_VERSION, "split_sha256": frozen["sha256"],
        "known_creators": list(CREATORS), "limitations": limitations, "vods": selected,
        "rejected": rejected,
        "split_revision": {
            "previous_sha256": prior_split_sha,
            "reason": "exclude active/unfinalized VOD after canonical metadata probe",
        } if prior_split_sha and prior_split_sha != frozen["sha256"] else None,
        "download_decision": decision.status,
    }
    write_json(output / "multi-creator-corpus-plan.json", manifest)
    return manifest


def register_creators(output: Path, discovery: dict[str, Any]) -> None:
    library = LibraryService(output / "metadata-library.sqlite")
    rows = []
    for login in CREATORS:
        channel = discovery["channels"][login]
        creator = library.create_creator(channel["display_name"], slug=login)
        source = library.add_source(
            creator.id, platform="twitch", external_id=str(channel.get("creator_id") or login),
            channel_name=channel["display_name"], source_type="vod_channel",
            channel_url=f"https://www.twitch.tv/{login}", metadata={"login": login},
        )
        rows.append({"login": login, "creator_id": creator.id, "source_id": source.id})
    write_json(output / "creator-registration-receipt.json", {"schema_version": "1.0", "rows": rows})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("audit", "discover", "freeze", "all"))
    parser.add_argument("--output", type=Path, default=ROOT / "var/multi-creator-twitch-v1")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot_path = output / "windows-storage-audit.json"
    discovery_path = output / "twitch-metadata-discovery.json"
    if args.command in {"audit", "all"}:
        write_json(snapshot_path, collect_windows_storage())
    if args.command in {"discover", "all"}:
        payload = discover(output)
        register_creators(output, payload)
    if args.command in {"freeze", "all"}:
        if not snapshot_path.is_file() or not discovery_path.is_file():
            raise FileNotFoundError("run audit and discover before freeze")
        freeze(
            output, json.loads(discovery_path.read_text(encoding="utf-8")),
            ROOT / "config/new_twitch_validation_v1.json",
            ROOT / "var/new-twitch-validation/manifests/download-receipts-download.json",
            ROOT / "evidence/validation/new-twitch-creator-adaptive/existing-vod-registry.json",
            json.loads(snapshot_path.read_text(encoding="utf-8")),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
