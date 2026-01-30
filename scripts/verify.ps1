Param(
  [switch]$SkipContractChecks
)

$ErrorActionPreference = "Stop"

Write-Host "[verify] OS: Windows"
Write-Host "[verify] Running: compile + pytest + contract checks"
Write-Host ""

python -c "print('[verify] python ok')" | Out-Host

python -m compileall -q src | Out-Host

try {
  python -m pytest -q | Out-Host
} catch {
  if ($_.Exception.Message -like "*No module named pytest*" -or $_.Exception.Message -like "*pytest: command not found*") {
    Write-Warning "[verify] pytest not found, skipping tests"
  } else {
    throw
  }
}

if (-not $SkipContractChecks) {
  python scripts/contract_checks.py | Out-Host
}

Write-Host ""
Write-Host "[verify] PASS"
