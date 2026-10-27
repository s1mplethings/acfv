from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from acfv.library import ArtifactRootRegistry, LibraryService, analyze_transcript, migrate_artifact_locator
from acfv.library.artifacts import metadata_for
from acfv.library.transcript_quality import merge_analysis_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate transcript-derived language profiles and portable artifact locators.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--library-root-id", default="real-library-build")
    parser.add_argument("--creator-slug", default="anny")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate(args: argparse.Namespace) -> dict:
    db = args.db.resolve()
    library_root = args.library_root.resolve()
    if not args.dry_run and args.backup:
        backup = args.backup.resolve()
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(db, backup)
    library = LibraryService(db)
    creator = library.repository.get_creator_by_slug(args.creator_slug)
    if creator is None:
        raise KeyError(f"Unknown Creator slug: {args.creator_slug}")
    language_rows = []
    raw_hashes_before = {}
    for recording in library.list_recordings(creator.id):
        transcript_path = library_root / "runs" / recording.id / "work" / "transcript_merged.json"
        if not transcript_path.is_file():
            raise FileNotFoundError(f"Missing transcript for {recording.id}: {transcript_path}")
        raw_hash = sha256(transcript_path)
        raw_hashes_before[recording.id] = raw_hash
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        existing = metadata_for(recording)
        previous_profile = existing.get("recording_language_profile") or {}
        analyzed_at = (
            previous_profile.get("last_analyzed_at")
            if existing.get("transcript_quality", {}).get("raw_transcript_sha256") == raw_hash
            else datetime.now(timezone.utc).isoformat()
        )
        profile, spans = analyze_transcript(
            transcript,
            metadata_language=str(transcript.get("language") or "unknown"),
            analyzed_at=analyzed_at,
        )
        quality_path = transcript_path.with_name("transcript_quality.json")
        quality_payload = {
            "schema_version": "1.0",
            "raw_transcript_path": str(transcript_path),
            "raw_transcript_sha256": raw_hash,
            "raw_transcript_preserved": True,
            "recording_language_profile": profile.to_dict(),
            "spans": [item.to_dict() for item in spans],
        }
        old_language = transcript.get("language") or "unknown"
        additions = {
            "recording_language_profile": profile.to_dict(),
            "transcript_quality": {
                "schema_version": "1.0",
                "raw_transcript_sha256": raw_hash,
                "raw_transcript_preserved": True,
                "derived_artifact": "work/transcript_quality.json",
                "span_count": len(spans),
            },
        }
        next_json = merge_analysis_metadata(recording.analysis_profile_json, additions)
        changed = next_json != recording.analysis_profile_json or not quality_path.is_file()
        if not args.dry_run:
            temporary = quality_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(quality_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(quality_path)
            recording.analysis_profile_json = next_json
            library.repository.save(recording)
        language_rows.append({
            "recording_id": recording.id,
            "old_language": old_language,
            "new_primary_language": profile.primary_language,
            "secondary_languages": list(profile.secondary_languages),
            "mixed_language": profile.mixed_language,
            "confidence": profile.confidence,
            "reason": f"{profile.source} overrides recording-wide metadata when transcript evidence conflicts",
            "raw_transcript_sha256": raw_hash,
            "raw_preserved": True,
            "changed": changed,
        })

    artifact_rows = []
    for recording in library.list_recordings():
        expected = library_root / "runs" / recording.id
        old = Path(recording.artifact_root) if recording.artifact_root else None
        if not expected.is_dir() or not old or old.exists():
            continue
        row = migrate_artifact_locator(
            recording,
            library_root_id=args.library_root_id,
            library_root=library_root,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            library.repository.save(recording)
        artifact_rows.append(row)
    if not args.dry_run:
        ArtifactRootRegistry().register(args.library_root_id, library_root)
    raw_hashes_after = {
        recording_id: sha256(library_root / "runs" / recording_id / "work" / "transcript_merged.json")
        for recording_id in raw_hashes_before
    }
    report = {
        "schema_version": "1.0",
        "dry_run": args.dry_run,
        "database": str(db),
        "backup": str(args.backup.resolve()) if args.backup else None,
        "library_root_id": args.library_root_id,
        "language_migration": language_rows,
        "artifact_migration": artifact_rows,
        "raw_transcript_hashes_unchanged": raw_hashes_before == raw_hashes_after,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = migrate(parse_args())
    print(json.dumps({
        "dry_run": report["dry_run"],
        "language_recordings": len(report["language_migration"]),
        "artifact_roots": len(report["artifact_migration"]),
        "raw_transcript_hashes_unchanged": report["raw_transcript_hashes_unchanged"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
