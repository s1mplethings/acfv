# Render Clips 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| source_path | str | 是 | 视频文件存在且可读 | processing/input/vod.mp4 |
| segments | list[object] | 是 | 每项含 start/end（秒），start<end，升序或可排序 | [{"start":10,"end":25,"text":"gg"}] |
| out_dir | str | 否 | 默认 `runs/out`; 可写且可创建 | runs/out/123 |
| codec | str | 否 | ffmpeg 支持的编码，默认 libx264 | libx264 |
| fps | int | 否 | >0；为空则继承源 | 30 |
| resolution | str | 否 | 形如 1920x1080；为空则继承源 | 1280x720 |
| subtitle.enabled | bool | 否 | 默认 True | true |
| subtitle.format | str | 否 | `srt|ass` | srt |
| thumbnail.enabled | bool | 否 | 默认 False | false |
| thumbnail.timestamp | float | 否 | 若启用，需在段落范围内 | 12.0 |

## 校验规则
- source_path 必须存在且可读。
- segments 非空；start/end 为浮点或整数，start<end；越界则报错或裁剪需记录。
- out_dir 不存在则创建，存在不可写时报错。
- codec/fps/resolution 在允许范围内；subtitle/thumbnail 选项互相独立。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
- ffmpeg 缺失或执行失败抛 RuntimeError，日志包含命令与返回码。
