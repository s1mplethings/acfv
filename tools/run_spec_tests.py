"""
Run spec/documentation presence tests with plugin autoload disabled.

Why: Pytest may pick up global plugins (e.g., opik) that require heavy deps
or mismatched binaries. Disabling autoload keeps the run lightweight and
focused on our spec presence checks.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    try:
        import pytest  # type: ignore
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"pytest is required to run spec tests: {exc}\n")
        return 1
    args = ["-q", "tests/integration/test_spec_presence.py"]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
