from __future__ import annotations

from pathlib import Path
from typing import Any


def invariants_check(outputs: dict[str, Path], rules: dict[str, Any]) -> tuple[bool, str]:
    required = rules.get("required_outputs", [])
    for name in required:
        if name not in outputs:
            return False, f"[INVARIANTS MISSING OUTPUT] {name}"

    global_min_size = int(rules.get("min_size_bytes", 1))
    for name, path in outputs.items():
        if not path.exists():
            return False, f"[INVARIANTS MISSING FILE] {name}"
        if path.stat().st_size < global_min_size:
            return False, f"[INVARIANTS FILE TOO SMALL] {name}"

    file_rules = rules.get("file_rules", {})
    for name, rule in file_rules.items():
        if name not in outputs:
            return False, f"[INVARIANTS MISSING OUTPUT] {name}"
        path = outputs[name]
        min_size = int(rule.get("min_size_bytes", global_min_size))
        if path.stat().st_size < min_size:
            return False, f"[INVARIANTS FILE TOO SMALL] {name}"

    return True, "[INVARIANTS OK]"
