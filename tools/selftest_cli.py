from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from selftest.adapters.run import run_selftest  # noqa: E402
from selftest.adapters.report import append_problem_registry  # noqa: E402
from selftest.adapters.registry import list_adapters  # noqa: E402
from selftest.adapters import detect  # noqa: F401,E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run selftest for a single input file.")
    parser.add_argument("input", nargs="?", help="Input file to test")
    parser.add_argument("--goldens", default=None, help="Override goldens root")
    parser.add_argument(
        "--problem-registry",
        default=None,
        help="Override problem registry jsonl path",
    )
    parser.add_argument("--list-adapters", action="store_true", help="List adapters")

    args = parser.parse_args(argv[1:])

    if args.list_adapters:
        for name in list_adapters():
            print(name)
        return 0

    if not args.input:
        print("Usage: python tools/selftest_cli.py <input_file>")
        return 2

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}")
        return 2

    goldens = Path(args.goldens) if args.goldens else _REPO_ROOT / "selftest" / "goldens"
    registry = (
        Path(args.problem_registry)
        if args.problem_registry
        else _REPO_ROOT / "var" / "problem_registry.jsonl"
    )

    report = run_selftest(input_path, goldens)
    print(json.dumps(report, ensure_ascii=True, indent=2))

    append_problem_registry(report, registry)

    return 0 if (report.get("sut_ok") and report.get("oracle_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
