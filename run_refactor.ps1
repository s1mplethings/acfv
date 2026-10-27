
---

```powershell
# run_refactor.ps1
# 在 PowerShell 中运行：它会把 refactor_acfv.sh 转为 LF，并用 Git Bash 执行
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File .\run_refactor.ps1

$bash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
if (-not (Test-Path $bash)) {
  Write-Error "未找到 Git Bash：$bash"
  exit 1
}

$shIn  = Join-Path (Get-Location) 'refactor_acfv.sh'
$shOut = Join-Path (Get-Location) 'refactor_acfv.lf.sh'

if (-not (Test-Path $shIn)) {
  Write-Error "未找到脚本：$shIn"
  exit 1
}

# 转换为 LF 行尾
(Get-Content $shIn -Raw) -replace "`r","" | Set-Content $shOut -NoNewline
Write-Host "已转换为 LF：$shOut"

# 调用 Git Bash 执行
& $bash -lc "bash '$shOut'"
