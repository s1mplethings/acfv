from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from acfv.library.artifacts import (
    ArtifactLocator,
    ArtifactRootRegistry,
    migrate_artifact_locator,
    resolve_artifact_root,
)


def _recording(tmp_path: Path, artifact_root: str | None = None):
    return SimpleNamespace(id="recording-id", artifact_root=artifact_root, analysis_profile_json="{}")


def test_migration_dry_run_and_repeat_are_idempotent(tmp_path: Path) -> None:
    old = tmp_path / "old root" / "recording-id"
    recording = _recording(tmp_path, str(old))
    root = tmp_path / "new root"
    (root / "runs" / recording.id).mkdir(parents=True)

    dry = migrate_artifact_locator(recording, library_root_id="portable", library_root=root, dry_run=True)
    first = migrate_artifact_locator(recording, library_root_id="portable", library_root=root)
    second = migrate_artifact_locator(recording, library_root_id="portable", library_root=root)

    assert dry["dry_run"] is True and recording.artifact_root == str(old)
    assert first["changed"] is True and first["exists"] is True
    assert second["changed"] is False
    assert json.loads(recording.analysis_profile_json)["legacy_artifact_root"] == str(old)


def test_resolution_prefers_registered_relative_root_then_legacy(tmp_path: Path) -> None:
    old = tmp_path / "legacy" / "recording-id"
    old.mkdir(parents=True)
    root = tmp_path / "中文 root"
    relative = root / "runs" / "recording-id"
    relative.mkdir(parents=True)
    recording = _recording(tmp_path, str(old))
    migrate_artifact_locator(recording, library_root_id="portable", library_root=root)

    assert resolve_artifact_root(recording, roots={"portable": root}) == relative
    relative.rmdir()
    assert resolve_artifact_root(recording, roots={"portable": root}) == old


def test_missing_root_is_visible_and_invalid_relative_locator_is_rejected(tmp_path: Path) -> None:
    recording = _recording(tmp_path)
    migrate_artifact_locator(recording, library_root_id="portable", library_root=tmp_path)

    with pytest.raises(FileNotFoundError, match="No artifact root candidate"):
        resolve_artifact_root(recording, roots={"portable": tmp_path / "missing"}, require_exists=True)
    with pytest.raises(ValueError, match="safe relative"):
        ArtifactLocator("portable", "../escape")


def test_registry_survives_restart_and_root_can_change(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    registry = ArtifactRootRegistry(path)
    registry.register("portable", first_root)
    restarted = ArtifactRootRegistry(path)
    assert restarted.read()["portable"] == first_root.resolve()
    restarted.register("portable", second_root)
    assert ArtifactRootRegistry(path).read()["portable"] == second_root.resolve()
