# SDDAI 改造任务说明（给 AI 的执行文档 / 可直接复制）

> 目的：把这个仓库改造成「总文档 + 模块分 spec + 输出/过程契约 + test + verify + 问题记忆（Issue Memory）」的 SDDAI 工作流。  
> 你是执行改造的 AI。请严格按本文件要求行动，不允许跳步或偷改需求。

---

## 0. 必须遵守的总原则（硬规则）
1) **Spec 是唯一事实来源**：如果实现与 spec 冲突，必须先更新 spec + tests，再改代码。  
2) **每条 AC（验收标准）必须对应至少 1 个测试**：缺测试就算没完成。  
3) **禁止为了过测试删测试/弱化断言**：修复必须是改实现或补齐 spec。  
4) **任何失败都必须记录**：只要出现 build/run/test/CI 失败或输出不一致，必须登记到 `ai_context/problem_registry.md`（症状→根因→修复→预防）。  
5) **最终以 verify 为准**：PR 合并前必须 `verify PASS`。  

---

## 1. 你开始动手前要做的事（必须）
请先阅读并总结（不要写代码）：
- 当前仓库的入口（如何运行、如何测试、有哪些输出）
- 当前仓库的模块划分（哪几个主要模块/步骤）
- 当前仓库最关键输出（哪些文件/JSON/目录结构是契约）
- 当前已有测试情况（有无 pytest/jest/cargo test 等）

输出要求（仅文字）：
- 入口命令列表（install/run/test）
- 模块列表（至少 5 个或按实际）
- 输出产物清单（路径 + 作用）
- 你建议的 verify 组成（哪些命令）

---

## 2. 必须新增的目录与文件（一次性创建）
在仓库根目录新增以下结构（如已存在则补齐内容）：

```
docs/
  00_overview.md
  01_architecture.md
  02_workflow.md
  03_quality_gates.md
  glossary.md

specs/
  index.md
  templates/
    module_spec.md
    contract_input.md
    contract_output.md
    tasks.md
    traceability.md
  modules/
    <module_name>/
      spec.md
      contract_input.md
      contract_output.md
      tasks.md
      traceability.md

ai_context/
  README.md
  keywords.yaml
  problem_registry.md
  runbook.md
  anti_patterns.md
  decision_log.md

tests/
  unit/
  integration/
  e2e/
  golden/

scripts/
  verify.sh   (或 verify.ps1 / verify.py，按仓库平台选择)
```

---

## 3. docs 文档要求（必须写到可执行）
### 3.1 docs/00_overview.md 必须包含
- Goal / Non-goals  
- 全局输出约束（哪些输出字段/结构不允许随便改）  
- 全局输入假设  
- 错误处理总规则（返回码/异常/日志策略）  
- Spec Drift 规则（先 spec+tests 再实现）  
- 文档索引链接（指向 specs/index.md、runbook、verify）  

### 3.2 docs/01_architecture.md 必须包含
- 模块表：模块名 | 输入来自 | 输出给谁 | 边界 | 依赖 | 运行方式  
- 数据流描述：从入口到最终输出经过哪些模块与产物  
- 稳定边界：哪些模块/输出是稳定契约  

### 3.3 docs/02_workflow.md 必须包含
- Spec 写作最低标准（AC 必须可测）  
- Tasks 拆解规则（每条 task 必须 DoD + 验证命令）  
- 实现循环（一次只做 1 个 task：先测试后实现）  
- Drift 处理流程  
- 问题记忆（problem_registry）的记录规则  

### 3.4 docs/03_quality_gates.md 必须包含
- Gate 顺序：format/lint/typecheck（可选）→ unit → integration（强制）→ e2e（建议至少 1 条）→ contract checks（强制）→ golden（建议）  
- 每个 gate 的失败处理与记录要求  
- verify 的精确定义（verify = 哪些命令的组合）  
- CI（若有）必须跑 verify  

---

## 4. 每个模块 spec 套件（必须清晰分开）
对每个模块（至少先完成 1 个核心模块作为样板）创建：
- `specs/modules/<module>/spec.md`
- `specs/modules/<module>/contract_input.md`
- `specs/modules/<module>/contract_output.md`
- `specs/modules/<module>/tasks.md`
- `specs/modules/<module>/traceability.md`

### 4.1 spec.md 必须包含（10 段缺一不可）
1) Purpose（负责什么/不负责什么）  
2) Inputs（来源+格式+字段+约束）  
3) Outputs（去向+格式+字段+稳定性）  
4) Process（步骤列表/伪代码）  
5) Configuration（参数、默认值、范围、影响）  
6) Performance Budget（可选）  
7) Error Handling（错误码/异常/降级）  
8) Edge Cases（空输入/异常格式/极端数据）  
9) Acceptance Criteria（AC：Given/When/Then + 样例输入输出）  
10) Trace Links（指向 tests + contract + traceability）  

### 4.2 contract_input.md 必须包含
- 输入 schema 表（字段名/类型/必填/约束/示例）  
- 校验规则（逐条可实现）  
- 输入不合格时的报错策略（错误码/异常）  

### 4.3 contract_output.md 必须包含
- 输出 schema 表（字段名/类型/必填/约束/示例）  
- 确定性要求（排序/随机种子/浮点精度/时间戳策略）  
- 稳定等级与版本策略（schema_version）  
- golden 快照策略（哪些输出要快照）  

### 4.4 traceability.md 必须有追踪表
- AC ID | 说明 | 测试文件 | 测试用例名 | 层级(unit/integration/e2e/golden) | 状态  

---

## 5. Test + Verify（必须能跑）
### 5.1 tests 分层要求
- unit：内部逻辑（快）  
- integration：**输入契约 → 输出契约**（强制）  
- e2e：全流程至少 1 条主路径  
- golden：关键输出快照（防回归）  

### 5.2 scripts/verify.* 要求
- 提供单一入口：一条命令跑完所有 gates  
- 输出清晰（哪一步失败、如何复现）  
- 本地和 CI（如有）一致  

最终验收：你必须展示一次 `verify PASS` 的结果（命令+输出摘要）。

---

## 6. Issue Memory（关键词 + 问题登记：你必须接入）
### 6.1 ai_context/keywords.yaml 必须包含
- entrypoints（install/run/test/verify 命令）  
- invariants（不可破坏规则：输出 schema、确定性等）  
- error_signatures（报错片段 → 建议动作 + tags）  
- hotspots（高风险模块/文件）  
- tags（deps/path/encoding/schema/perf/gpu/ci…）  

### 6.2 ai_context/problem_registry.md 记录规则（强制）
任何失败都必须新增一条（按模板）：
- Context（模块/命令/环境）  
- Symptoms（错误片段）  
- Root Cause（为什么会发生）  
- Fix（改了什么 + 如何验证）  
- Prevention（怎么防复发：新增测试/校验/文档/关键词）  

### 6.3 ai_context/runbook.md 必须可复现
必须写清：
- install/run/test/verify  
- 常见报错排查步骤（按 tags）  
- 输出位置、日志位置  
- golden 更新与检查方法  

### 6.4 ai_context/anti_patterns.md（禁止行为）
必须列出：
- 禁止删测试/弱化断言  
- 禁止改输出契约但不更新 spec/contract/tests/golden  
- 禁止绕过 verify 合并  
- 禁止出现 drift 不记录 decision  

---

## 7. 你每次提交（或输出结果）必须包含的内容
- 新增/修改文件列表（按目录归类）  
- 关键变更摘要（每项对齐哪个文档/哪个模块 spec）  
- verify 命令与结果（PASS/FAIL）  
- 若遇到问题：problem_registry 的条目编号（PRB-xxxx）  
- 若发生 spec drift：decision_log 的条目编号（DEC-xxxx）  

---

## 8. 迁移策略（先做最小样板，再扩展）
你必须按这个顺序做：
1) 先建 docs + ai_context + verify 框架（不改业务）  
2) 选 1 个核心模块完成“spec 套件 + 对应 integration 测试”  
3) verify 全绿后，再逐个模块扩展  

---

## 9. 失败处理（你不能卡住）
如果你无法确定某个命令/入口：
- 先在 `ai_context/runbook.md` 写“已知未知点”  
- 在 `problem_registry.md` 记录 PRB 条目（包含你尝试过什么）  
- 给出你下一步将如何确认（例如：搜索 README、grep 入口、查看 setup/pyproject/package.json）  

---

> 完成标志：仓库具备「总文档 + 至少 1 个模块完整 spec 套件 + tests + verify + issue memory」，并能 `verify PASS`。
