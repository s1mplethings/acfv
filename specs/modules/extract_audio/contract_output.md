# Extract Audio 输出契约

## Schema
| 字段 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| schema_version | str | 是 | 初始 1.0.0 | 1.0.0 |
| audio_path | str | 是 | 输出音频文件路径，存在且可读 | processing/tmp/vod_16k.wav |
| sample_rate | int | 是 | 与配置一致 | 16000 |
| channels | int | 是 | 与配置一致 | 1 |
| duration_sec | float | 否 | >=0 | 600.5 |

## 确定性要求
- 命名包含源文件名与采样率；重复运行可覆盖或复用需记录策略。
- 时间长度来源于 ffprobe，保留 3 位小数。

## 稳定等级与版本策略
- schema_version 初始 1.0.0；命名或字段变化需升级版本并同步 tests/golden。

## Golden 策略
- 以小样本视频抽取的音频元数据文本快照纳入 `tests/golden/`（非必须音频二进制）。
