"""Entry point for the acfv console script.

There are two potentially confusing things in this repository:

1. A legacy dispatcher module now named `legacy_cli.py`.
2. A package directory `acfv/cli/` which defines a Typer application in
    its `__main__.py` and re-exports `app` via `acfv.cli.__init__`.

When invoking the installed console script or `python -m acfv`, we want
to execute the Typer `app` (if present). If for some reason that fails,
we fall back to the legacy dynamic-dispatch `cli.py` logic (which looks
for various candidate modules exposing `main`).
"""

from __future__ import annotations

import sys


def main():  # pragma: no cover - thin wrapper
    # First try: Typer app in package acfv.cli (directory form)
    try:
        from .cli import app  # package's __init__ exporting Typer app
        return app()
    except Exception as first_err:  # noqa: BLE001 - broad to fallback
        # Second try: legacy dynamic dispatcher module (legacy_cli.py)
        try:
            from . import legacy_cli  # the renamed legacy module
            rc = legacy_cli.main()
            if isinstance(rc, int):
                return rc
            return 0
        except Exception as second_err:  # noqa: BLE001
            print("[acfv] CLI 启动失败:", file=sys.stderr)
            print("  1st (Typer app) error:", repr(first_err), file=sys.stderr)
            print("  2nd (legacy cli.main) error:", repr(second_err), file=sys.stderr)
            return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
