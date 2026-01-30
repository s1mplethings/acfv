#!/usr/bin/env python3
"""Cross-platform verify runner.

Preferred:
- Windows: powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
- Linux/macOS: bash scripts/verify.sh

This wrapper chooses based on platform, but you can call verify.ps1/verify.sh directly.
"""
from __future__ import annotations

import os, sys, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(cmd: list[str]) -> int:
    p = subprocess.run(cmd, cwd=str(ROOT))
    return p.returncode

def main() -> int:
    if os.name == "nt":
        ps1 = ROOT / "scripts" / "verify.ps1"
        if ps1.exists():
            return run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1)])
        print("verify.ps1 not found", file=sys.stderr)
        return 1
    sh = ROOT / "scripts" / "verify.sh"
    if sh.exists():
        return run(["bash", str(sh)])
    print("verify.sh not found", file=sys.stderr)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
