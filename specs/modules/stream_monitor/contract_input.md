# Stream Monitor 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| config_path | str | 否 | 默认 `var/settings/stream_monitor.yaml`，需存在且可读 | var/settings/stream_monitor.yaml |
| targets | list[str] | 是 | 非空；频道/房间名集合 | ["streamer1", "streamer2"] |
| interval_sec | int | 否 | >=15，默认 60 | 60 |
| output_dir | str | 否 | 可写目录，不存在则创建 | recordings |
| twitch.client_id | str | 是 | 有效 Client ID | abc123 |
| twitch.token | str | 是 | OAuth Token | token |
| chat.enabled | bool | 否 | 默认 true | true |
| chat.format | str | 否 | 仅支持 json | json |
| postprocess.enabled | bool | 否 | 默认 false | false |

## 校验规则
- config_path 提供时必须存在且可读；未提供时使用默认模板。
- targets 不能为空；去重并验证字符串非空。
- interval_sec 必须为整数且满足下限，避免 API 频率过高。
- output_dir 不可写时立即报错；不存在则尝试创建。
- chat.format 仅允许 json；开启 chat 需要 TwitchDownloaderCLI 可用。

## 错误处理
- 校验失败抛 ValidationError/ValueError；启动即终止。
- 外部依赖缺失（ffmpeg/TwitchDownloaderCLI）抛 RuntimeError，日志注明命令。
