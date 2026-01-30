# Stream Monitor 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 语义化版本，初始 1.0.0 | 1.0.0 |
| recordings | list[str] | 是 | 录制文件路径列表，文件存在且可读 | ["recordings/streamer1/20240101_120000.mp4"] |
| chat_logs | list[str] | 否 | chat JSON 路径列表，存在且与 recordings 对齐 | ["recordings/streamer1/20240101_120000_chat.json"] |
| log_path | str | 是 | 运行日志文件路径 | var/logs/stream_monitor.log |
| last_poll | str | 否 | ISO8601，最近轮询时间 | 2024-01-01T12:00:00Z |

## 确定性要求
- 文件命名：包含频道标识与 UTC 时间戳，避免覆盖；排序按录制开始时间升序。
- 时间戳格式：ISO8601；日志记录包含开始/结束时间。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；新增字段向后兼容，破坏性变更需主版本更新并同步 tests/golden。

## Golden 策略
- 以短录制样例生成日志与文件命名示例快照（文本型），可放入 `tests/golden/` 用于比较命名/格式。
