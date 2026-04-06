# Semantic Merge - Contract Output

| 字段 | 类型 | 必填 | 说明 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 合约版本 | "1.0.0" |
| units | str | 是 | 时间单位（ms） | "ms" |
| sort | str | 是 | 排序策略（start_ms_asc_end_ms_asc） | "start_ms_asc_end_ms_asc" |
| policy | object | 是 | 合并策略与阈值 | {"target_duration_ms":270000} |
| segments | list[object] | 是 | 合并后的语义段 | [{"start_ms":0,"end_ms":270000,"score":1.1,"rank":1}] |
| segments[].score_base | number | 否 | 原始评分均值（未加权） | 85.32 |
| segments[].score_scale | number | 否 | 时长加权系数 | 1.25 |
| segments[].overlap_count | int | 否 | 覆盖的候选段数量 | 12 |

说明：
- segments 必须按时间升序输出，避免后续渲染重新排序导致“窗口错位”。
- score 可为空时退化为段时长评分（用于排序/调试）。
