# Extract Chat 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| url | str | 否 | VOD 链接或 ID，与 `recording_dir` 至少一项提供 | https://www.twitch.tv/videos/123 |
| recording_dir | str | 否 | 录制输出目录，存在且可读 | recordings/streamer1 |
| out_dir | str | 否 | 默认同录制目录，可写 | recordings/streamer1 |
| retries | int | 否 | >=0，默认 2 | 2 |
| clean.enabled | bool | 否 | 默认 True | true |

## 校验规则
- url 与 recording_dir 至少一项；若两者皆空则报错。
- out_dir 不存在则创建；不可写报错。
- retries 非负整数；clean.enabled 为布尔。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
- CLI 失败抛 RuntimeError，日志包含命令与返回码。
