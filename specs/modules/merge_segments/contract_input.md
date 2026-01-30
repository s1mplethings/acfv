# Merge Segments 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| segments | list[object] | 是 | 每项含 start/end；start<end | [{"start":1.0,"end":2.5,"text":"hi"}] |
| merge_gap_sec | float | 否 | >=0，默认 1.0 | 1.0 |
| max_merged_duration | float | 否 | >0，默认 120.0 | 120.0 |

## 校验规则
- segments 非空；start/end 合法。
- merge_gap_sec >=0；max_merged_duration >0。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
