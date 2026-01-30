# Transcribe Audio 输入契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| source_path | str | 是 | 文件存在且可读，支持长路径；音频/视频容器需 ffprobe 可解析；可直接使用 extract_audio 的 `audio_path` | processing/input/sample.mp3 |
| work_dir | str | 否 | 默认使用 processing_path，需可写；自动创建子目录 | processing/tmp |
| language | str | 否 | ISO 639-1 代码；为空时自动检测 | en |
| model_size | str | 否 | `tiny|base|small|medium|large-v2` | base |
| device | str | 否 | `cuda` 或 `cpu`，默认自动选择 | cuda |
| split_duration | int | 否 | 秒，>0；用于长音频分片 | 300 |
| diarization | bool | 否 | 默认 False；True 时需可用 diarization 依赖 | false |
| prompt | str | 否 | 前置提示词，可为空 | "twitch stream intro" |
| output_format | str | 否 | `json|srt|ass|all`，默认 json | all |

## 校验规则
- `source_path` 必须存在且为文件；当为视频时需可抽取音轨；若来自 extract_audio，请传其 `audio_path` 字段。
- `work_dir` 不存在则创建，存在但不可写则报错。
- `language` 提供时跳过自动检测；非法语言代码报错。
- `model_size` 不在允许列表时报错。
- `split_duration` 若提供必须为正整数；与 diarization 不冲突。
- `output_format` 必须在允许集合内。

## 错误处理
- 校验失败抛 ValidationError / ValueError，日志写入错误字段名与值。
- 外部依赖缺失（ffmpeg/模型）时抛 RuntimeError，指明命令或模型名。
