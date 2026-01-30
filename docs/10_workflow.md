# Workflow（Quickstart）

> 这是 Quickstart。完整规则与细节以 `docs/02_workflow.md` 与 `docs/03_quality_gates.md` 为准。

## Human-driven
1) Write/Update spec（若涉及行为/输出/CLI/API/契约变化：必须更新 specs/contracts/tests）
2) Create Task Card（使用统一模板：`ai_context/task_cards/_template.md`）
3) Implement (smallest change)
4) Run verify（Linux/macOS：`bash scripts/verify.sh`；Windows：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`）
5) If FAIL: record to `ai_context/problem_registry.md`
6) If PASS: finalize PR

## Auto loop (optional)
Discover → Plan → Patch → Verify → Record → Report
