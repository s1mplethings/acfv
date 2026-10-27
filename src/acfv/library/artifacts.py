from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from acfv.runtime.storage import storage_root


@dataclass(frozen=True)
class ArtifactLocator:
    library_root_id: str
    relative_artifact_path: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        relative = PurePosixPath(self.relative_artifact_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Artifact locator must be a safe relative path")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class ArtifactRootRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or storage_root() / "artifact_roots.json")

    def read(self) -> dict[str, Path]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {str(key): Path(value) for key, value in payload.get("roots", {}).items()}

    def register(self, root_id: str, path: Path | str) -> None:
        roots = self.read()
        roots[root_id] = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"schema_version": "1.0", "roots": {key: str(value) for key, value in sorted(roots.items())}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def metadata_for(recording: Any) -> dict[str, Any]:
    try:
        return json.loads(recording.analysis_profile_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def locator_for(recording: Any) -> ArtifactLocator | None:
    payload = metadata_for(recording).get("artifact_locator")
    if not isinstance(payload, dict):
        return None
    try:
        return ArtifactLocator(
            library_root_id=str(payload["library_root_id"]),
            relative_artifact_path=str(payload["relative_artifact_path"]),
            schema_version=str(payload.get("schema_version", "1.0")),
        )
    except (KeyError, ValueError):
        return None


def resolve_artifact_root(
    recording: Any,
    *,
    roots: dict[str, Path | str] | None = None,
    extra_roots: Iterable[Path | str] = (),
    require_exists: bool = False,
) -> Path | None:
    metadata = metadata_for(recording)
    locator = locator_for(recording)
    configured = {key: Path(value) for key, value in (roots or ArtifactRootRegistry().read()).items()}
    candidates: list[Path] = []
    if locator:
        registered = configured.get(locator.library_root_id)
        if registered:
            candidates.append(registered / Path(locator.relative_artifact_path))
        candidates.extend(Path(root) / Path(locator.relative_artifact_path) for root in extra_roots)
    value = recording.artifact_root
    if value:
        candidate = Path(value)
        if candidate.is_absolute():
            candidates.append(candidate)
        elif locator is None:
            candidates.extend(Path(root) / candidate for root in extra_roots)
    legacy = metadata.get("legacy_artifact_root")
    if legacy:
        candidates.append(Path(str(legacy)))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    existing = next((candidate for candidate in unique if candidate.exists()), None)
    if existing is not None:
        return existing
    if require_exists:
        rendered = ", ".join(str(item) for item in unique) or "<none>"
        raise FileNotFoundError(f"No artifact root candidate exists: {rendered}")
    return unique[0] if unique else None


def migrate_artifact_locator(
    recording: Any,
    *,
    library_root_id: str,
    library_root: Path | str,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(library_root).expanduser().resolve()
    canonical = ArtifactLocator(library_root_id, f"runs/{recording.id}")
    before = recording.artifact_root
    metadata = metadata_for(recording)
    legacy = metadata.get("legacy_artifact_root") or before
    after_metadata = dict(metadata)
    after_metadata["artifact_locator"] = canonical.to_dict()
    if legacy:
        after_metadata["legacy_artifact_root"] = str(legacy)
    changed = metadata != after_metadata
    if not dry_run:
        recording.analysis_profile_json = json.dumps(after_metadata, ensure_ascii=False, sort_keys=True)
    resolved = root / Path(canonical.relative_artifact_path)
    return {
        "recording_id": recording.id,
        "before": before,
        "after": canonical.to_dict(),
        "legacy_artifact_root": str(legacy) if legacy else None,
        "resolved_path": str(resolved),
        "exists": resolved.exists(),
        "changed": changed,
        "dry_run": dry_run,
    }
