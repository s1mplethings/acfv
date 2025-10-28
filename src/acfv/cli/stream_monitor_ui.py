"""Launch the PyQt Stream Monitor editor."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from acfv.ui.stream_monitor_editor import launch_editor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acfv stream-monitor-ui",
        description="Open the GUI editor for the StreamGet monitor config.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Optional YAML path (defaults to var/settings/stream_monitor.yaml).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    launch_editor(str(args.config) if args.config else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
