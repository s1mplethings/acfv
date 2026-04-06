# ACFV — AI 修改/修复工作手册（以 v1.1.0 为金标准）

> 目的：让任何“AI 编程助手”（Copilot/Claude/ChatGPT/自建 Agent）在 **不跑偏、不堆垃圾文件、不破坏现有功能** 的前提下，按一个固定流程对 ACFV 做改动，并能快速回归到你认可的 **v1.1.0 水平**。

---

## 0. 给 AI 的一句话任务（直接复制给它）

你是 ACFV 仓库的代码维护 Agent。请以 **v1.1.0** 为金标准（行为、CLI/GUI 可用性、目录规范），在当前分支上实现我描述的改动。改动必须：  
1) 最小化改动范围；2) 增量提交；3) 保持 CLI/GUI 入口可用；4) 任何改动都要能通过 verify（见本文）+ tests；5) 不要在仓库根目录堆新的报告/日志/临时文件；6) 输出时给出 *patch*（diff）和复现/验证步骤。

---

## 1. 你这个仓库现在的「AI 编程结构」主要问题（为什么 AI 会改不动/改跑偏）

> 这些问题不是“代码不行”，而是 **“给 AI 的约束不够单点、验收不够硬、上下文太分散”**，导致 AI 每次改完都无法稳定收敛。

### 1.1 入口文件/规范太多，AI 不知道该信谁
仓库根目录同时存在很多“面向 AI 的说明/报告/计划”，例如 `AGENTS.md`、`SDDAI_playbook.md`、`REFACTOR_PLAN.md`、`MIGRATION_NOTES.md`、大量 `*_REPORT.md` 等（并且还有 `ai_context/`、`.codex/` 等目录）。这会让 AI：  
- 不确定“唯一权威规则”是哪份文档  
- 倾向于继续生成更多报告文件（越改越乱）

**解决原则：必须有一个“唯一入口”**：让 AI 只先读 1 个文件（建议就是 `AGENTS.md`），其它都当“参考资料”。

### 1.2 验收闸门不够“硬”，AI 改完无法自证
如果没有“一条命令”能证明：  
- CLI/GUI 还能启动  
- 关键流程还能跑  
- tests 没挂  

AI 就只能“感觉上改好了”，但你本地一跑就爆。

**解决原则：固定 verify 命令 + 最小 smoke tests**（哪怕是 30 秒跑完的）。

### 1.3 缺少「v1.1.0 金标准」的“可机器对比”方式
你说“我想回到 1.1.0 那个程度”，但 AI 没有被要求：  
- 把 v1.1.0 的行为抓成可对比的“快照”（CLI help / 默认配置 / 关键输出文件结构等）  
- 改动后自动比对差异

**解决原则：把 v1.1.0 变成一个“回归基线”**（黄金样本），每次修都能对比。

### 1.4 根目录混入“产物”（报告/zip/临时文件）会让 AI 更难判断“什么是代码、什么是产物”
根目录有 `sddai_pack.zip`、各种 `*_REPORT.md`、`tmp_*.txt` 等。AI 改动时会误把它们当成“需要维护的正式文档”，越写越多。

**解决原则：产物统一进 `docs/reports/` 或 `artifacts/`，默认不提交**。

---

## 2. ACFV 的“必须保持可用”的关键入口（这是硬验收）

从 README 可以看到你期望的入口是：  
- GUI：`python -m acfv.cli gui`  
- CLI 管线：`python -m acfv.cli.pipeline clip --url <VOD_ID 或本地 mp4> --out-dir ...`  

这些命令在任何改动后都必须仍然可用（至少 `--help` 不报错，能启动并走到合理的报错/提示）。  

---

## 3. 给 AI 的标准工作流（每次改动都照这个走）

### Step A：建立“金标准”
在你本地仓库里做（AI 也必须按这个做）：

1) 获取 v1.1.0  
- `git fetch --tags`  
- `git checkout v1.1.0`（如果 tag 名不是这个，用 `git tag --list` 找到 1.1.0 对应 tag/commit）

2) 生成 v1.1.0 快照（只要最小化可对比的内容）
- 保存 CLI 命令树（help 输出）  
- 保存默认配置/目录结构（如果有）  
- 保存一次“最小跑通”的输出目录结构样例（比如只跑到生成 work/ 结构即可）

把这些快照放在：  
- `docs/regression/v1.1.0/`（只放“人类可读 + 小文本”，不要提交大视频/大模型）

### Step B：切回当前分支，对比差异
- `git checkout main`（或你的工作分支）  
- 用 `git diff v1.1.0..HEAD -- <重点目录>` 做差异定位：  
  - `src/acfv/`（核心包）  
  - `processing/`（流程/处理）  
  - `scripts/`、`tools/`（辅助脚本）  
  - `tests/`（回归）

输出一个“差异清单”给你（文件路径 + 变化类型 + 可能影响的行为）。

### Step C：按“最小修复”策略实施
规则：  
1) **先修入口**（CLI/GUI 能跑）  
2) 再修关键链路（transcription.json/segments.json 为空等你之前遇到的硬问题）  
3) 最后再做重构/美化（能拖就拖）

每次只做一个小目标，并在同一个 PR/patch 里自证。

### Step D：硬验收（必须跑）
最小验收建议（你可以根据你机器环境删减，但 AI 不能跳过）：

- 安装（开发模式）  
  - `pip install -e .`  

- CLI smoke  
  - `python -m acfv.cli --help`  
  - `python -m acfv.cli gui --help`（若有）  
  - `python -m acfv.cli.pipeline clip --help`  

- tests  
  - `pytest -q`（或你仓库里定义的测试命令）

- 关键回归（如果你有最小样例视频）  
  - 跑一次 pipeline 到能生成 work/ 目录、且不会出现 “No segments to clip” 这种致命空输出（除非输入确实无语音/无内容）

---

## 4. “让 AI 改代码”的交付格式（你要的 patch 级别）

AI 每次输出都必须包含：

1) **变更摘要**（3~10 条）  
2) **影响面**（哪些命令/模块/文件）  
3) **patch**（diff）  
4) **如何验证**（复制粘贴就能跑的命令列表）  
5) **回滚方式**（`git revert <commit>` 或恢复到 v1.1.0 的策略）  
6) **问题记忆**（遇到坑就记录到 problem_registry）

---

## 5. 建议你把“唯一入口规范”落到一个文件：AGENTS.md（模板）

> 下面是一份你可以直接覆盖/合并进 `AGENTS.md` 的结构（让 AI 只看它）。

### AGENTS.md 推荐结构
1) 本仓库一句话目标  
2) 关键入口（GUI/CLI 命令）  
3) 目录约定（哪些是源码/哪些是文档/哪些是产物）  
4) “禁止事项”（不要在根目录堆报告、不要加重依赖、不要大重构等）  
5) verify 一条命令 + 解释  
6) patch 交付格式（上面第 4 节）

---

## 6. Issue Memory（让 AI 越修越聪明，而不是每次重来）

在仓库里固定一个位置放：  
- `docs/issue_memory/problem_registry.md`：每次遇到的 bug、原因、修复、复现命令  
- `docs/issue_memory/keywords.yaml`：你希望 AI 永远记住的规则/路径/坑点关键词  
- `docs/issue_memory/runbook.md`：常见修复动作（比如 ffmpeg、whisper、目录结构）

AI 每次修复后必须追加一条记录（短、可检索）。

---

## 7. 最小落地清单（你现在就能要求 AI 先做的 3 件事）

1) 把“唯一入口”收敛到 `AGENTS.md`（其它规则文档都在 AGENTS.md 里链接即可）  
2) 加一个 `verify` 脚本（Windows + Linux 各一份也行），跑 CLI smoke + pytest  
3) 建一个 `docs/regression/v1.1.0/`，把 v1.1.0 的最小快照放进去（help 输出/目录样例）

---

## 8. 你发给 AI 的“任务模板”（复制就能用）

【目标】把当前分支修到 v1.1.0 水平：CLI/GUI 可用、关键管线能跑通并产出合理的 work/ 结构。  
【金标准】v1.1.0（请先 checkout 并生成快照对比）。  
【禁止】不要新增根目录报告/临时文件；不要引入重依赖；不要大重构。  
【必须通过】verify + pytest。  
【交付】给出 patch + 验证命令 + 回滚方式 + problem_registry 记录。

