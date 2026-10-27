# SDDAI 总览（ACFV）

## Goal / Non-goals
- Goal：以文档驱动（spec → contract → tests → verify）方式管控 ACFV 的剪辑/转写/流媒体工具链，确保入口、输入输出契约与质量门可复现。
- Non-goals：不在本轮改造中重写业务逻辑或更换依赖；不覆盖已有 UI/CLI 设计细节；不引入新云服务。

## 全局输出约束
- 导出目录结构（如 `runs/out`, `clips/`, `var/logs/stream_monitor.log`）视为稳定契约，路径与文件命名需有版本或时间戳策略。
- 生成数据（字幕 JSON、剪辑清单、评分 JSON）必须具备 `schema_version` 字段，并在 `specs/contract_output/` 中声明排序/精度/时间戳策略。
- 随机或非确定性操作必须设定种子或排序保证（deterministic sort）；文件写入需原子（临时文件 + rename）避免半写。

## 全局输入假设
- 运行环境：Python 3.9+，ffmpeg 可执行可用，网络可访问 Twitch API（当需要），配置通过 `config.txt` / `var/settings/*.yaml` / CLI 参数提供。
- 资源路径允许 Windows 长路径，外部工具（TwitchDownloaderCLI、ffmpeg）需在 PATH 或 `var/tools/`。
- 用户凭证存放在 `secrets/*.txt` / `.env`，不得硬编码。

## 错误处理总规则
- CLI/守护进程遇到可恢复错误时写日志并返回非零 exit code；GUI 显示可读提示，日志落地 `var/logs/*.log`。
- 外部命令失败需记录命令与返回码；网络错误重试需有上限。
- 输入校验失败应使用一致的异常类型或错误码，并在 `specs/contract_input/` 里声明（若存在）。

## Spec Drift 规则
- 先更新 specs + contracts + tests，再改实现；若临时偏离需记录到 `ai_context/decision_log.md` 并补齐追溯。
- 每条验收标准（AC）需绑定至少 1 个测试用例（unit/integration/e2e/golden 任选但需说明）。

## verify（语义单入口 + OS 实现入口）
- 语义单入口：**verify**（质量闸门的统一概念入口）
- 实现入口：
  - Linux/macOS：`bash scripts/verify.sh`
  - Windows：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`

## 文档索引
- 总览：`docs/00_overview.md`
- 架构与数据流：`docs/01_architecture.md`
- 端到端工作流：`docs/02_workflow.md`
- 质量门定义：`docs/03_quality_gates.md`
- Quickstart：`docs/10_workflow.md`
- Conventions：`docs/20_conventions.md`
- 模块与契约索引：`specs/index.md`
- 模块模板：`specs/templates/`
- 运行与排障：`ai_context/runbook.md`
- 关键词记忆：`ai_context/keywords.yaml`

## Auto/Agent Scaffold（可选）
- 建议代理运行循环：Discover → Plan → Patch → Verify → Record → Report（见 `docs/10_workflow.md`）。
- 自动运行产物建议写入：`ai_context/runs/<timestamp>/`（便于回溯与对比）。
