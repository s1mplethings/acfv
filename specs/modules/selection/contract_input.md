# Selection & Scoring 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| segments | list[object] | 是 | 每项含 start/end/text/score?; start<end | [{"start":1.0,"end":5.0,"text":"hi"}] |
| features | dict | 否 | 例如情绪/弹幕密度等，可选字段 | {"emotion":0.8} |
| strategy | str | 否 | `topk|threshold`，默认 topk | topk |
| topk | int | 否 | strategy=topk 时必填，>0 | 10 |
| min_score | float | 否 | strategy=threshold 时必填 | 0.6 |
| min_duration | float | 否 | >=0，默认 0 | 1.5 |
| max_duration | float | 否 | >0，默认不限 | 30.0 |
| merge_overlap | bool | 否 | 默认 True | true |

## 校验规则
- segments 非空；start/end 合法且可排序。
- strategy 必须在集合内；与 topk/min_score 的依赖关系需检查。
- min_duration <= max_duration（若提供）。

## 错误处理
- 校验失败抛 ValidationError/ValueError。
- 空段落：允许输出空列表但记录日志。
