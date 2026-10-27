from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .base import RunResult
from .registry import register


class GenericJsonAdapter:
    name = "generic_json_pipeline"

    def match(self, input_path: Path) -> bool:
        return input_path.suffix.lower() == ".json"

    def run_sut(self, input_path: Path, workdir: Path) -> RunResult:
        out_path = workdir / "out.json"
        cmd = [
            sys.executable,
            "-c",
            (
                "import json,sys;"
                "data=json.load(open(sys.argv[1], 'r', encoding='utf-8'));"
                "json.dump(data, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=True, indent=2)"
            ),
            str(input_path),
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        outputs = {"out_json": out_path} if out_path.exists() else {}
        return RunResult(
            ok=(proc.returncode == 0),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            outputs=outputs,
        )

    def pick_oracle(self, input_path: Path) -> str:
        return "snapshot"

    def oracle_config(self, input_path: Path) -> dict[str, object]:
        return {}


register(GenericJsonAdapter())
