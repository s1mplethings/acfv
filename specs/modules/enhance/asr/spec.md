# ASR (Automatic Speech Recognition) Spec

## 1) Purpose
- 负责：将音频转写为文本，输出词级时间戳和稳定分句。
- 不负责：字幕渲染、特效生成、视角切换。

## 2) Inputs
- 音频文件路径（wav/mp3/m4a，优先16kHz mono）
- 配置：语言hint、模型选择（large-v3-turbo/medium/small）
- 详见 `contract_input.md`

## 3) Outputs
- `words.json`：词级时间戳 `[{word, start, end, confidence}]`
- `segments.json`：分句后的字幕 `[{text, start, end, words[]}]`
- 详见 `contract_output.md`

## 4) Process
1) 检测音频格式，必要时重采样为16kHz mono
2) 调用WhisperX或stable-ts进行转写
3) 输出词级时间戳到words.json
4) 按分句规则（标点、时长）生成segments.json
5) 记录置信度低于阈值的片段到日志

## 5) Configuration
- `whisper_model`: large-v3-turbo / medium / small / base
- `language`: auto / en / zh / ja（自动检测优先）
- `min_confidence`: 0.5（低于此值记录警告）
- `max_segment_duration`: 4.5秒（分句最大时长）

## 6) Performance Budget
- 10分钟视频：< 2分钟处理时间（GPU），< 10分钟（CPU）
- 内存占用：< 4GB（large-v3-turbo + GPU）

## 7) Error Handling
- 音频文件不存在：报错并退出
- 模型下载失败：提示检查网络和HuggingFace token
- 转写置信度过低：输出警告但不阻塞流程

## 8) Edge Cases
- 纯音乐/无人声：返回空segments并记录
- 多语言混杂：按language=auto处理，记录检测到的语言
- 音频时长>1小时：建议分块处理（chunked=True）

## 9) Acceptance Criteria
- AC-ASR-001 格式校验：输入非音频格式时报错
- AC-ASR-002 词级时间戳：words.json中每个word有start/end且递增
- AC-ASR-003 分句稳定：segments.json中片段时长在0.8s-4.5s范围内

## 10) Trace Links
- Contracts: `contract_input.md`, `contract_output.md`
- Implementation: `src/acfv/enhance/asr/transcribe.py`
- Tests: `tests/integration/test_asr_pipeline.py`
