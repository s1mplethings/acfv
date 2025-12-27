[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$IncludeData
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot

$targets = @(
    "dist",
    "build",
    "logs",
    "thumbnails",
    "processing.log",
    "artifacts\\large",
    "var\\cache",
    "var\\logs"
)

if ($IncludeData) {
    $targets += "clips"
    $targets += "var\\processing"
}

function Remove-Target {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        if ($DryRun) {
            Write-Host "Would remove: $Path"
        } else {
            Remove-Item -LiteralPath $Path -Recurse -Force
            Write-Host "Removed: $Path"
        }
    }
}

foreach ($target in $targets) {
    $fullPath = Join-Path $projectRoot $target
    Remove-Target -Path $fullPath
}

$pycaches = Get-ChildItem -Path $projectRoot -Recurse -Directory -Force -Filter "__pycache__" -ErrorAction SilentlyContinue
foreach ($dir in $pycaches) {
    Remove-Target -Path $dir.FullName
}
