#!/usr/bin/env python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, List, Tuple

# contract_checks.py
#
# 目的：
# - 把“输出契约”从文档约定变成自动失败的质量门（见 docs/03_quality_gates.md）。
# - 校验实际产物是否至少满足 `specs/contract_output/*.schema.json` 的最小关键字段。
#
# 验证策略：
# - 如果未找到候选产物，认为通过（兼容本地未跑管线的场景）。
# - 若发现产物，要求对象存在 `schema_version` 且具备核心字段。

ArtifactCheck = Tuple[str, Iterable[Path], Callable[[Path], List[str]]]

SEGMENT_PATHS = [
    Path("work") / "segments.json",
    Path("runs") / "out" / "segments.json",
]

MANIFEST_PATHS = [
    Path("work") / "clips_manifest.json",
    Path("runs") / "out" / "clips_manifest.json",
]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover - defensive
        return {"__error__": f"JSON parse error: {e}"}


def _validate_segments(path: Path) -> List[str]:
    data = _load_json(path)
    if isinstance(data, dict) and "__error__" in data:
        return [f"{path}: {data['__error__']}"]
    errors: List[str] = []
    if not isinstance(data, dict):
        return [f"{path}: expected object with schema_version and segments[] (see specs/contract_output/segments.schema.json)"]

    if not isinstance(data.get("schema_version"), str) or not data["schema_version"].strip():
        errors.append(f"{path}: missing schema_version")
    if data.get("units") not in (None, "ms"):
        errors.append(f"{path}: units must be 'ms'")
    segments = data.get("segments")
    if not isinstance(segments, list):
        errors.append(f"{path}: segments should be a list")
        return errors

    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"{path}: segments[{idx}] expected object")
            continue
        for field in ("start_ms", "end_ms", "score", "rank"):
            if field not in seg:
                errors.append(f"{path}: segments[{idx}] missing {field}")
    return errors


def _validate_manifest(path: Path) -> List[str]:
    data = _load_json(path)
    if isinstance(data, dict) and "__error__" in data:
        return [f"{path}: {data['__error__']}"]
    errors: List[str] = []
    if not isinstance(data, dict):
        return [f"{path}: expected object with schema_version and clips[] (see specs/contract_output/clips_manifest.schema.json)"]

    if not isinstance(data.get("schema_version"), str) or not data["schema_version"].strip():
        errors.append(f"{path}: missing schema_version")
    if data.get("units") not in (None, "ms"):
        errors.append(f"{path}: units must be 'ms'")

    clips = data.get("clips")
    if not isinstance(clips, list):
        errors.append(f"{path}: clips should be a list")
        return errors

    for idx, clip in enumerate(clips):
        if not isinstance(clip, dict):
            errors.append(f"{path}: clips[{idx}] expected object")
            continue
        for field in ("clip_id", "start_ms", "end_ms"):
            if field not in clip:
                errors.append(f"{path}: clips[{idx}] missing {field}")
        output = clip.get("output")
        if not isinstance(output, dict) or "video" not in output:
            errors.append(f"{path}: clips[{idx}].output.video missing")
        duration = clip.get("duration_ms")
        if duration is not None:
            try:
                dur = int(duration)
                if dur < 240_000 or dur > 300_000:
                    errors.append(f"{path}: clips[{idx}].duration_ms expected 240000-300000 (4-5min), got {dur}")
            except Exception:
                errors.append(f"{path}: clips[{idx}].duration_ms invalid")
    return errors


ARTIFACTS: List[ArtifactCheck] = [
    ("segments", SEGMENT_PATHS, _validate_segments),
    ("clips_manifest", MANIFEST_PATHS, _validate_manifest),
]


def main() -> int:
    existing: List[Tuple[str, Path, Callable[[Path], List[str]]]] = []
    for name, paths, validator in ARTIFACTS:
        for path in paths:
            if path.exists():
                existing.append((name, path, validator))

    if not existing:
        print("[contract_checks] no known artifact files found (ok for template)")
        return 0

    errors: list[str] = []
    for name, path, validator in existing:
        errors.extend(validator(path))

    if errors:
        print("[contract_checks] FAIL")
        for e in errors:
            print(" -", e)
        return 1

    print("[contract_checks] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
