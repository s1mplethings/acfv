# Semantic Merge - Contract Input

| 字段 | 类型 | 必填 | 说明 | 示例 |
| --- | --- | --- | --- | --- |
| transcript.segments | list[object] | 是 | 转录片段列表（start/end/text） | [{"start":0.0,"end":2.1,"text":"hello"}] |
| segments | list[object] | 否 | 评分/候选片段（用于聚合分数，可为空） | [{"start_ms":0,"end_ms":5000,"score":1.2}] |
| semantic.target_duration_sec | number | 否 | 语义段目标时长（默认 240） | 270 |
| semantic.min_duration_sec | number | 否 | 语义段最小时长（默认 min(60, target*0.6)） | 180 |
| semantic.max_duration_sec | number | 否 | 语义段最大时长（默认 min(target*1.6, 600)） | 300 |
| semantic.similarity_threshold | number | 否 | 相似度阈值（0-1，默认 0.75） | 0.72 |
| semantic.max_gap_sec | number | 否 | 允许的最大空隙（默认 60） | 30 |
| semantic.enabled | bool | 否 | 关闭时直接透传 segments | true |
