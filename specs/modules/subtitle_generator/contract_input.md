# Subtitle Generator 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| segments | list[object] | 是 | 每项含 start/end/text；start<end | [{"start":0.5,"end":3.2,"text":"hi"}] |
| format | str | 否 | `srt|ass`，默认 srt | srt |
| out_dir | str | 否 | 可写目录 | runs/out/123 |
| time_offset_sec | float | 否 | 可正负，默认 0 | -0.3 |
| framerate | float | 否 | format=ass 时可用；>0 | 23.976 |

## 校验规则
- segments 非空；字段存在且合法。
- format 在允许集合；out_dir 可写。
- framerate >0（ASS 时）。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
- 写入失败抛 RuntimeError，并记录路径。
