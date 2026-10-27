#!/usr/bin/env python3
"""Create a fresh Creator Library using only public production service APIs.

Input manifests describe media ownership and derived validation ranges.  The
harness never inserts database rows directly and does not contain creator- or
recording-specific branches.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from acfv.library import LibraryService
from acfv.library.repository import SCHEMA_VERSION


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _quick_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
        if size > 1024 * 1024:
            handle.seek(max(0, size - 1024 * 1024))
            digest.update(handle.read(1024 * 1024))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest()


def _integrity(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        schema = connection.execute(
            "SELECT version FROM library_schema_state WHERE id = 1"
        ).fetchone()
    return {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "schema_version": schema[0] if schema else None,
    }


def bootstrap(*, root: Path, inventory_path: Path, proxy_path: Path,
              creator_map_path: Path) -> dict[str, Any]:
    root = root.resolve()
    db_path = root / "library" / "acfv.db"
    if db_path.exists():
        raise FileExistsError(f"Fresh bootstrap requires an absent database: {db_path}")
    source_inventory = _read(inventory_path)
    source_rows = source_inventory.get("recordings", source_inventory)
    proxies = _read(proxy_path)
    creator_map = _read(creator_map_path)
    if not isinstance(source_rows, list) or not isinstance(proxies, list):
        raise ValueError("Inventory and proxy manifests must contain lists")

    service = LibraryService(db_path)
    creators = {}
    sources = {}
    for display_name in sorted(set(creator_map.values())):
        creator = service.create_creator(display_name)
        creators[display_name] = creator
        sources[display_name] = service.add_source(
            creator.id, platform="local", external_id=f"current-machine-{creator.slug}",
            channel_name=display_name, source_type="local_library",
            metadata={"validation_root": str(root)},
        )

    registered = []
    for row in source_rows:
        historical_id = str(row.get("recording_id") or row.get("id") or "")
        display_name = creator_map.get(historical_id)
        if not display_name:
            raise KeyError(f"No creator mapping for recording {historical_id}")
        path = Path(str(row["local_path"])).resolve()
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(path)
        recording = service.register_recording(
            creator_id=creators[display_name].id,
            source_id=sources[display_name].id,
            title=str(row.get("title") or path.stem), local_path=path,
            source_type="current_machine_raw", content_type=str(row.get("content_type") or "other"),
        )
        registered.append({
            "kind": "RAW", "recording_id": recording.id,
            "historical_recording_id": historical_id, "creator": display_name,
            "title": recording.title, "local_path": recording.local_path,
            "duration_ms": recording.duration_ms, "size_bytes": recording.file_size,
            "quick_fingerprint": _quick_fingerprint(path),
        })

    for row in proxies:
        display_name = str(row["creator"])
        if display_name not in creators:
            raise KeyError(f"Unknown proxy creator: {display_name}")
        path = Path(str(row["local_path"])).resolve()
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(path)
        recording = service.register_recording(
            creator_id=creators[display_name].id,
            source_id=sources[display_name].id,
            title=str(row.get("title") or path.stem), local_path=path,
            source_type="derived_validation_range", content_type=str(row.get("content_type") or "other"),
            analysis_profile=dict(row.get("analysis_profile") or {}), profile_source="validation_manifest",
        )
        registered.append({
            "kind": "PROCESSING_PROXY", "recording_id": recording.id,
            "creator": display_name, "title": recording.title,
            "local_path": recording.local_path, "duration_ms": recording.duration_ms,
            "size_bytes": recording.file_size, "source_recording_id": row.get("source_recording_id"),
            "source_offset_ms": row.get("source_offset_ms"),
            "content_type": recording.content_type, "quick_fingerprint": _quick_fingerprint(path),
        })

    payload = {
        "schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root), "database": str(db_path), "production_api_only": True,
        "supported_schema_version": SCHEMA_VERSION,
        "creators": len(service.list_creators()), "sources": len(service.list_sources()),
        "recordings": len(service.list_recordings()), "raw_recordings": len(source_rows),
        "processing_proxies": len(proxies),
        "processing_duration_ms": sum(int(row.get("duration_ms") or 0) for row in registered if row["kind"] == "PROCESSING_PROXY"),
        "registered": registered, "integrity": _integrity(db_path),
    }
    evidence = root / "evidence" / "validation"
    _write(evidence / "fresh-library-inventory.json", payload)
    _write(evidence / "fresh-db-bootstrap.json", {
        "database": str(db_path), "created_from_absent": True,
        "production_migrations": True, "production_api_only": True,
        "counts": {key: payload[key] for key in ("creators", "sources", "recordings")},
        "integrity": payload["integrity"],
    })
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--proxies", type=Path, required=True)
    parser.add_argument("--creator-map", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(bootstrap(root=args.root, inventory_path=args.inventory,
                               proxy_path=args.proxies, creator_map_path=args.creator_map),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
