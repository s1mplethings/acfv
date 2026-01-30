# AI Context

目的：为 AI/开发者提供一致的入口、约束与决策记忆，避免 drift。

## 组成
- `keywords.yaml`：入口命令、不可变规则、常见错误签名、热点文件。
- `problem_registry.md`：失败登记（症状→根因→修复→预防）。
- `runbook.md`：安装/运行/测试/verify 与常见排障。
- `anti_patterns.md`：明确禁止行为。
- `decision_log.md`：记录偏离 spec/契约的决策与原因。

使用方式：修改实现或发现异常时，先查关键词与 runbook；出现失败及时登记；需要临时豁免时更新 decision_log。

## Starter add-ons
- `prompts/`: agent 入口与 bugfix/feature playbook、输出格式。
- `auto/`: 自动模式规则、结果模板与 `agent_config.json`（配置你的 ai_cmd）。
