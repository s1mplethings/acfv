# Runbook（运行与排障）

## 常用命令
- verify（Linux/macOS）：`bash scripts/verify.sh`
- verify（Windows）：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`

## 排障顺序（建议）
1) 看 `var/logs/*.log`（守护/CLI/GUI 各自日志）
2) 复现最小命令（写入 problem_registry）
3) 对照 spec/contract（看是否 drift）
4) 修复后跑 verify（必须过 gate）

## 产物定位
- 运行产物建议统一落盘：`runs/out/` 或 `ai_context/runs/<timestamp>/`
