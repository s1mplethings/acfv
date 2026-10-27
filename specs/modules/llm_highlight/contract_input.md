# LLM Highlight 输入契约

- `segments`: 候选段 contract JSON。
- `transcript`: 可选转录片段列表。
- `chat`: 可选弹幕记录。
- `screen_context`: 可选屏幕理解 timeline。
- `video_emotion`: 可选视频情绪时间序列。
- `max_candidates`: 送入 LLM 的最大候选数。
- `LLM_LOCAL_*`: 可选本地 Ollama/OpenAI-compatible 蒸馏配置。
- `LLM_HIGHLIGHT_USER_PREFERENCE_PROMPT`: 用户兴趣提示词，用于让最终 rerank 更贴近偏好。
