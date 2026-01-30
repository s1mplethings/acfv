# Twitch Downloader 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| video_path | str | 是 | 下载的视频文件路径，存在且大小>0 | processing/downloads/123.mp4 |
| chat_path | str | 否 | download_chat 为 True 时必填且存在 | processing/downloads/123_chat.json |
| log_path | str | 否 | 日志文件路径 | var/logs/twitch_downloader.log |

## 确定性要求
- 命名：包含 VOD ID；同一输入仅覆盖或重用同名文件，需记录策略。
- 重试后成功：最终输出应一致，不生成重复文件。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；变更输出命名或字段需版本更新并同步 tests/golden。

## Golden 策略
- 对小型 VOD 样本记录下载日志和文件命名示例（文本型）放入 `tests/golden/` 进行格式比较。
