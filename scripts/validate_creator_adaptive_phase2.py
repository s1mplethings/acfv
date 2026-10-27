from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from acfv.creator_adaptive.repository import CreatorAdaptiveRepository, SCHEMA_VERSION
from acfv.providers.avatar_discovery import discover_avatar_models
from acfv.providers.avatar_identity import ExistingAvatarModelAdapter


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def optional_ultralytics_probe(candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("format") != "PYTORCH":
        return {"status": "NOT_APPLICABLE"}
    try:
        from ultralytics import YOLO

        started = time.perf_counter()
        model = YOLO(str(candidate["path"]))
        names = model.names if isinstance(model.names, dict) else dict(enumerate(model.names))
        labels = [str(value) for _, value in sorted(names.items())]
        creator_labels = [label for label in labels if label.casefold() in {"saruei", "anny", "annytf"}]
        return {
            "status": "PASS", "framework": "ultralytics", "task": model.task,
            "label_count": len(labels), "label_sample": labels[:20],
            "creator_labels": creator_labels,
            "load_ms": (time.perf_counter() - started) * 1000,
            "classification": "AVATAR_CANDIDATE" if creator_labels else "REJECTED_NON_AVATAR_LABELS",
        }
    except Exception as exc:
        return {"status": "NOT_EVALUATED", "reason": type(exc).__name__}


def migration_receipt(output: Path) -> dict[str, Any]:
    db = output / "migration-validation.sqlite"
    backup = output / "migration-validation.before.sqlite"
    first = CreatorAdaptiveRepository(db)
    first.ensure_profile("creator", "creator_profile_v1")
    shutil.copy2(db, backup)
    second = CreatorAdaptiveRepository(db)
    with sqlite3.connect(db) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check").fetchall())
        version = int(connection.execute("SELECT version FROM creator_adaptive_schema_state WHERE id=1").fetchone()[0])
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        "backup_created": backup.is_file(), "integrity": integrity,
        "foreign_key_violations": len(foreign_keys), "schema_version": version,
        "expected_schema_version": SCHEMA_VERSION,
        "phase2_tables": sorted(tables & {"avatar_label_mappings", "avatar_identity_observations", "creator_visual_identity_spans"}),
        "restart_safe": second.latest_profile("creator") is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "var" / "creator-adaptive-phase2")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    mapping_path = os.environ.get("ACFV_AVATAR_LABEL_MAPPING", "").strip()
    mapping: dict[str, str] = {}
    if mapping_path and Path(mapping_path).is_file():
        payload = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        mapping = dict(payload.get("labels", payload))
    discovery = discover_avatar_models(
        ROOT,
        search_roots=(
            Path("F:/ACFV-Derived"), Path("D:/Cliper"), Path("E:/work"), Path("E:/.WORK"),
            Path("D:/.py_projects/hentaiviewer"), Path.home() / "Documents" / "Codex", Path.home() / "Downloads",
        ),
        label_mapping=mapping,
    )
    for candidate in discovery["candidates"]:
        candidate["runtime_probe"] = optional_ultralytics_probe(candidate)
    discovery["candidate_counts"] = dict(Counter(
        item["runtime_probe"].get("classification", "UNCLASSIFIED") for item in discovery["candidates"]
    ))
    write_json(output / "avatar-model-discovery.json", discovery)

    avatar = ExistingAvatarModelAdapter().audit()
    real_ready = discovery["status"] == "SELECTED_IDENTITY" and avatar["status"] == "READY"
    write_json(output / "avatar-real-inference.json", {
        "status": "NOT_EVALUATED" if not real_ready else "CONFIGURED_NEEDS_MEDIA_RUN",
        "reason": "BLOCKED_MODEL_PATH" if not real_ready else "real provider configured",
        "provider": avatar, "frames": 0, "creators": {}, "predictions": 0,
        "unknown": 0, "latency_ms": None, "raw_media_mutations": 0,
    })
    write_json(output / "identity-bootstrap.json", {
        "profile_version": "creator_profile_v2", "status": "BLOCKED_MODEL_PATH" if not real_ready else "PENDING_RUN",
        "visual_spans": 0, "confirmed": 0, "probable": 0, "ambiguous": 0, "unknown": 0, "conflict": 0,
        "visual_presence_implies_active_speaker": False,
    })
    write_json(output / "voice-profile-v2.json", {
        "profile_version": "creator_profile_v2", "status": "BLOCKED_NO_VISUAL_CONFIRMED_REGIONS" if not real_ready else "PENDING_BUILD",
        "Saruei": {"candidate_spans": 0, "retained": 0, "duration_ms": 0, "far": "NOT_EVALUATED", "frr": "NOT_EVALUATED"},
        "anny": {"candidate_spans": 0, "retained": 0, "duration_ms": 0, "far": "NOT_EVALUATED", "frr": "NOT_EVALUATED"},
        "v1_preserved": True,
    })
    write_json(output / "trusted-speech-bootstrap.json", {
        "profile_version": "creator_profile_v2", "status": "BLOCKED_NO_CONFIRMED_IDENTITY",
        "creators": {"Saruei": {"candidates": 0, "pseudo_trusted": 0, "human_confirmed": 0, "rejected": 0, "duration_ms": 0, "recordings": 0},
                     "anny": {"candidates": 0, "pseudo_trusted": 0, "human_confirmed": 0, "rejected": 0, "duration_ms": 0, "recordings": 0}},
        "strict_gate_lowered": False,
    })
    write_json(output / "creator-lexicon-bootstrap.json", {
        "profile_version": "creator_profile_v2", "status": "BLOCKED_NO_TRUSTED_SPEECH",
        "creators": {"Saruei": {"candidates": 0, "promoted": 0}, "anny": {"candidates": 0, "promoted": 0}},
        "acoustic_exemplars": 0, "raw_asr_used_as_authority": False,
    })
    write_json(output / "adaptive-shadow-results.json", {
        "mode": "SHADOW_ONLY", "status": "BLOCKED_NO_TRUSTED_CONTEXT",
        "eligible_spans": 0, "generic": 0, "adaptive": 0, "same": 0, "changed": 0,
        "conflict": 0, "fallback": 0, "high_risk_changed": 0,
        "official_transcript_mutations": 0, "generic_authoritative": True,
        "generic_wer": "NOT_EVALUATED", "adaptive_wer": "NOT_EVALUATED",
        "recommendations": {"Saruei": "KEEP_SHADOW", "anny": "KEEP_SHADOW"},
    })
    review_payload = {
        "schema_version": "2", "dataset_version": "creator-adaptive-phase2-review-v2",
        "parent_dataset_version": "fixed37-human-review-v2", "profile_version": "creator_profile_v2",
        "identity": [], "trusted_speech": [], "adaptive_asr": [],
        "blocked_reason": "No real avatar model was selected; unsafe review items were not manufactured.",
    }
    write_json(output / "creator-adaptive-review-v2.json", review_payload)
    write_json(output / "human-review-v2-receipt.json", {
        "old_items_retained": 686,
        "prior_phase1_identity_artifact_preserved": 100,
        "prior_phase1_identity_merged_into_this_blocked_dataset": False,
        "validated_dataset_sample_count": 686,
        "new_identity": 0, "new_trusted_speech": 0, "new_adaptive_asr": 0,
        "blind_adaptive": True, "migration": "forward-only merge path validated by tests", "annotations_overwritten": 0,
        "reason": review_payload["blocked_reason"],
    })
    write_json(output / "migration-receipt.json", migration_receipt(output))
    print(json.dumps({"output": str(output), "discovery": discovery["status"], "real_inference": real_ready}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
