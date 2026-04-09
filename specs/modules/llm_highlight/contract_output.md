# LLM Highlight 输出契约

- `schema_version`: 当前为 `1.0.0`
- `units`: `ms`
- `segments`: `[{start_ms,end_ms,score,rank,highlight_type,summary,reason_tags,why_highlight,confidence}]`
- `policy`: 至少包含 `source` 与 `max_segments`

确定性要求：
- 输出按 `score desc -> start asc -> end asc` 排序。
- 回退模式下也必须输出合法 `segments` contract。
