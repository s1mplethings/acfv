# Extract Audio Spec

## 1) Purpose
- 负责：从视频容器抽取音轨，转为标准化音频（采样率/声道），供后续转写或预处理使用。
- 不负责：下载媒体、转写文本、分段与渲染。

## 2) Inputs
- 视频文件路径（可包含长路径），输出目录、目标采样率/声道数。
- ffmpeg/ffprobe 可执行。
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- 标准化音频文件（如 wav，采样率默认 16k、单声道）。
- 元数据（持续时间、采样率、声道）可写入 JSON/日志。
- 详情：见 `contract_output.md`。

## 4) Process
1) 校验视频文件存在且可读；检查 ffmpeg/ffprobe 可用。
2) 读取媒体信息，若采样率/声道不匹配则转码。
3) 将音频写入目标目录，命名包含源文件名与采样率。
4) 返回路径与元数据；记录日志。

## 5) Configuration
- `sample_rate`（默认 16000）
- `channels`（默认 1）
- `out_dir`（默认 processing 临时目录）

## 6) Performance Budget
- 抽取需线性于媒体长度；至少 1x 实时速度。

## 7) Error Handling
- 文件不存在/不可解析：报错终止。
- ffmpeg 执行失败：记录命令+返回码，返回非零。
- 写入失败：清理临时文件。

## 8) Edge Cases
- 无音轨或多音轨：选择默认轨或报错；需记录。
- 超长路径：使用 `\\?\\` 前缀。
- 极短视频：输出空音频并记录。

## 9) Acceptance Criteria
- AC-EA-001 输入校验：不存在的视频路径时报错并停止。
- AC-EA-002 采样率/声道标准化：输出满足配置，命名包含采样率。
- AC-EA-003 ffmpeg 失败：记录命令与返回码，返回非零。

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
