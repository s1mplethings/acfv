Param(
  [switch]$SkipContractChecks
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"
if ($env:PYTHONPATH) {
  $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
  $env:PYTHONPATH = $srcPath
}

Write-Host "[verify] OS: Windows"
Write-Host "[verify] Running: compile + smoke + pytest + contract checks"
Write-Host "[verify] PYTHONPATH: $env:PYTHONPATH"
Write-Host ""

python -c "print('[verify] python ok')" | Out-Host
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Error "[verify] python check failed with exit code $exitCode"
  exit $exitCode
}

# Smoke: CLI help
Write-Host "[verify] smoke: CLI help"
python -m acfv.cli --help | Out-Host
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Error "[verify] cli help failed with exit code $exitCode"
  exit $exitCode
}
python -m acfv.cli gui --help | Out-Host
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Error "[verify] gui help failed with exit code $exitCode"
  exit $exitCode
}
python -m acfv.cli pipe clip --help | Out-Host
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Error "[verify] pipeline help failed with exit code $exitCode"
  exit $exitCode
}

python -m compileall -q src | Out-Host
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Error "[verify] compileall failed with exit code $exitCode"
  exit $exitCode
}

try {
  Write-Host "[verify] unit/integration/e2e/golden: pytest"
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
  python -m pytest -q | Out-Host
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    Write-Error "[verify] pytest failed with exit code $exitCode"
    exit $exitCode
  }
} catch {
  if ($_.Exception.Message -like "*No module named pytest*" -or $_.Exception.Message -like "*pytest: command not found*") {
    Write-Warning "[verify] pytest not found, skipping tests"
  } else {
    throw
  }
}

if (-not $SkipContractChecks) {
  python scripts/contract_checks.py | Out-Host
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    Write-Error "[verify] contract_checks failed with exit code $exitCode"
    exit $exitCode
  }
}

Write-Host ""
Write-Host "[verify] PASS"
