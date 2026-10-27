# Streamer Subtitles Spec

## 1) Purpose
- 负责：从转写与说话人分段中生成“仅主播”的字幕文件（SRT/ASS）。
- 不负责：转写本身、切片渲染、视频烧录。

## 2) Inputs
- `work/transcription.json`：转写段或词级时间戳。
- `work/speaker_separation/speaker_separation_result.json`：说话人分段与 `host_speaker`。
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- `work/subtitles_streamer.srt`
- `work/subtitles_streamer.ass`
- `work/subtitles_streamer.debug.json`（可选排障信息）
- 详细字段：见 `contract_output.md`。

## 4) Process
1) 读取转写与说话人分段。
2) 识别主播（优先 `host_speaker`，否则按时长最大）。
3) 过滤出主播词流并重新切分字幕段。
4) 进行轻量时间对齐（lead-in/out）。
5) 写出 SRT/ASS 与 debug。

## 5) Configuration
- `ENABLE_STREAMER_SUBTITLES`：是否启用。
- `STREAMER_PRIMARY_SPEAKER`：指定主播 ID（覆盖自动识别）。
- `STREAMER_SUB_MAX_CHARS`：每行最大字符数。
- `STREAMER_SUB_MAX_LINES`：最大行数。
- `STREAMER_SUB_TARGET_DUR`：目标字幕时长。
- `STREAMER_SUB_MIN_DUR` / `STREAMER_SUB_MAX_DUR`：最短/最长字幕时长。
- `STREAMER_SUB_PAUSE_SPLIT`：词间隔切分阈值（秒）。

## 6) Error Handling
- 转写或说话人分段缺失：返回状态 `missing_*` 并记录日志。
- 无主播可用：返回 `missing_primary_speaker`。

## 7) Edge Cases
- 词级时间戳缺失：退化为按段内均分时间。
- 过短字幕：合并或跳过，保证单调时序。

## 8) Acceptance Criteria
- 产物存在：SRT/ASS 均写出。
- 时间单调：start < end 且不倒退。
- 仅主播：字幕词流来自主播分段。

## 9) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
