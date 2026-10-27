from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VISUAL = ROOT / "var" / "creator-visual-identity-v1"
ADAPTIVE = ROOT / "var" / "creator-adaptive-v3-real"
EVIDENCE = ROOT / "evidence" / "validation"


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="959369cdac26c7853df583c36a7cfc9d0754c668")
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    manifest_source = VISUAL / "visual-dataset-manifest.jsonl"
    entries = [json.loads(line) for line in manifest_source.read_text(encoding="utf-8").splitlines() if line.strip()]
    write_json(EVIDENCE / "visual-dataset-manifest.json", {
        "schema_version": 1,
        "source_format": "jsonl",
        "source_sha256": sha256(manifest_source),
        "sample_count": len(entries),
        "entries": entries,
    })

    copies = {
        VISUAL / "visual-dataset-audit.json": "visual-dataset-audit.json",
        VISUAL / "benchmark" / "visual-model-benchmark.json": "visual-model-benchmark.json",
        VISUAL / "benchmark" / "visual-model-selection.json": "visual-model-selection.json",
        VISUAL / "benchmark" / "visual-holdout-results.json": "visual-holdout-results.json",
        VISUAL / "real-validation" / "visual-identity-spans-real.json": "visual-identity-spans-real.json",
        VISUAL / "real-validation" / "creator-visual-real-validation.json": "creator-visual-real-validation.json",
        ADAPTIVE / "creator-identity-v3-real.json": "creator-identity-v3-real.json",
        ADAPTIVE / "voice-profile-v3-real.json": "voice-profile-v3-real.json",
        ADAPTIVE / "trusted-speech-v3-real.json": "trusted-speech-v3-real.json",
        ADAPTIVE / "creator-lexicon-v3-real.json": "creator-lexicon-v3-real.json",
        ADAPTIVE / "adaptive-shadow-v3-real.json": "adaptive-shadow-v3-real.json",
        ADAPTIVE / "human-review-v4.json": "human-review-v4.json",
        ADAPTIVE / "creator-adaptive-full-test-receipt.json": "creator-adaptive-v3-real-run.json",
    }
    for source, name in copies.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, EVIDENCE / name)

    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{args.base}..HEAD"], cwd=ROOT,
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    pending = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    write_json(EVIDENCE / "creator-adaptive-full-change-manifest.json", {
        "schema_version": "1",
        "change_id": "creator-visual-identity-full-v3",
        "summary": "Two-stage open-set Creator visual identity and visual-backed Creator-Adaptive v3 shadow pipeline.",
        "capabilities": [
            "avatar_identity_provider", "creator_visual_identity", "creator_identity", "voice_profile",
            "trusted_speech_memory", "creator_lexicon", "creator_adaptive_asr", "human_review",
        ],
        "files_changed": sorted(set(changed + [row[3:] for row in pending if len(row) > 3])),
        "behavior_change": True,
        "contract_change": True,
        "migration_required": False,
        "compatibility": "Additive creator_profile_v3; v1/v2 data and generic ASR remain isolated and available.",
        "risks": [
            "Visual precision has recording-prior proxy truth but not completed human frame labels.",
            "Adaptive WER is not evaluated without independent human transcripts.",
            "Creator lexicon remains empty because the strict repeated-trusted-term gate did not pass.",
        ],
    })

    config = ROOT / "config" / "creator_visual_identity.json"
    classifier = ROOT / "resources" / "creator_visual_identity_v1" / "identity-model.joblib"
    write_json(EVIDENCE / "creator-visual-model-artifact-audit.json", {
        "config": str(config.relative_to(ROOT)),
        "config_sha256": sha256(config),
        "classifier": str(classifier.relative_to(ROOT)),
        "classifier_sha256": sha256(classifier),
        "classifier_bytes": classifier.stat().st_size,
        "large_encoder_weight_bundled": False,
        "presence_weight_bundled": False,
    })
    print(json.dumps({"evidence": str(EVIDENCE), "files": len(copies) + 4}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
