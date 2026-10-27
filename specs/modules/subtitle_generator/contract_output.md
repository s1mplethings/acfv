# Subtitle Generator 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| subtitle_path | str | 是 | 输出字幕路径，存在且可读 | runs/out/123/subtitle.srt |
| format | str | 是 | `srt|ass` | srt |
| segments | int | 否 | >=0，输出段数 | 120 |

## 确定性要求
- 输出按 start 升序；时间偏移后的时间戳保留 3 位小数。
- 命名包含源标识或 out_dir，并与 format 后缀对应。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；命名或字段变更需版本更新并同步 tests/golden。

## Golden 策略
- 选取小样本生成 SRT/ASS 文本快照，保存到 `tests/golden/` 用于比较格式与排序。
