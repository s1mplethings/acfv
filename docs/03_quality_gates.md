# 质量门（Quality Gates）

## Gate 顺序
1) format/lint/typecheck（可选，若启用需列命令）
2) unit（快速逻辑检查）
3) integration（强制：输入契约→输出契约）
4) e2e（至少 1 条主路径，建议）
5) contract checks（强制，涵盖 schema_version/排序/精度）
6) golden（建议：关键输出快照）

## 失败处理与记录
- 任一 gate 失败即视为 verify 失败；记录到 `ai_context/problem_registry.md`，附命令与日志片段。
- 若需要临时豁免，必须记录到 `ai_context/decision_log.md`，并设定后续补齐计划。

## verify 定义（语义单入口 + OS 实现入口）
- 语义单入口：**verify**
- 实现入口：
  - Linux/macOS：`bash scripts/verify.sh`
  - Windows：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`
- 默认步骤：环境自检（可选）→ unit/integration/e2e/golden 测试 → 汇总结果
- 可按参数扩展 lint/typecheck，但需保持 CI 与本地一致。

## CI 要求
- CI（若存在）必须执行与 runner OS 对应的 verify 实现入口，并与本地保持同一组步骤（避免分歧）。

## contract checks（最小必须项）
contract checks 的目标是：把“输出契约”从“文档约定”变成“可自动失败”的质量门。

最小必须项（建议脚本化）：
- 所有生成 JSON 必须包含 `schema_version`。
- 候选段（segments）必须满足：
  - 单位一致（`units=ms`）
  - `0 <= start_ms < end_ms`
  - 时长 >= 6s（分析阶段即剔除超短段；剪辑阶段再防御过滤）
  - 可选：若提供 `video_duration_ms`，则 `end_ms <= video_duration_ms`
  - 排序满足 contract 中声明的规则（确定性）
- 剪辑清单（manifest）必须满足：
  - 记录每个 clip 的输入段（start/end）与输出路径（video/subtitle/thumbnail）
  - 输出命名策略可回溯：`clip_{rank:03d}_{HHhMMmSSs}_{start_ms}-{end_ms}.mp4`
  - 每个 clip 时长目标 4~5 分钟（配置 MIN/TARGET/MAX = 240/270/300s），不含纯音乐/带语音的音乐段（分析阶段按标签/空文本剔除）
