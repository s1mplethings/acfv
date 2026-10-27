# Glossary

- AC（Acceptance Criteria）：可测的验收标准，Given/When/Then 形式。
- Contract：输入或输出的 schema/约束文档，包含字段、必填、约束、示例、错误策略。
- Golden：稳定输出的快照，用于防回归比较。
- Verify：按质量门顺序执行的组合命令集合（本仓库为 `scripts/verify.ps1`）。
- Drift：实现与 spec/contract/tests 不一致的状态，需要通过 decision_log 记录或立即修复。
- Problem Registry：失败登记表，记录症状→根因→修复→预防。
