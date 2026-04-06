from __future__ import annotations

import json
from pathlib import Path

from .snapshot import _hash_file


def diff_check(output_file: Path, golden_dir: Path, case_id: str) -> tuple[bool, str]:
    meta_path = golden_dir / f"{case_id}.json"
    if not meta_path.exists():
        return False, f"[DIFF MISSING GOLDEN] {meta_path}"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    expected_hash = meta.get("sha256")
    current_hash = _hash_file(output_file)
    ok = expected_hash == current_hash
    if ok:
        return True, "[DIFF OK]"
    return False, f"[DIFF MISMATCH] expected={expected_hash} got={current_hash}"
