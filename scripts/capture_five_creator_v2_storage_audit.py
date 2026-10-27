from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


SAFE_RESERVE_BYTES = 300_057_152_102


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def powershell_json(command: str) -> object:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "PowerShell storage audit failed")
    value = completed.stdout.strip()
    return json.loads(value) if value else []


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
    drive_letter = bulk_root.drive.rstrip(":")
    if not re.fullmatch(r"[A-Za-z]", drive_letter):
        parser.error("--bulk-root must resolve to a local Windows drive")
    evidence = bulk_root / "evidence" / "five-creator-v2-storage-hardware-audit.json"
    usage = shutil.disk_usage(bulk_root)
    hardware = powershell_json(
        f"$partition=Get-Partition -DriveLetter {drive_letter} -ErrorAction Stop; "
        "$disk=Get-Disk -Number $partition.DiskNumber -ErrorAction Stop; "
        "$physical=Get-PhysicalDisk | Where-Object DeviceId -eq ([string]$disk.Number); "
        f"$volume=Get-Volume -DriveLetter {drive_letter} -ErrorAction Stop; "
        "[pscustomobject]@{"
        "disk_number=$disk.Number; disk_friendly_name=$disk.FriendlyName; "
        "disk_serial_number=$disk.SerialNumber; disk_health_status=[string]$disk.HealthStatus; "
        "disk_operational_status=[string]$disk.OperationalStatus; "
        "disk_bus_type=[string]$disk.BusType; disk_partition_style=[string]$disk.PartitionStyle; "
        "disk_size_bytes=[int64]$disk.Size; physical_media_type=[string]$physical.MediaType; "
        "physical_health_status=[string]$physical.HealthStatus; "
        "physical_operational_status=[string]$physical.OperationalStatus; "
        "partition_number=$partition.PartitionNumber; partition_size_bytes=[int64]$partition.Size; "
        "volume_file_system=$volume.FileSystem; volume_health_status=[string]$volume.HealthStatus; "
        "volume_operational_status=[string]$volume.OperationalStatus; "
        "volume_size_bytes=[int64]$volume.Size; volume_free_bytes=[int64]$volume.SizeRemaining"
        "} | ConvertTo-Json -Depth 4 -Compress"
    )
    payload = {
        "schema_version": "1.0",
        "captured_at": now(),
        "bulk_root": str(bulk_root),
        "capacity_bytes": usage.total,
        "free_bytes": usage.free,
        "safe_reserve_bytes": SAFE_RESERVE_BYTES,
        "reserve_passed": usage.free >= SAFE_RESERVE_BYTES,
        "hardware": hardware,
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    temporary = evidence.with_suffix(evidence.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(evidence)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["reserve_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
