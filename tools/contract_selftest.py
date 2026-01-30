"""
Lightweight self-tests for contract-based helpers.

Runs quick, dependency-light checks that don't require external binaries or network.
Intended as a sanity check, not a full integration test suite.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from acfv.selection.contract_selection import select_candidates
from acfv.selection.merge_segments import merge_segments
from acfv.processing.subtitle_contract import generate_subtitle


def test_selection(tmpdir: Path) -> None:
    sample = {
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "hello", "score": 0.5},
            {"start": 6.0, "end": 9.0, "text": "world", "score": 0.9},
            {"start": 9.1, "end": 12.0, "text": "again", "score": 0.8},
        ],
        "strategy": "topk",
        "topk": 2,
        "min_duration": 0.1,
    }
    result = select_candidates(sample)
    assert result["schema_version"].startswith("1."), "schema_version missing"
    candidates = result["candidates"]
    assert len(candidates) == 2, "topk selection failed"
    assert candidates[0]["score"] >= candidates[1]["score"], "sorting not deterministic"
    tmpdir.joinpath("selection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def test_merge(tmpdir: Path) -> None:
    sample = {
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "a"},
            {"start": 3.5, "end": 5.0, "text": "b"},
            {"start": 20.0, "end": 22.0, "text": "c"},
        ],
        "merge_gap_sec": 1.0,
        "max_merged_duration": 10.0,
    }
    result = merge_segments(sample)
    merged = result["merged_segments"]
    assert len(merged) == 2, "merge count unexpected"
    assert merged[0]["start"] == 0.0 and merged[0]["end"] == 5.0, "merge gap rule failed"
    tmpdir.joinpath("merge.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def test_subtitle(tmpdir: Path) -> None:
    payload = {
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "Hello"},
            {"start": 2.0, "end": 3.0, "text": "World"},
        ],
        "format": "srt",
        "out_dir": str(tmpdir),
        "source_name": "sample",
        "time_offset_sec": 0.0,
    }
    result = generate_subtitle(payload)
    path = Path(result["subtitle_path"])
    assert path.exists(), "subtitle file not written"
    content = path.read_text(encoding="utf-8")
    assert "Hello" in content and "World" in content, "subtitle content missing"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lightweight contract self-tests.")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        test_selection(tmpdir)
        test_merge(tmpdir)
        test_subtitle(tmpdir)
    print("contract self-tests passed")


if __name__ == "__main__":
    main()
