from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def should_record_failure(report: dict[str, Any]) -> bool:
    return not (report.get("sut_ok") and report.get("oracle_ok"))


def append_problem_registry(report: dict[str, Any], registry_path: Path) -> None:
    if not should_record_failure(report):
        return

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "input": report.get("input"),
        "adapter": report.get("adapter"),
        "oracle": report.get("oracle"),
        "sut_ok": report.get("sut_ok"),
        "oracle_ok": report.get("oracle_ok"),
        "oracle_msg": report.get("oracle_msg"),
        "error": report.get("error"),
        "stdout": report.get("stdout"),
        "stderr": report.get("stderr"),
        "outputs": report.get("outputs"),
    }
    with registry_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
