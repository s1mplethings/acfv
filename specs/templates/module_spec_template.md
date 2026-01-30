# <Module Name> Spec

## Purpose
- 这一步解决什么问题？属于哪个 pipeline 阶段？

## Inputs
| 字段/文件 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |

## Outputs
| 字段/文件 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |

## Config
- 配置来源（CLI/YAML/config.txt）与默认值
- 参数范围、单位

## Process
- 步骤化描述（尽量能映射到函数/文件）
- 明确排序/随机性/精度策略

## Error Handling
- 错误码/异常类型（或统一的错误返回结构）
- 外部命令失败如何记录（命令 + 返回码）

## Edge Cases
- 空输入、缺文件、越界、重叠、极端长视频等

## Performance
- 复杂度/大致耗时点
- 性能预算（如有）

## Acceptance Criteria (AC)
使用 Given/When/Then（可测、可复现）：
- AC-1: ...
- AC-2: ...

## Trace Links
- tests: `tests/...`
- contracts: `specs/contract_*...`
- code: `src/...`
