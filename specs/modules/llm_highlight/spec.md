# LLM Highlight Spec

## 1) Purpose
- 负责：在现有规则粗召回基础上，结合 transcript/chat/screen context/video emotion 做 LLM 精排。
- 不负责：抽帧、转写、最终视频裁剪。

## 2) Inputs
- `segments`: 来自 `semantic_merge` 的候选段。
- `transcript` / `chat` / `screen_context` / `video_emotion`。
- 配置：`ENABLE_LLM_HIGHLIGHT`、`MAX_CLIP_COUNT`、`LLM_HIGHLIGHT_CANDIDATE_MULTIPLIER`、`LLM_HIGHLIGHT_MAX_CANDIDATES`、`OPENAI_*`。

## 3) Outputs
- 结构化最终高光列表，包含 `start/end/score/highlight_type/summary/reason_tags/why_highlight/confidence`。

## 4) Process
1) 读取粗召回候选段并裁剪为有限候选；默认候选池按 `MAX_CLIP_COUNT * 5` 放大。
2) 为每个候选聚合 transcript/chat/screen/emotion 上下文。
3) 默认先尝试本地 Ollama/OpenAI-compatible `LLM_LOCAL_*` 做候选蒸馏，压缩出 `local_distill` 语义摘要。
4) 再使用 `LLM_HIGHLIGHT` / `OPENAI_*` 做最终精排，并明确告诉模型目标切片个数。
5) API 校验失败或缺配置时回退到旧规则结果；本地蒸馏失败只跳过蒸馏，不中断最终 API 精排。

## 5) Error Handling
- 缺少 API key、JSON 非法、远端失败时必须回退，不得打断旧管线。
