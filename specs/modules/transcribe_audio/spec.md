# Transcribe Audio Spec

## 1) Purpose
- 负责：将输入音频/视频中的音轨转为带时间戳的文本段，并输出标准化的转写 JSON/SRT（含 schema_version）。
- 不负责：下载媒体、后续剪辑/评分/渲染；不负责聊天记录同步；不负责模型下载管理。

## 2) Inputs
- 来源：处理管线前置步骤输出的音频文件，或直接由用户提供的本地文件。
- 格式：支持 wav/mp3/mp4/m4a（经 ffprobe 检测），路径需可访问且长度在 Windows 长路径兼容。
- 字段与约束：见 `contract_input.md`。

## 3) Outputs
- 转写结果 JSON（包含 segments 列表与元数据），可选 SRT/ASS 字幕文件。
- 输出路径位于 processing/working 目录或调用方指定目录；命名包含源文件名 + `transcript`.
- Schema 与稳定性：见 `contract_output.md`。

## 4) Process
1) 校验输入（存在性/格式/长度/必填字段）。
2) 确认 ffmpeg/ffprobe 可用；必要时转换为标准 wav（16k 或配置的采样率）。
3) 根据配置选择模型（Whisper 等），设置语言/提示词/分段长度/设备策略（GPU/CPU）。
4) 可选：通道分离或说话人分离（若启用 diarization）。
5) 运行转写，生成带时间戳/置信度的 segments。
6) 排序并规范化（start/end 单位秒，文本去除尾部空白，speaker 填充值）。
7) 写出 JSON（含 schema_version）与字幕文件；记录日志。

## 5) Configuration
- `language`（str，可选，默认 auto）：显式语言可跳过自动检测。
- `model_size`（str，默认 `base`）：`tiny|base|small|medium|large-v2`；影响性能与精度。
- `device`（str，默认 auto）：`cuda` or `cpu`，自动回退到可用设备。
- `split_duration`（int，可选）：>0 时按秒切片处理以降低内存。
- `prompt`（str，可选）：前置提示词。
- `diarization`（bool，默认 False）：是否尝试说话人分离。
- `output_format`（str，默认 `json`，可 `json|srt|ass|all`）。

## 6) Performance Budget
- 单 10 分钟音频在 GPU 情况下应在 2 分钟内完成；若超出需在 spec 中更新预算与原因。
- 内存：避免整体加载超大音频，推荐 split_duration + 流式处理。

## 7) Error Handling
- 输入文件不存在/不可读：抛 FileNotFoundError 或自定义 ValidationError，日志包含路径。
- ffmpeg/ffprobe 失败：抛 RuntimeError，并记录命令与返回码。
- 模型加载失败：记录异常并回退到较小模型或 CPU；若仍失败则终止并返回非零。
- 输出写入失败：使用临时文件 + rename，失败时清理临时文件。

## 8) Edge Cases
- 空音频或长度 <1s：返回空 segments，输出 schema_version，日志警告。
- 采样率异常或多通道失衡：重新采样并记录；若无法修复则报错。
- 非 UTF-8 文本：统一转为 UTF-8，替换非法字节。
- 长路径（>240）在 Windows 需添加 `\\\\?\\` 前缀。

## 9) Acceptance Criteria
- AC-TA-001 输入校验：Given 不存在的 `source_path`，When 运行转写，Then 抛出文件不存在错误并记录路径片段。
- AC-TA-002 排序与确定性：Given 同一音频与固定 `model_size`+`language`+`split_duration`，When 重复运行，Then `segments` 按 start 升序且文本相同，输出包含 `schema_version`。
- AC-TA-003 字幕写出：Given `output_format=all`，When 运行转写，Then 生成 JSON 与 SRT 文件，文件名包含源文件名与后缀。

示例输入：`{"source_path": "processing/input/sample.mp3", "language": "en", "model_size": "base"}`  
示例输出（节选）：`{"schema_version": "1.0.0", "language": "en", "segments": [{"start": 0.5, "end": 3.2, "text": "hello", "confidence": 0.71, "speaker": "unk"}]}`

## 10) Trace Links
- Contract：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_transcribe_audio_contract.py`
