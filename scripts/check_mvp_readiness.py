from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _human_gate(payload: dict[str, Any], key: str, accepted: set[str], minimum: int, total: int) -> dict[str, Any]:
    rows = payload.get(key, [])
    if not isinstance(rows, list):
        rows = []
    scores = [str(row.get("score", "")).strip().upper() for row in rows if isinstance(row, dict)]
    rated = sum(bool(score) for score in scores)
    passed = sum(score in accepted for score in scores)
    return {
        "required": total,
        "rated": rated,
        "passing_scores": passed,
        "threshold": minimum,
        "pass": rated >= total and passed >= minimum,
    }


def check_readiness(
    db_path: Path,
    index_root: Path,
    *,
    verification_receipt: Path | None = None,
    human_results: Path | None = None,
) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        recordings = connection.execute(
            "SELECT id, COALESCE(duration_ms, 0), processing_status, index_status FROM library_recordings"
        ).fetchall()
        final_moments = int(
            connection.execute("SELECT COUNT(*) FROM library_moments WHERE status = 'FINAL'").fetchone()[0]
        )

    manifest = _read_json(index_root / "manifest.json")
    index_rows = manifest.get("rows", [])
    if not isinstance(index_rows, list):
        index_rows = []
    recording_count = len(recordings)
    total_hours = sum(int(row[1]) for row in recordings) / 3_600_000
    processed = sum(str(row[2]) == "READY" for row in recordings)
    indexed = sum(str(row[3]) == "READY" for row in recordings)
    library_ready = (
        recording_count >= 10
        and total_hours >= 20
        and processed == recording_count
        and indexed == recording_count
        and final_moments > 0
        and len(index_rows) == final_moments
    )

    verification = _read_json(verification_receipt)
    issues = verification.get("known_issues", [])
    if not isinstance(issues, list):
        issues = []
    p0 = sum(isinstance(issue, dict) and str(issue.get("severity", "")).upper() == "P0" for issue in issues)
    p1 = sum(isinstance(issue, dict) and str(issue.get("severity", "")).upper() == "P1" for issue in issues)
    automated_pass = str(verification.get("overall", verification.get("status", ""))).upper() == "PASS"
    code_ready = automated_pass and p0 == 0 and p1 == 0

    human = _read_json(human_results)
    retrieval = _human_gate(human, "retrieval", {"PASS"}, 7, 10)
    moments = _human_gate(human, "moments", {"GOOD", "ACCEPTABLE"}, 16, 20)
    clips = _human_gate(human, "clips", {"NO_EDIT", "MINOR_EDIT"}, 6, 10)
    gui = human.get("gui", {}) if isinstance(human.get("gui"), dict) else {}
    gui_pass = bool(gui.get("pass", False))
    human_pass = retrieval["pass"] and moments["pass"] and clips["pass"] and gui_pass

    return {
        "recordings": recording_count,
        "hours": round(total_hours, 6),
        "processed_recordings": processed,
        "indexed_recordings": indexed,
        "final_moments": final_moments,
        "index_rows": len(index_rows),
        "known_p0": p0,
        "known_p1": p1,
        "automated_verification": "PASS" if automated_pass else "MISSING_OR_FAILED",
        "human": {"retrieval": retrieval, "moments": moments, "clips": clips, "gui_pass": gui_pass},
        "MVP_CODE_READY": code_ready,
        "REAL_LIBRARY_READY": library_ready,
        "PRODUCT_VALIDATION_PENDING": not human_pass,
        "MVP_READY_FOR_REAL_USAGE": code_ready and library_ready and human_pass,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ACFV MVP code, real-library, and human quality gates.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--index-root", type=Path, required=True)
    parser.add_argument("--verification-receipt", type=Path)
    parser.add_argument("--human-results", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check_readiness(
        args.db,
        args.index_root,
        verification_receipt=args.verification_receipt,
        human_results=args.human_results,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["MVP_CODE_READY"] and result["REAL_LIBRARY_READY"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
