#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src_path="$repo_root/src"
export PYTHONPATH="${src_path}${PYTHONPATH:+:${PYTHONPATH}}"

echo "[verify] OS: $(uname -s)"
echo "[verify] Running: compile + smoke + pytest + contract checks"
echo "[verify] PYTHONPATH: $PYTHONPATH"
echo

if ! command -v python >/dev/null 2>&1; then
  echo "[verify] ERROR: python not found" >&2
  exit 2
fi

python -c "print('[verify] python ok')"

# Smoke: CLI help
echo "[verify] smoke: CLI help"
python -m acfv.cli --help
exit_code=$?
if [ $exit_code -ne 0 ]; then
  echo "[verify] cli help failed with exit code $exit_code" >&2
  exit $exit_code
fi
python -m acfv.cli gui --help
exit_code=$?
if [ $exit_code -ne 0 ]; then
  echo "[verify] gui help failed with exit code $exit_code" >&2
  exit $exit_code
fi
python -m acfv.cli pipe clip --help
exit_code=$?
if [ $exit_code -ne 0 ]; then
  echo "[verify] pipeline help failed with exit code $exit_code" >&2
  exit $exit_code
fi

# Byte-compile to catch syntax errors quickly
python -m compileall -q src
exit_code=$?
if [ $exit_code -ne 0 ]; then
  echo "[verify] compileall failed with exit code $exit_code" >&2
  exit $exit_code
fi

if command -v pytest >/dev/null 2>&1; then
  echo "[verify] unit/integration/e2e/golden: pytest"
  export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  python -m pytest -q
  exit_code=$?
  if [ $exit_code -ne 0 ]; then
    echo "[verify] pytest failed with exit code $exit_code" >&2
    exit $exit_code
  fi
else
  echo "[verify] WARN: pytest not found, skipping tests"
fi

python scripts/contract_checks.py
exit_code=$?
if [ $exit_code -ne 0 ]; then
  echo "[verify] contract_checks failed with exit code $exit_code" >&2
  exit $exit_code
fi

echo
echo "[verify] PASS"
