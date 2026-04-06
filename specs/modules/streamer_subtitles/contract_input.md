# Streamer Subtitles 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| transcription_path | str | 是 | 转写 JSON，含 segments/words | work/transcription.json |
| speaker_result_path | str | 是 | 说话人分段结果 | work/speaker_separation/speaker_separation_result.json |
| primary_speaker | str | 否 | 覆盖自动识别 | SPEAKER_00 |
| out_dir | str | 否 | 默认 work 目录 | work |
| format | str | 否 | `srt|ass|both` | both |

## 校验规则
- transcription_path 与 speaker_result_path 必须存在且可读。
- 主播识别失败应返回明确状态码。
