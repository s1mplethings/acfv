"""Launch the standalone RAG GUI without starting the full app."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    sys.path.insert(0, str(src_path))

    from acfv.app.rag_gui import launch_rag_gui

    return launch_rag_gui()


if __name__ == "__main__":
    raise SystemExit(main())
