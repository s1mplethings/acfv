# Extract Chat 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| chat_path | str | 是 | JSON 文件路径，存在且可读 | recordings/streamer1/123_chat.json |
| messages | int | 否 | >=0，总条数 | 1200 |
| start_time | str | 否 | ISO8601，首条时间戳 | 2024-01-01T12:00:00Z |
| end_time | str | 否 | ISO8601 | 2024-01-01T13:00:00Z |

## 确定性要求
- 消息按时间戳升序；时间戳精度到秒或毫秒，需注明。
- 命名包含 VOD ID/录制名；重复运行是否覆盖需记录。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；字段变更需版本提升并同步 tests/golden。

## Golden 策略
- 保存小样本 chat JSON 摘要（文本型）到 `tests/golden/` 用于格式验证。
