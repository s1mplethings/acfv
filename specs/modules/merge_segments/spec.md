# Merge Segments Spec

## 1) Purpose
- 负责：将相邻或重叠的候选段合并成更长的片段，保持时间顺序与上下文。
- 不负责：评分/选段决策、渲染。

## 2) Inputs
- 段落列表（start/end/score/text），排序可未保证。
- 配置：合并间隔阈值、最大合并长度。
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- 合并后的段落列表 JSON，包含合并来源信息与新的 start/end。
- 详情：见 `contract_output.md`。

## 4) Process
1) 校验段落结构与时间合法性。
2) 按 start 升序排序。
3) 若相邻段间隔小于阈值或重叠则合并，更新 start/end/文本。
4) 生成输出列表与可选合并映射。

## 5) Configuration
- `merge_gap_sec`（默认 1.0）：间隔阈值。
- `max_merged_duration`（默认 120.0）：超过则不再合并。

## 6) Performance Budget
- O(n log n) 排序；应在数万段内快速完成。

## 7) Error Handling
- 非法时间戳或空列表：报错或返回空并记录。

## 8) Edge Cases
- 完全重叠的段落：合并并保持最早 start/最晚 end。
- 超长合并：截断或停止合并，需记录策略。

## 9) Acceptance Criteria
- AC-MS-001 输入校验：start>=end 时报错。
- AC-MS-002 合并规则：间隔小于阈值的段被合并，输出排序正确。
- AC-MS-003 超长合并处理：超过 max_merged_duration 的合并被截断或拆分，需记录。

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
