# Clip Pipeline 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 语义化版本，初始 1.0.0 | 1.0.0 |
| clips | list[str] | 是 | 剪辑文件路径列表，存在且可读 | ["runs/out/123/clip_001.mp4"] |
| subtitles | list[str] | 否 | SRT/ASS 路径列表，与 clips 对齐 | ["runs/out/123/clip_001.srt"] |
| segments_json | str | 是 | 选段 JSON 路径，包含时间戳与分数 | runs/out/123/segments.json |
| chat_json | str | 否 | 弹幕 JSON 路径（若下载） | runs/out/123/chat.json |
| thumbnails | list[str] | 否 | 缩略图路径列表 | ["runs/out/123/thumb_001.jpg"] |
| logs | list[str] | 否 | 本次运行产生的日志路径 | ["var/logs/pipeline_123.log"] |

## 确定性要求
- clips/subtitles/segments 顺序与文件名应基于输入与配置确定性生成（同一输入+配置输出一致）。
- 时间戳与排序：`segments_json` 中段落按 start 升序；浮点时间戳精度 3 位小数。
- 命名：包含源标识（如 vod_id 或文件 stem）和序号，避免覆盖。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；新增字段需向后兼容并更新次版本；破坏性变更需主版本+1，并同步 specs/tests/golden。

## Golden 策略
- 为代表性 VOD 生成 `segments_json` 与至少 1 个剪辑的字幕快照，存入 `tests/golden/`。
- 比较策略：文本精确，时间戳容差 1e-3。
