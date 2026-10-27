from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def snapshot_check(output_file: Path, golden_dir: Path, case_id: str) -> tuple[bool, str]:
    golden_dir.mkdir(parents=True, exist_ok=True)
    meta_path = golden_dir / f"{case_id}.json"

    current_hash = _hash_file(output_file)

    if not meta_path.exists():
        meta_path.write_text(
            json.dumps(
                {"sha256": current_hash, "file": str(output_file.name)},
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        return True, f"[SNAPSHOT CREATED] {meta_path}"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ok = meta.get("sha256") == current_hash
    if ok:
        return True, "[SNAPSHOT OK]"
    return False, f"[SNAPSHOT MISMATCH] expected={meta.get('sha256')} got={current_hash}"
