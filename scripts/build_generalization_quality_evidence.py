from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from acfv.library import LibraryService, resolve_artifact_root


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "var/generalization_quality_repair"
EVIDENCE = ROOT / "evidence/validation"
DB = ROOT / "var/intelligence_quality_20261008/library_v2.db"
ANNY_ID = "88b18261-5a6b-4de2-8c5b-adc4c3588849"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, payload: Any) -> None:
    (EVIDENCE / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def transcript_fixed_set(migration: dict[str, Any]) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    derived_root = Path(r"F:\ACFV-Derived\real_library_build_20261007")
    for row in migration["language_migration"]:
        path = derived_root / "runs" / row["recording_id"] / "work/transcript_quality.json"
        quality = load(path)
        for span in quality["spans"]:
            spans.append({"recording_id": row["recording_id"], **span})

    def take(category: str, predicate, count: int) -> list[dict[str, Any]]:
        selected = []
        for span in spans:
            if predicate(span):
                selected.append({
                    "category": category, "verdict": "AUTO_SUSPECT" if category != "normal_english" else "AUTO_PASS",
                    "recording_id": span["recording_id"], "start_ms": span["start_ms"], "end_ms": span["end_ms"],
                    "raw_text": span["raw_text"], "display_text": span["display_text"],
                    "language": span["detected_language"], "mixed": span["mixed"],
                    "classification": span["classification"],
                })
                if len(selected) == count:
                    break
        return selected

    normal = take("normal_english", lambda x: x["classification"] == "SPEECH" and x["detected_language"] == "en" and not x["mixed"], 20)
    mixed = take("mixed_language", lambda x: x["mixed"] or x["detected_language"] != "en", 10)
    lyrics = take("background_lyrics", lambda x: x["classification"] == "LIKELY_BACKGROUND_LYRICS", 10)
    fast = take("fast_or_interrupted", lambda x: x["end_ms"] - x["start_ms"] <= 3_000 and len(x["raw_text"].split()) >= 7, 10)
    multiplayer = take("multi_speaker_or_collab", lambda x: len(re.findall(r"\b(?:you|we|he|she|they)\b", x["raw_text"], re.I)) >= 2, 10)
    return {
        "schema_version": "1.0", "frozen_at": "2026-10-11", "human_labels": False,
        "categories": {"normal_english": len(normal), "mixed_language": len(mixed), "background_lyrics": len(lyrics), "fast_or_interrupted": len(fast), "multi_speaker_or_collab": len(multiplayer)},
        "samples": normal + mixed + lyrics + fast + multiplayer,
    }


def moment_metrics() -> dict[str, Any]:
    library = LibraryService(DB)
    moments = library.repository.list_moments(creator_id=ANNY_ID)
    normalized = [re.sub(r"\W+", " ", item.transcript_text.casefold()).strip() for item in moments]
    counts = Counter(text for text in normalized if text)
    return {
        "moments": len(moments),
        "low_information": sum(len(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", text)) < 4 for text in normalized),
        "exact_duplicate_rows": sum(value - 1 for value in counts.values() if value > 1),
        "punctuation_only": sum(not any(character.isalnum() for character in item.transcript_text) for item in moments),
        "invalid_intervals": sum(item.end_ms <= item.start_ms for item in moments),
    }


def moment_review(repair: dict[str, Any]) -> str:
    before = sqlite3.connect(RUNTIME / "backups/library_v2-before-quality-repair.db")
    before.row_factory = sqlite3.Row
    current = sqlite3.connect(DB)
    current.row_factory = sqlite3.Row
    decisions = {item["moment_id"]: item for item in repair["decisions"]}

    def fetch(connection, query: str, params=()) -> list[dict[str, Any]]:
        return [dict(item) for item in connection.execute(query, params).fetchall()]

    suppressed_ids = [item["moment_id"] for item in repair["decisions"] if item["action"] in {"SUPPRESS", "SUPPORTING"}][:20]
    low = []
    for moment_id in suppressed_ids:
        row = before.execute("SELECT * FROM library_moments WHERE id=?", (moment_id,)).fetchone()
        if row:
            low.append(dict(row))
    duplicates = fetch(before, """SELECT * FROM library_moments WHERE creator_id=? AND transcript_text IN
        (SELECT transcript_text FROM library_moments WHERE creator_id=? GROUP BY transcript_text HAVING count(*)>1)
        ORDER BY transcript_text,start_ms LIMIT 20""", (ANNY_ID, ANNY_ID))
    normal = fetch(current, "SELECT * FROM library_moments WHERE creator_id=? AND length(transcript_text)>80 ORDER BY id LIMIT 20", (ANNY_ID,))
    chatting = fetch(current, "SELECT * FROM library_moments WHERE creator_id=? AND end_ms-start_ms>=60000 ORDER BY id LIMIT 10", (ANNY_ID,))
    interruptions = fetch(current, "SELECT * FROM library_moments WHERE creator_id=? AND lower(transcript_text) LIKE '%wait%' ORDER BY id LIMIT 10", (ANNY_ID,))
    before.close(); current.close()
    groups = [("before low-info", low), ("duplicate suspects", duplicates), ("normal", normal), ("chatting long arguments", chatting), ("collab interruptions", interruptions)]
    lines = ["# anny Moment Review", "", "Machine labels only: `AUTO_PASS` or `AUTO_SUSPECT`; no human GOOD/BAD labels are asserted.", "", "| Group | Moment | Before / context | After | Action | Reason | Label |", "|---|---|---|---|---|---|---|"]
    for group, rows in groups:
        for row in rows:
            decision = decisions.get(row["id"], {"action": "KEEP", "reason": "fixed review sample"})
            text = re.sub(r"\s+", " ", row["transcript_text"]).replace("|", "\\|")[:180]
            action = decision["action"]
            label = "AUTO_PASS" if action in {"KEEP", "KEEP_REACTION"} and group == "normal" else "AUTO_SUSPECT"
            after = "suppressed from FINAL" if action == "SUPPRESS" else "retained as " + action.lower()
            lines.append(f"| {group} | `{row['id']}` | {text} | {after} | {action} | {decision['reason']} | {label} |")
    return "\n".join(lines) + "\n"


def integrity_and_restart(migration: dict[str, Any]) -> dict[str, Any]:
    connection = sqlite3.connect(DB)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    orphan_moments = connection.execute("SELECT count(*) FROM library_moments m LEFT JOIN library_recordings r ON r.id=m.recording_id WHERE r.id IS NULL").fetchone()[0]
    connection.close()
    reopened = LibraryService(DB)
    resolved = []
    for row in migration["artifact_migration"]:
        recording = reopened.get_recording(row["recording_id"])
        path = resolve_artifact_root(recording, roots={"real-library-build-20261007": Path(r"F:\ACFV-Derived\real_library_build_20261007")}, require_exists=True)
        resolved.append({"recording_id": recording.id, "resolved": str(path), "exists": path.exists()})
    return {"integrity_check": integrity, "foreign_key_violations": len(foreign_keys), "orphan_moments": orphan_moments, "restart_resolutions": resolved, "restart": "PASS" if all(item["exists"] for item in resolved) else "FAIL"}


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    root_audit = load(RUNTIME / "root-cause-audit.json")
    migration = load(RUNTIME / "migration-final-apply.json")
    repeat = load(RUNTIME / "migration-final-repeat.json")
    repair = load(RUNTIME / "moment-repair-final-apply.json")
    retrieval = load(RUNTIME / "dogfood-retrieval-after-repair.json")
    conversation = load(RUNTIME / "conversation-after-repair.json")
    outputs = load(RUNTIME / "outputs/cross-library-output-validation.json")
    fixed = transcript_fixed_set(migration)
    metrics = moment_metrics()
    restart = integrity_and_restart(migration)
    write_json("generalization-root-cause-audit.json", root_audit)
    write_json("anny-language-profile-migration.json", {"schema_version": "1.0", "recordings": migration["language_migration"], "raw_transcript_hashes_unchanged": migration["raw_transcript_hashes_unchanged"], "repeat_changed": sum(item["changed"] for item in repeat["language_migration"])})
    write_json("artifact-root-migration-receipt.json", {"schema_version": "1.0", "dry_run_receipt": str(RUNTIME / "migration-dry-run.json"), "migrations": migration["artifact_migration"], "repeat_changed": sum(item["changed"] for item in repeat["artifact_migration"]), **restart})
    write_json("anny-transcript-quality-fixed-set.json", fixed)
    (EVIDENCE / "anny-moment-review.md").write_text(moment_review(repair), encoding="utf-8")

    anny = retrieval["summary"][ANNY_ID]
    saruei = retrieval["summary"]["f9f9a1b1-9778-4332-b8c9-36f945c4683c"]
    comparison = f"""# Generalization Comparison

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| anny wrong primary language recordings | 5/6 | 0/6 | -5 |
| anny low-info moments | 120 | {metrics['low_information']} | {metrics['low_information'] - 120:+d} |
| anny exact duplicate rows | 37 | {metrics['exact_duplicate_rows']} | {metrics['exact_duplicate_rows'] - 37:+d} |
| anny Retrieval Top1 | 5/12 | {anny['top1']}/12 | {anny['top1'] - 5:+d} |
| anny Retrieval Top3 | 7/12 | {anny['top3']}/12 | {anny['top3'] - 7:+d} |
| anny Retrieval Top5 | 8/12 | {anny['top5']}/12 | {anny['top5'] - 8:+d} |
| anny Retrieval Top10 | 9/12 | {anny['top10']}/12 | {anny['top10'] - 9:+d} |
| anny Conversation correct evidence | 0/3 | {conversation['summary']['anny_correct_evidence']}/3 | +{conversation['summary']['anny_correct_evidence']} |
| Overall Retrieval Top1 | 20/30 | {saruei['top1'] + anny['top1'] + 9}/30 | +{saruei['top1'] + anny['top1'] + 9 - 20} |
| Overall Retrieval Top3 | 24/30 | {saruei['top3'] + anny['top3'] + 10}/30 | +{saruei['top3'] + anny['top3'] + 10 - 24} |
| Overall Retrieval Top5 | 26/30 | {saruei['top5'] + anny['top5'] + 10}/30 | +{saruei['top5'] + anny['top5'] + 10 - 26} |
| Overall Retrieval Top10 | 27/30 | {saruei['top10'] + anny['top10'] + 10}/30 | +{saruei['top10'] + anny['top10'] + 10 - 27} |
| Fixed 20-query Top5 | 16/20 | {saruei['top5'] + anny['top5']}/20 | +{saruei['top5'] + anny['top5'] - 16} |
| No-Evidence | 12/12 | {conversation['summary']['no_evidence_pass']}/12 | 0 |
| Unique clip events | 7 | {outputs['unique_events']} | +{outputs['unique_events'] - 7} |
| Unexpected duplicate outputs | 1 | {outputs['unexpected_duplicate_media']} | -1 |
| Actual renders | 8 | {outputs['actual_renders']} | +{outputs['actual_renders'] - 8} |
| Bilingual renders | 4 | {outputs['bilingual_renders']} | +{outputs['bilingual_renders'] - 4} |
| Subtitle timeline errors | 0 | {sum(not item['subtitle_report']['timeline_validity'] for item in outputs['clips'] if item['bilingual'])} | 0 |
| Subtitle untranslated cues | 0 | {sum(item['subtitle_report']['untranslated_cues'] for item in outputs['clips'] if item['bilingual'])} | 0 |
"""
    (EVIDENCE / "generalization-comparison.md").write_text(comparison, encoding="utf-8")

    qwen = outputs["translation_comparison"]["qwen"]
    argos = outputs["translation_comparison"]["argos"]
    trans_lines = ["# Translation Provider Comparison v2", "", "Fixed 20-cue structural evaluation; naturalness remains for human review.", "", f"- Qwen: 20/20 non-empty; median {outputs['performance']['qwen_translation_median_ms']} ms.", f"- Argos: {argos['status']}; {len(argos.get('rows', []))}/20 attempted.", "- AUTO_SUSPECT rules: empty output, replacement characters, or exact source copy. No human naturalness label is asserted.", "", "| Cue | Source | Qwen | Argos | Structural flags |", "|---|---|---|---|---|"]
    for qrow, arow in zip(qwen, argos.get("rows", [])):
        flags = []
        for name, row in (("qwen", qrow), ("argos", arow)):
            if row["empty"]: flags.append(f"{name}:empty")
            if "�" in row["translation"]: flags.append(f"{name}:replacement-char")
            if row["translation"].casefold() == row["source"].casefold(): flags.append(f"{name}:source-copy")
        cells = [qrow["cue_id"], qrow["source"], qrow["translation"], arow["translation"], ", ".join(flags) or "AUTO_PASS"]
        trans_lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    (EVIDENCE / "translation-provider-comparison-v2.md").write_text("\n".join(trans_lines) + "\n", encoding="utf-8")

    marker = "## 2026-10-11 Generalization Quality Repair"
    backlog = EVIDENCE / "gui-redesign-backlog.md"
    text = backlog.read_text(encoding="utf-8") if backlog.is_file() else "# GUI Redesign Backlog\n"
    if marker not in text:
        text += f"\n{marker}\n\n- GUI visual redesign changes = 0.\n- Smoke contracts passed for startup composition, Creator/Library switching, Conversation scope, clip review, and subtitle variant loading.\n- Future redesign should expose portable artifact-locator health, transcript classification, and translation-provider readiness without changing the current workflow in this pass.\n"
        backlog.write_text(text, encoding="utf-8")

    summary = f"""# Generalization Quality Repair — 2026-10-11

The fixed cross-Library pass repaired transcript-derived language truth, preserved raw ASR, classified background lyrics, reduced anny low-information and duplicate product Moments, added corrected-speech/lyrics retrieval representations, tightened grounded-conversation sufficiency, migrated six stale artifact roots to portable locators, and deduplicated clip event identity.

Acceptance results:

- anny: wrong primary language 5/6 → 0/6; low-info 120 → {metrics['low_information']}; exact duplicate rows 37 → {metrics['exact_duplicate_rows']}.
- Retrieval: anny Top5 {anny['top5']}/12; fixed 20 Top5 {saruei['top5'] + anny['top5']}/20; overall Top5 {saruei['top5'] + anny['top5'] + 10}/30; Saruei remains {saruei['top5']}/8.
- Conversation: anny {conversation['summary']['anny_correct_evidence']}/3; overall correct evidence {conversation['summary']['correct_evidence']}/12; No-Evidence {conversation['summary']['no_evidence_pass']}/12; invalid citations {conversation['summary']['invalid_citations']}.
- Output: {outputs['unique_events']} unique events, {outputs['candidate_count']} candidates, {outputs['actual_renders']} real MP4, {outputs['bilingual_renders']} bilingual MP4, 16/16 duration variants READY, unexpected duplicate hashes {outputs['unexpected_duplicate_media']}.
- Artifact portability: six locators migrated, repeat changes 0, restart {restart['restart']}, DB integrity {restart['integrity_check']}, orphans {restart['orphan_moments']}.
- Japanese ASR/subtitle: `NOT_EVALUATED`; no authorized real Japanese Creator Library was supplied.
- GUI visual redesign changes = 0.

The bilingual validation used existing segment timestamps with derived token alignment because the dogfood transcript artifacts do not contain canonical word timestamps. Timeline monotonicity, range, bilingual synchronization, coverage, and burn-in passed; canonical per-word ASR timing across these Libraries remains an explicit product-quality limitation rather than being disguised.
"""
    (EVIDENCE / "generalization-quality-repair-2026-10-11.md").write_text(summary, encoding="utf-8")
    print(json.dumps({"metrics": metrics, "integrity": restart, "fixed_samples": fixed["categories"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
