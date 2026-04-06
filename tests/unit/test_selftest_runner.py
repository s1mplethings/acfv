import json

from selftest.adapters.oracles.invariants import invariants_check
from selftest.adapters.run import run_selftest
import selftest.adapters.detect  # noqa: F401


def test_snapshot_creates_golden_and_passes(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"a": 1}), encoding="utf-8")

    goldens = tmp_path / "goldens"
    report = run_selftest(input_path, goldens)

    assert report["sut_ok"] is True
    assert report["oracle_ok"] is True

    meta_path = goldens / "generic_json_pipeline" / "input.json"
    assert meta_path.exists()


def test_invariants_basic(tmp_path):
    out_path = tmp_path / "out.txt"
    out_path.write_text("ok", encoding="utf-8")

    ok, msg = invariants_check(
        {"out": out_path},
        {"required_outputs": ["out"], "min_size_bytes": 1},
    )
    assert ok is True
    assert "INVARIANTS" in msg
