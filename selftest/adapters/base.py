from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    outputs: dict[str, Path]


class Adapter(Protocol):
    name: str

    def match(self, input_path: Path) -> bool:
        ...

    def run_sut(self, input_path: Path, workdir: Path) -> RunResult:
        ...

    def pick_oracle(self, input_path: Path) -> str:
        """Return one of: "diff" | "invariants" | "snapshot"."""
        ...

    def oracle_config(self, input_path: Path) -> dict[str, Any]:
        ...
