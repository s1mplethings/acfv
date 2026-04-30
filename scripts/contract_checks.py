#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Iterable, List, Sequence, Tuple

from acfv.pipeline.contracts import validate_contract_artifacts

ArtifactCheck = Tuple[str, Sequence[Path], Callable[[Path], List[str]]]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return {"__error__": f"JSON parse error: {exc}"}


def _validate_segments(path: Path) -> List[str]:
    data = _load_json(path)
    if isinstance(data, dict) and "__error__" in data:
        return [f"{path}: {data['__error__']}"]
    if not isinstance(data, dict):
        return [f"{path}: expected object with schema_version and segments[]"]

    errors: List[str] = []
    if not isinstance(data.get("schema_version"), str) or not data["schema_version"].strip():
        errors.append(f"{path}: missing schema_version")
    if data.get("units") not in (None, "ms"):
        errors.append(f"{path}: units must be 'ms'")

    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.append(f"{path}: segments should be a non-empty list")
        return errors

    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"{path}: segments[{idx}] expected object")
            continue
        for field in ("start_ms", "end_ms", "score"):
            if field not in seg:
                errors.append(f"{path}: segments[{idx}] missing {field}")
    return errors


def _validate_manifest(path: Path) -> List[str]:
    data = _load_json(path)
    if isinstance(data, dict) and "__error__" in data:
        return [f"{path}: {data['__error__']}"]
    if not isinstance(data, dict):
        return [f"{path}: expected object with schema_version and clips[]"]

    errors: List[str] = []
    if not isinstance(data.get("schema_version"), str) or not data["schema_version"].strip():
        errors.append(f"{path}: missing schema_version")
    if data.get("units") not in (None, "ms"):
        errors.append(f"{path}: units must be 'ms'")

    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        errors.append(f"{path}: clips should be a non-empty list")
        return errors

    if "clip_count" in data and data.get("clip_count") != len(clips):
        errors.append(f"{path}: clip_count must equal len(clips)")

    for idx, clip in enumerate(clips):
        if not isinstance(clip, dict):
            errors.append(f"{path}: clips[{idx}] expected object")
            continue
        for field in ("clip_id", "start_ms", "end_ms", "output"):
            if field not in clip:
                errors.append(f"{path}: clips[{idx}] missing {field}")
        output = clip.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("video"), str) or not output.get("video"):
            errors.append(f"{path}: clips[{idx}].output.video missing")
    return errors


def _artifact_checks_for_root(root: Path) -> List[ArtifactCheck]:
    work_dir = root / "work"
    return [
        (
            "segments",
            [
                work_dir / "segments.json",
                work_dir / "selected_segments.json",
                Path("work") / "segments.json",
                Path("work") / "selected_segments.json",
                Path("runs") / "out" / "segments.json",
            ],
            _validate_segments,
        ),
        (
            "clips_manifest",
            [
                work_dir / "clips_manifest.json",
                root / "clips_manifest.json",
                Path("work") / "clips_manifest.json",
                Path("runs") / "out" / "clips_manifest.json",
            ],
            _validate_manifest,
        ),
    ]


def _collect_existing_artifacts(root: Path) -> List[Tuple[str, Path, Callable[[Path], List[str]]]]:
    existing: List[Tuple[str, Path, Callable[[Path], List[str]]]] = []
    seen: set[Path] = set()
    for name, paths, validator in _artifact_checks_for_root(root):
        for path in paths:
            candidate = path if path.is_absolute() else path.resolve()
            if candidate in seen or not candidate.exists():
                continue
            seen.add(candidate)
            existing.append((name, candidate, validator))
    return existing


def _validate_explicit_run_dir(run_dir: Path) -> List[str]:
    errors = validate_contract_artifacts(run_dir)
    work_dir = run_dir / "work"
    for validator, target in (
        (_validate_segments, work_dir / "selected_segments.json"),
        (_validate_manifest, work_dir / "clips_manifest.json"),
    ):
        if target.exists():
            errors.extend(validator(target))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate clip workflow contract outputs")
    parser.add_argument("--run-dir", help="Validate a specific clip workflow run directory")
    parser.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail if no recognizable contract artifacts are found",
    )
    args = parser.parse_args(argv)

    if args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        work_dir = run_dir / "work"
        if not work_dir.exists():
            print(f"[contract_checks] FAIL: missing work dir: {work_dir}")
            return 1
        errors = _validate_explicit_run_dir(run_dir)
        if errors:
            print("[contract_checks] FAIL")
            for err in errors:
                print(" -", err)
            return 1
        print("[contract_checks] PASS")
        return 0

    existing = _collect_existing_artifacts(Path.cwd())
    if not existing:
        if args.require_artifacts:
            print("[contract_checks] FAIL: no known artifact files found")
            return 1
        print("[contract_checks] no known artifact files found (ok for template)")
        return 0

    errors: List[str] = []
    for _name, path, validator in existing:
        errors.extend(validator(path))

    if errors:
        print("[contract_checks] FAIL")
        for err in errors:
            print(" -", err)
        return 1

    print("[contract_checks] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
