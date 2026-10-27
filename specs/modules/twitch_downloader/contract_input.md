# Twitch Downloader 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| url | str | 是 | Twitch VOD 链接或 ID；可解析；若为 ID 自动构造 URL | https://www.twitch.tv/videos/123 |
| out_dir | str | 否 | 默认 `processing/downloads`; 可写 | processing/downloads |
| retries | int | 否 | >=0，默认 2 | 2 |
| concurrency | int | 否 | >=1，默认 1 | 1 |
| download_chat | bool | 否 | 默认 True | true |
| client_id | str | 是 | Twitch Client ID | abc123 |
| token | str | 是 | OAuth Token | token |

## 校验规则
- url 必须为合法链接或数字 ID；空值拒绝。
- out_dir 可写，不存在则创建。
- retries/concurrency 必须为非负/正整数。
- client_id/token 不可为空。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
- CLI 调用失败抛 RuntimeError，日志包含命令和 stderr。
