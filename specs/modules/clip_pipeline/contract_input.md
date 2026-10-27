# Clip Pipeline 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| url | str | 是 | Twitch VOD 链接或本地文件路径，存在且可读；支持 http/https/file | https://www.twitch.tv/videos/123 |
| out_dir | str | 否 | 默认 `runs/out`; 可写且可创建 | runs/out |
| cfg | str | 否 | YAML 配置路径；存在且可读 | var/settings/pipeline.yaml |
| no_chat | bool | 否 | True 时跳过 chat 下载 | false |
| no_clip | bool | 否 | True 时仅执行前置步骤（转写等），不渲染剪辑 | false |
| download.retries | int | 否 | >=0，默认 2 | 2 |
| transcribe.model_size | str | 否 | `tiny|base|small|medium|large-v2` | base |
| transcribe.language | str | 否 | ISO 639-1，空则自动检测 | en |
| selection.strategy | str | 否 | `topk|threshold` 等，需在实现支持的集合内 | topk |
| render.template | str | 否 | 模板名或路径，需存在 | default |

## 校验规则
- `url` 必须是可解析的 VOD 链接或现存文件；当为 URL 时需要 Twitch 凭证或可匿名访问。
- `out_dir` 不存在则创建，存在但不可写时报错。
- `cfg` 提供时需可读且解析成功，冲突字段以 CLI 为优先。
- 选项值必须在允许集合内（模型、策略、布尔等）。

## 错误处理
- 校验失败抛 ValidationError/ValueError，日志包含字段与示例值。
- 下载/外部依赖缺失抛 RuntimeError，指明命令或 URL。
