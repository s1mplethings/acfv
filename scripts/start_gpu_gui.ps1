Param(
  [Alias("PythonPath")]
  [string]$PythonExecutable,
  [switch]$CheckOnly,
  [switch]$ResolveOnly
)

$ErrorActionPreference = "Stop"

function Resolve-PythonExecutable {
  param([string]$Explicit)

  if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
    if (-not (Test-Path -LiteralPath $Explicit -PathType Leaf)) {
      throw "Explicit Python interpreter is not a file: $Explicit"
    }
    return (Resolve-Path -LiteralPath $Explicit).ProviderPath
  }

  if (Test-Path Env:ACFV_PYTHON) {
    if ([string]::IsNullOrWhiteSpace($env:ACFV_PYTHON) -or
        -not (Test-Path -LiteralPath $env:ACFV_PYTHON -PathType Leaf)) {
      throw "ACFV_PYTHON is not a valid Python interpreter: $env:ACFV_PYTHON"
    }
    return (Resolve-Path -LiteralPath $env:ACFV_PYTHON).ProviderPath
  }

  if (-not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)) {
    $condaPython = Join-Path $env:CONDA_PREFIX "python.exe"
    if (Test-Path -LiteralPath $condaPython -PathType Leaf) {
      return (Resolve-Path -LiteralPath $condaPython).ProviderPath
    }
  }

  $pathPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($pathPython) {
    return $pathPython.Source
  }

  throw "Python interpreter not found. Activate the project environment or set ACFV_PYTHON or -PythonExecutable."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"
$PythonPath = Resolve-PythonExecutable -Explicit $PythonExecutable

if ($env:PYTHONPATH) {
  $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
} else {
  $env:PYTHONPATH = $srcPath
}

$env:ACFV_GUI_PREFERRED_PYTHON = $PythonPath
$env:ACFV_TRANSCRIBE_PYTHON = $PythonPath
$env:KMP_DUPLICATE_LIB_OK = "TRUE"

Write-Host "[gpu-gui] repo: $repoRoot"
Write-Host "[gpu-gui] python: $PythonPath"
Write-Host "[gpu-gui] PYTHONPATH: $env:PYTHONPATH"

if ($ResolveOnly) {
  exit 0
}

$probeScript = @'
import importlib.util
import json
import sys

out = {
    "python": sys.executable,
    "PyQt5": importlib.util.find_spec("PyQt5") is not None,
    "whisper": importlib.util.find_spec("whisper") is not None,
    "faster_whisper": importlib.util.find_spec("faster_whisper") is not None,
    "torch": importlib.util.find_spec("torch") is not None,
    "cuda_available": False,
    "cuda_device_count": 0,
}

if out["torch"]:
    import torch
    out["torch_version"] = getattr(torch, "__version__", "")
    out["cuda_available"] = bool(torch.cuda.is_available())
    out["cuda_device_count"] = int(torch.cuda.device_count()) if out["cuda_available"] else 0
    if out["cuda_available"] and out["cuda_device_count"] > 0:
        out["cuda_device_name"] = torch.cuda.get_device_name(0)

print(json.dumps(out, ensure_ascii=False, indent=2))
'@

$probeScript | & $PythonPath -

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  Write-Error "[gpu-gui] environment probe failed with exit code $exitCode"
  exit $exitCode
}

if ($CheckOnly) {
  Write-Host "[gpu-gui] check only; GUI not launched"
  exit 0
}

Push-Location $repoRoot
try {
  & $PythonPath -m acfv.cli gui run
  $exitCode = $LASTEXITCODE
} finally {
  Pop-Location
}

if ($exitCode -ne 0) {
  Write-Error "[gpu-gui] gui launch failed with exit code $exitCode"
  exit $exitCode
}
