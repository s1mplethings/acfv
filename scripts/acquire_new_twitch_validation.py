from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from acfv.library import LibraryService, VodDownloadService
from acfv.providers.download import fetch_twitch_vod_metadata
from acfv.utils.twitch_downloader_setup import ensure_cli_on_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("dataset_id") not in {"NEW_TWITCH_VALIDATION_V1", "MULTI_CREATOR_TWITCH_V1"}:
        raise ValueError("Unexpected dataset_id")
    return payload


def _split_payload(plan: dict[str, Any]) -> dict[str, Any]:
    rows = []
    seen: set[str] = set()
    for item in plan["vods"]:
        vod_id = str(item["vod_id"])
        if vod_id in seen:
            raise ValueError(f"VOD crosses split boundary: {vod_id}")
        seen.add(vod_id)
        rows.append({key: item.get(key) for key in (
            "creator", "vod_id", "url", "role", "unknown_partition",
            "range_start_ms", "range_end_ms", "quality",
        )})
    return {
        "schema_version": "1.0",
        "dataset_id": plan["dataset_id"],
        "dataset_version": plan["dataset_version"],
        "profile_version": plan["profile_version"],
        "split_revision": plan.get("split_revision"),
        "frozen_before_training": True,
        "leakage_invariant": (
            "HOLDOUT VOD cannot enter visual training, voice profile training, trusted memory, "
            "lexicon, or threshold tuning; UNKNOWN cannot create known-Creator trusted memory."
        ),
        "rows": rows,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def freeze(plan_path: Path, output_root: Path) -> None:
    plan = _load_plan(plan_path)
    existing = {"schema_version": "1.0", "rows": plan["existing_registry"]}
    discovery = {
        "schema_version": "1.0",
        "dataset_id": plan["dataset_id"],
        "discovery": plan["discovery"],
        "vods": plan["vods"],
        "rejected_or_not_selected": plan["rejected_or_not_selected"],
    }
    split = _split_payload(plan)
    _write_json(output_root / "existing-vod-registry.json", existing)
    _write_json(output_root / "new-twitch-vod-discovery.json", discovery)
    split_path = output_root / "new-vod-split-manifest.json"
    _write_json(split_path, split)
    (output_root / "new-vod-split-manifest.sha256").write_text(
        f"{_sha256(split_path)}  {split_path.name}\n", encoding="ascii"
    )


def acquire(
    plan_path: Path,
    runtime_root: Path,
    *,
    stage: str,
    vod_ids: set[str] | None = None,
) -> None:
    plan = _load_plan(plan_path)
    cli = ensure_cli_on_path(auto_install=True)
    if not cli:
        raise RuntimeError("TwitchDownloaderCLI unavailable")
    os.environ["ACFV_STORAGE_ROOT"] = str(runtime_root)
    db_path = runtime_root / ("probe-library.sqlite" if stage == "probe" else "acfv.db")
    media_root = runtime_root / ("probe-media" if stage == "probe" else "library")
    library = LibraryService(db_path)
    service = VodDownloadService(
        library,
        media_root=media_root,
        metadata_fetcher=lambda source: fetch_twitch_vod_metadata(source, cli_path=cli),
    )
    receipt_path = runtime_root / "manifests" / f"download-receipts-{stage}.json"
    receipts: list[dict[str, Any]] = []
    if receipt_path.is_file():
        receipts = list(json.loads(receipt_path.read_text(encoding="utf-8")).get("rows") or [])
    for index, item in enumerate(plan["vods"]):
        if vod_ids and str(item["vod_id"]) not in vod_ids:
            continue
        receipts = [row for row in receipts if str(row.get("vod_id")) != str(item["vod_id"])]
        start_ms = int(item.get("probe_start_ms", item["range_start_ms"])) if stage == "probe" else int(item["range_start_ms"])
        if stage == "probe":
            end_ms = min(start_ms + 600_000, int(item["range_end_ms"]))
        else:
            end_ms = int(item["range_end_ms"])
        job = service.discover(item["url"], start_ms=start_ms, end_ms=end_ms)
        recording = library.get_recording(str(job.recording_id))
        metadata = json.loads(recording.download_metadata_json or "{}")
        metadata["validation_experiment"] = {
            "dataset_id": plan["dataset_id"],
            "dataset_version": plan["dataset_version"],
            "profile_version": plan["profile_version"],
            "role": item["role"],
            "unknown_partition": item.get("unknown_partition"),
            "stage": stage,
            "purpose": "local_validation",
        }
        recording.download_metadata_json = json.dumps(metadata, ensure_ascii=False)
        library.repository.save(recording)
        base_receipt = {
            "creator": item["creator"],
            "vod_id": item["vod_id"],
            "url": item["url"],
            "date": item["published_at"],
            "title": item["title"],
            "type": item["type"],
            "source_duration_seconds": item["duration_seconds"],
            "range_start_ms": start_ms,
            "range_end_ms": end_ms,
            "quality": item["quality"],
            "role": item["role"],
            "unknown_partition": item.get("unknown_partition"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "purpose": "local_validation",
            "raw_media_redistribution": "PROHIBITED",
        }
        try:
            job = service.download(job.id, auto_process=False, max_retries=2)
            final_path = Path(job.final_path or "")
            receipts.append(base_receipt | {
                "bytes": final_path.stat().st_size,
                "sha256": _sha256(final_path),
                "download_id": job.id,
                "recording_id": job.recording_id,
                "status": job.status.value,
                "local_path": str(final_path),
                "metadata": json.loads(job.metadata_json or "{}"),
            })
        except Exception as exc:
            failed = service.get(job.id) or job
            receipts.append(base_receipt | {
                "bytes": int(failed.downloaded_bytes or 0),
                "sha256": None,
                "download_id": failed.id,
                "recording_id": failed.recording_id,
                "status": failed.status.value,
                "local_path": failed.temp_path,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "metadata": json.loads(failed.metadata_json or "{}"),
            })
        _write_json(receipt_path, {
            "schema_version": "1.0", "stage": stage, "rows": receipts,
        })


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze and acquire NEW_TWITCH_VALIDATION_V1 via canonical services")
    parser.add_argument("command", choices=("freeze", "probe", "download"))
    parser.add_argument("--plan", type=Path, default=Path("config/new_twitch_validation_v1.json"))
    parser.add_argument("--runtime-root", type=Path, default=Path("var/new-twitch-validation"))
    parser.add_argument("--vod-id", action="append", default=[], help="Acquire only selected frozen VOD IDs")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.plan, args.runtime_root / "manifests")
    else:
        acquire(
            args.plan,
            args.runtime_root,
            stage="probe" if args.command == "probe" else "download",
            vod_ids=set(args.vod_id) or None,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
