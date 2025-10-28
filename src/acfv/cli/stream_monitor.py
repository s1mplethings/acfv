"""CLI entry for the background StreamGet monitor."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Sequence

from acfv.runtime.stream_monitor import StreamMonitorService, load_stream_monitor_config
from acfv.runtime.storage import logs_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acfv stream-monitor",
        description="Run the StreamGet-based background recorder.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Optional path to a YAML config (defaults to var/settings/stream_monitor.yaml).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll each enabled target once and exit (useful for smoke tests).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (DEBUG, INFO, WARNING, ...).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional log file path (defaults to var/logs/stream_monitor.log).",
    )
    return parser


def configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    configure_logging(args.log_level)

    config, cfg_path, created = load_stream_monitor_config(args.config)
    if created:
        logging.getLogger("acfv.cli").warning(
            "Created %s. Edit it to add your streams, then re-run the command.", cfg_path
        )
        return 1

    if not config.targets:
        logging.getLogger("acfv.cli").warning(
            "No targets defined in %s. Add entries under the 'targets' list.", cfg_path
        )
        return 1

    log_path = args.log_file or logs_path("stream_monitor.log")
    service = StreamMonitorService(config, log_path=log_path)
    try:
        asyncio.run(service.run(run_once=args.once))
    except KeyboardInterrupt:
        logging.getLogger("acfv.cli").info("Interrupted, shutting down…")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
