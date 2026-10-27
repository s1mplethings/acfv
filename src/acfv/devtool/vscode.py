from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _which(exe: str) -> Optional[str]:
    if sys.platform.startswith("win"):
        # Prefer PATHEXT-resolved executables to avoid non-exe "code" files.
        found = shutil.which(exe)
        if found:
            return found
        for ext in (".cmd", ".bat", ".exe"):
            for p in os.environ.get("PATH", "").split(os.pathsep):
                cand = Path(p) / f"{exe}{ext}"
                if cand.exists():
                    return str(cand)
        return None

    return shutil.which(exe)


def open_in_vscode(
    path: str,
    line: Optional[int] = None,
    col: Optional[int] = None,
    reuse: bool = True,
    workspace_dir: Optional[str] = None,
    new_window: bool = False,
) -> None:
    code_cmd = _which("code")
    if not code_cmd:
        raise RuntimeError(
            "VSCode 'code' command not found in PATH. "
            "Install it via VSCode: Shell Command: Install 'code' command in PATH."
        )

    args = [code_cmd]
    if new_window:
        args.append("-n")
    elif reuse:
        args.append("-r")

    p = Path(path).resolve()
    if workspace_dir:
        args.append(str(Path(workspace_dir).resolve()))
    if line is not None:
        if col is None:
            col = 1
        args += ["--goto", f"{p}:{line}:{col}"]
    else:
        args.append(str(p))

    subprocess.run(args, check=False)


def find_line_of_token(file_path: str, token: str) -> Optional[int]:
    try:
        lines = Path(file_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    for i, line in enumerate(lines, start=1):
        if token in line:
            return i
    return None


__all__ = ["open_in_vscode", "find_line_of_token"]
