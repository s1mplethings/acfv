from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


TARGETS = (
    "tests/unit/test_five_creator_adaptive_v2_script.py",
    "tests/unit/test_multi_creator_adaptive.py",
    "tests/unit/test_creator_adaptive_understanding.py",
    "tests/integration/test_creator_adaptive_architecture_guards.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=7200)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = tuple(path.resolve() for path in args.evidence)
    missing = [str(path) for path in evidence if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing soak evidence: {missing}")
    baseline_hashes = {str(path): sha256(path) for path in evidence}
    baseline_status = subprocess.run(
        ["git", "status", "--porcelain=v1"], check=True, capture_output=True, text=True,
    ).stdout
    started = time.monotonic()
    cycles: list[dict[str, object]] = []
    cycle = 0
    while True:
        cycle += 1
        command = ["python", "-m", "pytest", "-q", *TARGETS]
        completed = subprocess.run(command, capture_output=True, text=True)
        current_hashes = {str(path): sha256(path) for path in evidence}
        current_status = subprocess.run(
            ["git", "status", "--porcelain=v1"], check=True, capture_output=True, text=True,
        ).stdout
        row = {
            "cycle": cycle,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "elapsed_seconds": time.monotonic() - started,
            "pytest_exit_code": completed.returncode,
            "pytest_tail": "\n".join(completed.stdout.splitlines()[-8:]),
            "stderr_tail": "\n".join(completed.stderr.splitlines()[-8:]),
            "evidence_stable": current_hashes == baseline_hashes,
            "worktree_stable": current_status == baseline_status,
        }
        cycles.append(row)
        _write(output / "progress.json", {
            "status": "RUNNING", "cycle": cycle, "elapsed_seconds": row["elapsed_seconds"],
            "last": row, "ground_truth_opened": False,
        })
        if completed.returncode or not row["evidence_stable"] or not row["worktree_stable"]:
            _write(output / "soak-receipt.json", {
                "status": "FAIL", "duration_seconds": time.monotonic() - started,
                "cycles": cycles, "baseline_hashes": baseline_hashes,
                "ground_truth_opened": False,
            })
            return 1
        elapsed = time.monotonic() - started
        if elapsed >= args.duration_seconds:
            break
        time.sleep(min(args.interval_seconds, max(0.0, args.duration_seconds - elapsed)))
    _write(output / "progress.json", {
        "status": "COMPLETE", "result": "PASS", "cycles": cycle,
        "elapsed_seconds": time.monotonic() - started, "ground_truth_opened": False,
    })
    _write(output / "soak-receipt.json", {
        "status": "PASS", "duration_seconds": time.monotonic() - started,
        "cycles": cycles, "baseline_hashes": baseline_hashes,
        "worktree_stable": True, "ground_truth_opened": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
