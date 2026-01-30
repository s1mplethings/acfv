# Extract Audio 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| source_path | str | 是 | 视频文件存在且可读 | processing/input/vod.mp4 |
| out_dir | str | 否 | 默认 processing/tmp，可写 | processing/tmp |
| sample_rate | int | 否 | >0，默认 16000 | 16000 |
| channels | int | 否 | 1 或 2，默认 1 | 1 |

## 校验规则
- source_path 必须存在且为文件；ffprobe 可解析音轨。
- out_dir 不存在则创建；不可写时报错。
- sample_rate >0；channels 只能是 1/2。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
- ffmpeg/ffprobe 失败抛 RuntimeError，日志包含命令与返回码。
