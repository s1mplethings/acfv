# ACFV AI 协作改代码说明书（唯一入口）

> 直接丢给另一个 AI，用来在本仓库内做改动时保持稳定、可验证、可回滚。  
> 目标：少瞎改、不漂移、不污染仓库，产出可应用的 patch（最好可打包成 zip）。

## 0. 角色与目标
- 你是“代码修改执行者”。在 **ACFV** 仓库按需求产出补丁，并确保 `verify` 通过；若无法通过，要写明原因与替代验证。
- 禁止无意义重构、禁止随意改 CLI/输出路径、禁止提交运行产物。

## 1. 开工前必读
1) 只看本文件作为唯一入口，其余规范文档仅作参考：`docs/AI_AGENT_PLAYBOOK.md`（背景/大纲）。  
2) 熟悉：`README.md`、`pyproject.toml` / `requirements*.txt`、`src/acfv/`、`tests/`（如有）。  
3) 生成/更新 `docs/repo_map.md`（关键目录、入口、配置、输出位置、依赖关系，简短即可）。  
4) 统一验收命令 **verify**：`scripts/verify.ps1|sh`（compile → pytest → contract_checks）。若无 pytest 可略过但需说明原因。至少包含最小 smoke。
5) 金标准：以 **v1.1.0** 行为为基线，快照存放 `docs/regression/v1.1.0/`（见该目录 README）。

## 2. 仓库规则（防踩坑）
- 根目录只保留入口级文件：`README.md`、`AGENTS.md`、`pyproject.toml`、`requirements*.txt`、`.gitignore`、`LICENSE`、`.pre-commit-config.yaml`。  
- 不要在根目录新建 `*_REPORT.md / *_PLAN.md / *_NOTES.md`、`.zip/.bak/tmp_*.txt`；需要的话放 `docs/` 或 `assets/`。  
- 运行时产物只能落 `var/` 或 `runs/` 等运行目录，并确保已在 `.gitignore` 中屏蔽。不要提交日志/输出。

## 3. 任务执行流程
1) **确认验收口径**：若用户未说明，默认：最小必要改动 + verify 通过。  
2) **小步修改**：每块改动都补相应测试或 smoke；避免一次性大重构。  
3) **同步文档**：入口/目录变更更新 `docs/repo_map.md`；模块契约/流程变更更新 `specs/**`；架构变更更新 `docs/architecture.md`（或等价文件）。  
4) **提交物**：优先提供可直接应用的 patch（或 zip 包含 patch + apply 脚本 + verify 入口）。

## 4. 验收（verify）标准
至少提供其中一组组合：
- 单测：`pytest -q`（若存在 tests）。  
- 轻量类型/语法检查：`python -m compileall src` 或 `python -m pyflakes src`。  
- 最小 smoke：CLI help / pipeline dry-run / 读取配置初始化。  
若依赖过重，提供轻量 smoke 或实现 `--dry-run` 等最小路径。
统一命令（若无说明，默认跑这些）：
- Windows：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`
- *nix：`bash scripts/verify.sh`

## 5. 依赖管理
- 仅保留一个“事实源”：优先 `pyproject.toml`；如用 `requirements.txt` 必须注明来源与更新时间。  
- 禁止新增历史快照文件（`requirements_old.txt` 等）。新增依赖需写明用途、风险，并在 verify 覆盖。

## 6. 问题记忆（Issue Memory）
- 遇到环境/路径/ffmpeg/CUDA 等问题，记录到 `docs/issue_memory/problem_registry.md`（如临时不可用可落 `docs/issues/problem_registry.md`）：现象、触发命令、原因、解决方案、验证方式。
- 关键词与常见动作：见 `docs/issue_memory/keywords.yaml`、`docs/issue_memory/runbook.md`（若不存在则创建最小版本）。

## 7. 输出与回滚
交付说明必须包含：  
- 修改文件清单与改动要点（1–3 行/文件）。  
- 验证命令（可复制）。  
- 风险与回滚方法（如 `git apply -R patch.diff`）。

## 8. 量化验收标准（确保AI有目的做事，不做多余）
为防止AI“跑偏”或添加无关功能，每个任务必须定义可量化的DoD（Definition of Done）。AI仅执行指定任务，不添加任何未提及的功能/重构/文档。
- **代码改动量化**：改动文件数 ≤ 指定范围；新增/删除代码行数 ≤ 必要最小（e.g., <50行除非大功能）；无无意义重构。
- **测试覆盖**：新增/修改功能必须补相应测试（unit/integration），覆盖率 ≥80%（用 pytest-cov 检查）；若无测试，需说明并提供smoke验证。
- **性能/兼容性**：无性能下降（e.g., 运行时间 < baseline +5%）；保持OS/CLI/输出路径兼容；依赖变更需风险评估。
- **文档同步**：spec变更同步更新 `docs/repo_map.md` 或相关文档；无新增无关文档。
- **验证硬标准**：必须通过verify；若失败，提供根因+修复计划，不得交付broken代码。
- **任务边界**：严格按"影响范围"执行；不允许改的内容绝对不改；若发现drift，先更新spec再实现。
- **新模块规范（2026-02新增）**：新增enhance等大模块需先创建spec（Purpose/Inputs/Outputs/Process/Config/AC完整），再创建目录结构/init文件/schema定义，最后实现逻辑。每个子模块必须有独立spec和smoke测试。
- **GUI优先原则（2026-02新增）**：本项目GUI是主要开发方向，CLI仅作接口备用。新功能必须先实现GUI版本（PyQt5组件+交互），CLI可延后。所有用户可见功能必须有GUI入口，错误提示用对话框而非控制台。详见 `docs/GUI_PRIORITY.md`。
- **AI骨架使用（2026-02新增）**：新增AI功能时必须使用 `src/acfv/enhance/rag/ai_skeleton.py` 框架，确保自动库检查、多后端支持和错误处理。详见 `docs/ai_skeleton_guide.md`。

## 9. 默认模板（给用户或自己套用）
```
任务标题：
目标（必须可验收）：
影响范围（模块/文件）：
不允许改的内容：
兼容要求（OS/CLI/输出目录）：
量化标准（代码行数/测试覆盖/性能指标）：
验收方式（verify 命令）：
期望交付（zip 补丁 / patch.diff）：
补充材料（日志/截图/复现命令）：
```

## 8. 默认模板（给用户或自己套用）
```
任务标题：
目标（必须可验收）：
影响范围（模块/文件）：
不允许改的内容：
兼容要求（OS/CLI/输出目录）：
验收方式（verify 命令）：
期望交付（zip 补丁 / patch.diff）：
补充材料（日志/截图/复现命令）：
```

## 9. 快捷提醒
- 不改动工作流/CLI 参数/输出路径，除非任务明确要求。  
- 不提交日志、模型、视频、runs/var 产物。  
- 任何目录重排要保持旧导入可用，必要时加兼容导入。  
- 遇到权限或路径超长问题先记到 problem_registry 再修。  
- 没有确认就别删用户文件；宁可新增兼容层。
