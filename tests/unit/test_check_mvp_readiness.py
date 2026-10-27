from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_mvp_readiness.py"
SPEC = importlib.util.spec_from_file_location("check_mvp_readiness", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _fixture(tmp_path: Path):
    db = tmp_path / "library.db"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TABLE library_recordings (id TEXT, duration_ms INTEGER, processing_status TEXT, index_status TEXT)"
        )
        connection.execute("CREATE TABLE library_moments (id TEXT, status TEXT)")
        connection.executemany(
            "INSERT INTO library_recordings VALUES (?, ?, 'READY', 'READY')",
            [(str(index), 7_200_000) for index in range(10)],
        )
        connection.executemany(
            "INSERT INTO library_moments VALUES (?, 'FINAL')",
            [(str(index),) for index in range(20)],
        )
    index_root = tmp_path / "index"
    index_root.mkdir()
    (index_root / "manifest.json").write_text(
        json.dumps({"rows": [{"moment_id": str(index)} for index in range(20)]}), encoding="utf-8"
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"overall": "PASS", "known_issues": []}), encoding="utf-8")
    return db, index_root, receipt


def test_ready_library_without_human_scores_remains_pending(tmp_path: Path):
    db, index_root, receipt = _fixture(tmp_path)

    result = checker.check_readiness(db, index_root, verification_receipt=receipt)

    assert result["MVP_CODE_READY"] is True
    assert result["REAL_LIBRARY_READY"] is True
    assert result["PRODUCT_VALIDATION_PENDING"] is True
    assert result["MVP_READY_FOR_REAL_USAGE"] is False


def test_all_human_gates_are_required_for_real_usage(tmp_path: Path):
    db, index_root, receipt = _fixture(tmp_path)
    human = tmp_path / "human.json"
    human.write_text(
        json.dumps(
            {
                "retrieval": [{"score": "PASS"} for _ in range(10)],
                "moments": [{"score": "GOOD"} for _ in range(20)],
                "clips": [{"score": "NO_EDIT"} for _ in range(10)],
                "gui": {"pass": True},
            }
        ),
        encoding="utf-8",
    )

    result = checker.check_readiness(
        db, index_root, verification_receipt=receipt, human_results=human
    )

    assert result["PRODUCT_VALIDATION_PENDING"] is False
    assert result["MVP_READY_FOR_REAL_USAGE"] is True
