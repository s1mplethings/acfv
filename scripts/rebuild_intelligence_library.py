"""Versioned Moment rebuild from existing transcript/chat artifacts.

This script never writes to the source database or media artifacts.  It builds a
SQLite staging copy, migrates Clip/Feedback Moment references, validates it, and
only then atomically promotes the copy.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from acfv.library import LibraryService
from acfv.moments import MomentFinalizer


def _backup(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)


def _overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _mapping(old_rows, rebuilt_by_recording):
    rows = []
    for old in old_rows:
        candidates = rebuilt_by_recording[old.recording_id]
        best = max(
            candidates,
            key=lambda new: (
                _overlap(old.start_ms, old.end_ms, new.start_ms, new.end_ms),
                -abs(old.start_ms - new.start_ms),
            ),
        )
        intersection = _overlap(old.start_ms, old.end_ms, best.start_ms, best.end_ms)
        union = max(old.end_ms, best.end_ms) - min(old.start_ms, best.start_ms)
        rows.append(
            {
                "old_moment_id": old.id,
                "new_moment_id": best.id,
                "recording_id": old.recording_id,
                "old_start_ms": old.start_ms,
                "old_end_ms": old.end_ms,
                "new_start_ms": best.start_ms,
                "new_end_ms": best.end_ms,
                "anchor_overlap_ms": intersection,
                "anchor_iou": round(intersection / union, 6) if union else 1.0,
            }
        )
    return rows


def _migrate_and_prune(database: Path, mapping, new_ids: set[str]) -> dict:
    mapped = {row["old_moment_id"]: row["new_moment_id"] for row in mapping}
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        clip_rows = connection.execute("SELECT id, moment_id FROM library_clips").fetchall()
        feedback_rows = connection.execute("SELECT id, moment_id FROM library_feedback").fetchall()
        for identity, old_id in clip_rows:
            connection.execute("UPDATE library_clips SET moment_id=? WHERE id=?", (mapped[old_id], identity))
        for identity, old_id in feedback_rows:
            connection.execute("UPDATE library_feedback SET moment_id=? WHERE id=?", (mapped[old_id], identity))
        placeholders = ",".join("?" for _ in new_ids)
        connection.execute(f"DELETE FROM library_moments WHERE id NOT IN ({placeholders})", tuple(new_ids))
        connection.commit()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        duplicate_keys = connection.execute(
            "SELECT stable_key, COUNT(*) FROM library_moments GROUP BY stable_key HAVING COUNT(*) > 1"
        ).fetchall()
        final_count = connection.execute("SELECT COUNT(*) FROM library_moments WHERE status='FINAL'").fetchone()[0]
    return {
        "clips_migrated": len(clip_rows),
        "feedback_migrated": len(feedback_rows),
        "foreign_key_errors": foreign_key_errors,
        "duplicate_stable_keys": duplicate_keys,
        "final_moment_count": final_count,
    }


def _distribution(moments) -> dict[str, int]:
    buckets = Counter()
    punctuation_only = 0
    single_token_low_info = 0
    for moment in moments:
        duration = moment.end_ms - moment.start_ms
        key = "lt_5s" if duration < 5_000 else "5_20s" if duration < 20_000 else "20_50s" if duration < 50_000 else "50_60s" if duration < 60_000 else "60_90s" if duration <= 90_000 else "gt_90s"
        buckets[key] += 1
        content = "".join(char for char in moment.transcript_text if char.isalnum())
        punctuation_only += int(not content)
        tokens = re.findall(r"[\w\u3400-\u9fff]+", moment.transcript_text.casefold())
        single_token_low_info += int(len(set(tokens)) <= 1 and len(content) < 8)
    return {
        **{key: buckets[key] for key in ("lt_5s", "5_20s", "20_50s", "50_60s", "60_90s", "gt_90s")},
        "punctuation_only": punctuation_only,
        "single_token_low_info": single_token_low_info,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifact-fallback-root", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    staging = output.with_suffix(output.suffix + ".staging")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing rebuild output: {output}")
    if staging.exists():
        staging.unlink()  # Recover only this script's exact, unpromoted staging path.
    output.parent.mkdir(parents=True, exist_ok=True)
    args.mapping.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    _backup(source, staging)

    library = LibraryService(staging)
    old_moments = library.repository.list_moments()
    before = _distribution(old_moments)
    rebuilt_by_recording = {}
    finalizer = MomentFinalizer(library.repository)
    for number, recording in enumerate(library.list_recordings(), 1):
        artifact_root = Path(recording.artifact_root or "")
        if not artifact_root.is_dir() and args.artifact_fallback_root:
            artifact_root = args.artifact_fallback_root / recording.id
        rebuilt = finalizer.finalize_artifacts(
            recording.id,
            artifact_root=artifact_root,
            replace_existing=False,
        )
        if not rebuilt:
            raise RuntimeError(f"No rebuilt Moments for {recording.id}")
        rebuilt_by_recording[recording.id] = rebuilt
        print(f"[{number}/10] {recording.id}: {len(rebuilt)} rebuilt", flush=True)

    mapping = _mapping(old_moments, rebuilt_by_recording)
    new_ids = {moment.id for moments in rebuilt_by_recording.values() for moment in moments}
    migration = _migrate_and_prune(staging, mapping, new_ids)
    if migration["foreign_key_errors"] or migration["duplicate_stable_keys"]:
        raise RuntimeError(f"Rebuild validation failed: {migration}")
    final_library = LibraryService(staging)
    after_moments = final_library.repository.list_moments()
    after = _distribution(after_moments)
    if len(after_moments) != migration["final_moment_count"]:
        raise RuntimeError("FINAL Moment count and repository count differ")

    args.mapping.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    receipt = {
        "source_database": str(source),
        "output_database": str(output),
        "source_preserved": True,
        "asr_rerun": False,
        "raw_media_processed": False,
        "old_moment_count": len(old_moments),
        "new_moment_count": len(after_moments),
        "before_distribution": before,
        "after_distribution": after,
        "mapping_rows": len(mapping),
        **migration,
    }
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    final_library.repository.engine.dispose()
    library.repository.engine.dispose()
    staging.replace(output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
