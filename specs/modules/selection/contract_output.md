# Selection & Scoring 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| candidates | list[object] | 是 | 按 score 或 start 排序；含 start/end/score/features | [{"start":1.0,"end":5.0,"score":0.9}] |
| strategy | str | 是 | 回写使用的策略 | topk |
| topk | int | 否 | strategy=topk 时必填 | 10 |
| min_score | float | 否 | strategy=threshold 时必填 | 0.6 |

## 确定性要求
- 同一输入与配置输出排序一致；当 score 相同按 start 升序。
- 时间戳保留 3 位小数；score 保留 3 位。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；字段/排序规则变更需版本更新并同步 tests/golden。

## Golden 策略
- 代表性输入生成 candidates JSON 快照，放入 `tests/golden/`，比较排序与字段存在性。
