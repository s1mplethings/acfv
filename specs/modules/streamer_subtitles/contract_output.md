# Streamer Subtitles 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 语义版本 | 1.0.0 |
| srt_path | str | 否 | 字幕 SRT 路径 | work/subtitles_streamer.srt |
| ass_path | str | 否 | 字幕 ASS 路径 | work/subtitles_streamer.ass |
| speaker | str | 否 | 选中的主播 speaker | SPEAKER_00 |
| caption_count | int | 否 | 生成字幕条数 | 128 |
| status | str | 是 | `ok`/`missing_*` | ok |

## 规则
- 成功时必须存在 `subtitles_streamer.srt` 与 `subtitles_streamer.ass`。
- 时间顺序单调，start < end。
