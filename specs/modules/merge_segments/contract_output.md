# Merge Segments 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| merged_segments | list[object] | 是 | start/end 升序；每项含 merged_from | [{"start":1.0,"end":4.0,"merged_from":[0,1]}] |
| merge_gap_sec | float | 否 | 回写使用的阈值 | 1.0 |
| max_merged_duration | float | 否 | 回写限制 | 120.0 |

## 确定性要求
- 排序：按 start 升序，若相同按 end。
- merged_from 索引或标识保持确定。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；字段变更需版本提升并同步 tests/golden。

## Golden 策略
- 保存小样本合并结果 JSON（文本）用于比较顺序与 merged_from。
