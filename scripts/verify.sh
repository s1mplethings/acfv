#!/usr/bin/env bash
set -euo pipefail

echo "[verify] OS: $(uname -s)"
echo "[verify] Running: compile + pytest + contract checks"
echo

if ! command -v python >/dev/null 2>&1; then
  echo "[verify] ERROR: python not found" >&2
  exit 2
fi

python -c "print('[verify] python ok')"

# Byte-compile to catch syntax errors quickly
python -m compileall -q src

if command -v pytest >/dev/null 2>&1; then
  python -m pytest -q
else
  echo "[verify] WARN: pytest not found, skipping tests"
fi

python scripts/contract_checks.py

echo
echo "[verify] PASS"
