# Selection & Scoring Spec

## 1) Purpose
- 负责：基于转写/情绪/弹幕等特征，对片段进行评分与筛选，生成候选剪辑段列表。
- 不负责：转写、渲染、下载。

## 2) Inputs
- 转写段落（带时间戳/文本/置信度）。
- 可选特征：情绪评分、弹幕密度、视频情绪、兴趣点。
- 配置：策略（topk/threshold）、最小分数、片段长度限制。
- 详见 `contract_input.md`。

## 3) Outputs
- 候选段列表 JSON（start/end/score/来源特征），按分数或时间排序。
- 可选：debug 指标（特征贡献）。
- 详见 `contract_output.md`。

## 4) Process
1) 校验输入段落与特征存在性。
2) 归一化分数，按策略计算综合得分。
3) 过滤低分/过短/过长片段；可合并重叠。
4) 排序并输出 JSON。

## 5) Configuration
- `strategy`：`topk`（k）、`threshold`（min_score）。
- `min_duration`/`max_duration`
- `merge_overlap`（bool）
- `topk`（默认 10）

## 6) Performance Budget
- 时间复杂度线性于段落数；应在数万段内快速完成。

## 7) Error Handling
- 缺少必需特征或字段：校验失败。
- 配置非法（k<1、min>max）：报错。

## 8) Edge Cases
- 空输入：输出空列表并记录。
- 重叠段：按配置合并或分别保留。
- 同分数排序：二级排序使用 start 升序。

## 9) Acceptance Criteria
- AC-SEL-001 配置校验：非法策略或 k<1 时报错。
- AC-SEL-002 排序与确定性：同配置输出按 score/时间确定排序。
- AC-SEL-003 过滤规则：低于阈值或时长不合规的段被过滤。

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
