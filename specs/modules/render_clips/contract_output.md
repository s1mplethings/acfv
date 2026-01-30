# Render Clips 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| clips | list[str] | 是 | 剪辑文件路径列表，文件存在 | ["runs/out/123/clip_001.mp4"] |
| subtitles | list[str] | 否 | 与 clips 对齐的字幕路径 | ["runs/out/123/clip_001.srt"] |
| thumbnails | list[str] | 否 | 缩略图路径 | ["runs/out/123/thumb_001.jpg"] |
| log_path | str | 否 | 渲染日志路径 | var/logs/render_123.log |

## 确定性要求
- 命名：包含源标识与序号，clips/subtitles 对齐且排序一致。
- 时间戳：若输出字幕，时间戳精度 3 位小数。
- 同一输入 + 配置下输出应一致（确定性）。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；新增字段向后兼容，破坏性变更需主版本提升并更新 tests/golden。

## Golden 策略
- 对代表性段落生成字幕与文件列表快照（文本/JSON），纳入 `tests/golden/` 进行比较（路径与命名）。
