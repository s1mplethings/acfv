# Subtitle Translate Spec

## 1) Purpose
- 负责：将主播字幕按“上下文块”翻译为中文/双语，保持时间轴稳定。
- 不负责：转写/说话人识别、字幕生成、视频烧录。

## 2) Inputs
- `work/subtitles_streamer.ass` 或 `work/subtitles_streamer.srt`
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- `work/streamer.zh.srt`
- `work/streamer.zh.ass`
- `work/streamer.bilingual.ass`（可选）
- `work/translation_cache.jsonl`
- 详细字段：见 `contract_output.md`。

## 4) Process
1) 读取主播字幕并构建事件列表（id/start/end/text）。
2) 根据时长/字符/间隔打包为上下文块。
3) 调用翻译引擎（按 id 回填结果）。
4) 输出中文/双语 SRT/ASS，保留原时间轴。
5) 写入翻译缓存（jsonl）。

## 5) Configuration
- `ENABLE_SUBTITLE_TRANSLATE`
- `SUBTITLE_TRANSLATE_ENGINE`
- `SUBTITLE_TRANSLATE_TARGET_LANG`
- `SUBTITLE_TRANSLATE_SOURCE_LANG`
- `SUBTITLE_TRANSLATE_BILINGUAL`
- `SUBTITLE_TRANSLATE_MERGE_MODE`
- `SUBTITLE_TRANSLATE_BLOCK_*`
- `SUBTITLE_TRANSLATE_LLM_*`

## 6) Error Handling
- 输入字幕缺失：返回 `missing_source`。
- 引擎不可用：抛出明确错误提示。

## 7) Edge Cases
- 字幕为空：返回 `empty`。
- 翻译缺失：回退逐句翻译或保留原文。

## 8) Acceptance Criteria
- 输出文件存在（zh.srt/zh.ass）。
- 时间轴单调且不漂移（默认 lock_timeline）。

## 9) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
