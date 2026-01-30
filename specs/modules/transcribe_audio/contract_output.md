# Transcribe Audio 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 语义化版本，初始 1.0.0 | 1.0.0 |
| transcript_path | str | 是 | 指向 JSON 文件，路径可写 | processing/out/sample.transcript.json |
| language | str | 是 | ISO 639-1，若输入提供则与其一致 | en |
| duration_sec | float | 是 | 原始音频时长（秒） | 612.3 |
| segments | list[object] | 是 | 按 start 升序；每项含 start/end/text/confidence/speaker | [{"start":0.5,"end":3.2,"text":"hi","confidence":0.71,"speaker":"unk"}] |
| avg_confidence | float | 否 | 0-1 | 0.74 |
| srt_path | str | 否 | 当 output_format 包含 srt 时必填 | processing/out/sample.srt |
| ass_path | str | 否 | 当 output_format 包含 ass 时必填 | processing/out/sample.ass |

## 确定性要求
- `segments` 需按 `start` 升序排序，且在同一输入 + 同一配置下重复运行输出一致。
- 时间戳精度：保留 3 位小数（毫秒级）；浮点比较使用容差 1e-3。
- 文本需去除首尾空白；编码 UTF-8。

## 稳定等级与版本策略
- `schema_version` 初始 1.0.0；新增字段保持向后兼容并增加次版本号；破坏性变更需主版本+1，并更新 tests/golden。

## Golden 策略
- 对代表性音频样本生成 JSON 与 SRT 快照，纳入 `tests/golden/` 对比。
- 允许对浮点时间戳使用容差比较；文本需精确匹配。
