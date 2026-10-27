from __future__ import annotations

import tempfile
import traceback
from pathlib import Path
from typing import Any

from .registry import resolve
from .oracles.diff import diff_check
from .oracles.invariants import invariants_check
from .oracles.snapshot import snapshot_check


def _truncate(text: str | None, limit: int = 4000) -> str:
    if not text:
        return ""
    return text[-limit:]


def _pick_output(outputs: dict[str, Path], config: dict[str, Any]) -> Path | None:
    preferred = config.get("primary_output")
    if preferred and preferred in outputs:
        return outputs[preferred]
    return next(iter(outputs.values()), None)


def run_selftest(input_path: Path, goldens_root: Path) -> dict[str, Any]:
    input_path = input_path.resolve()
    adapter = resolve(input_path)

    report: dict[str, Any] = {
        "input": str(input_path),
        "adapter": adapter.name,
        "sut_ok": False,
        "stdout": "",
        "stderr": "",
        "outputs": {},
        "oracle": None,
        "oracle_ok": None,
        "oracle_msg": None,
        "error": None,
    }

    with tempfile.TemporaryDirectory(prefix="selftest_") as tmp:
        workdir = Path(tmp)
        try:
            rr = adapter.run_sut(input_path, workdir)
        except Exception:
            report["error"] = _truncate(traceback.format_exc())
            return report

        report["sut_ok"] = rr.ok
        report["stdout"] = _truncate(rr.stdout)
        report["stderr"] = _truncate(rr.stderr)
        report["outputs"] = {k: str(v) for k, v in rr.outputs.items()}

        try:
            oracle = adapter.pick_oracle(input_path)
            report["oracle"] = oracle
            config = adapter.oracle_config(input_path)

            if not rr.ok:
                report["oracle_ok"] = False
                report["oracle_msg"] = "SUT failed, oracle skipped"
                return report

            if oracle == "snapshot":
                out_file = _pick_output(rr.outputs, config)
                if out_file is None:
                    report["oracle_ok"] = False
                    report["oracle_msg"] = "No outputs produced"
                    return report
                case_id = input_path.stem
                ok, msg = snapshot_check(out_file, goldens_root / adapter.name, case_id)
                report["oracle_ok"] = ok
                report["oracle_msg"] = msg
                return report

            if oracle == "diff":
                out_file = _pick_output(rr.outputs, config)
                if out_file is None:
                    report["oracle_ok"] = False
                    report["oracle_msg"] = "No outputs produced"
                    return report
                case_id = input_path.stem
                ok, msg = diff_check(out_file, goldens_root / adapter.name, case_id)
                report["oracle_ok"] = ok
                report["oracle_msg"] = msg
                return report

            if oracle == "invariants":
                ok, msg = invariants_check(rr.outputs, config)
                report["oracle_ok"] = ok
                report["oracle_msg"] = msg
                return report

            report["oracle_ok"] = False
            report["oracle_msg"] = f"Oracle not implemented in runner: {oracle}"
            return report

        except Exception:
            report["oracle_ok"] = False
            report["error"] = _truncate(traceback.format_exc())
            return report
