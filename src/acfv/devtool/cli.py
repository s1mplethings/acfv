from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for parent in [current] + list(current.parents):
        pyproject = parent / "pyproject.toml"
        src_dir = parent / "src" / "acfv"
        if pyproject.exists() and src_dir.is_dir():
            return parent
    return current


def _is_repo_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "src" / "acfv").is_dir()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="code-gui",
        description="ACFV devtool GUI (scan specs and open in VSCode)",
    )
    parser.add_argument(
        "--root",
        type=str,
        nargs="?",
        default=None,
        help="project root directory (default: auto-detect)",
    )
    args = parser.parse_args()

    try:
        from .gui import run_gui
    except Exception as exc:
        msg = (
            "GUI dependencies are missing (PyQt5). "
            "Install with: pip install -e \".[gui]\". "
            f"Details: {exc}"
        )
        print(msg, file=sys.stderr)
        raise SystemExit(1)

    root_arg = (args.root or "").strip()
    if root_arg:
        root_dir = Path(root_arg).expanduser().resolve()
    else:
        root_dir = _find_repo_root(Path(__file__).resolve().parent)
        if not _is_repo_root(root_dir):
            root_dir = _find_repo_root(Path.cwd())

    run_gui(str(root_dir))


__all__ = ["main"]
