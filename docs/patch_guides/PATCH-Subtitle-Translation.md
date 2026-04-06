# PATCH: Subtitle Translation (Context-Aware, Stable Timeline)

目标
- 在现有“主播字幕（细切分 + 时间轴较准）”基础上新增“翻译管线步骤”
- 输出：
  1) `work/streamer.zh.srt`
  2) `work/streamer.zh.ass`
  3) `work/streamer.bilingual.ass`（可选）
  4) `work/translation_cache.jsonl`（缓存）

原则
- 默认不改字幕事件的 start/end（保证时间轴不漂）
- 翻译质量优先使用“上下文块 block 翻译”，不是逐句翻译
- 引擎可插拔：LLM(JSON)、NLLB/Seamless(离线)、Argos(兜底)

--------------------------------
## A. 新增 step：subtitle_translate
--------------------------------
目录（示例命名）：
- `src/acfv/steps/subtitle_translate/`
  - `step.py`：run(cfg, workdir, inputs) -> outputs
  - `blockify.py`：把字幕事件打包成 block
  - `backends/`：翻译引擎适配
  - `writer.py`：写回 SRT/ASS/双语

输入/输出约定
- 输入：主播字幕事件（id/start/end/text）
- 输出：`work/streamer.zh.srt` / `work/streamer.zh.ass` / `work/streamer.bilingual.ass`

--------------------------------
## B. blockify（上下文块打包）
--------------------------------
参数（cfg）：
- `block_max_duration_sec: 10.0`
- `block_max_chars: 350`
- `block_max_gap_sec: 0.60`
- `block_min_items: 2`

算法
- gap<=max_gap 且 时长/字符不超 -> 同 block
- 否则断开新 block

--------------------------------
## C. 翻译输出格式（按 id 回填）
--------------------------------
LLM_JSON 输出：
```
{"items":[{"id":"0001","zh":"..."}, ...]}
```
按 id 回填，保证时间轴不漂。

--------------------------------
## D. 回填与生成文件
--------------------------------
- `streamer.zh.srt` / `streamer.zh.ass`
- `streamer.bilingual.ass`：`EN\N中文`

可选：merge_mode
- `lock_timeline`（默认）
- `merge_contiguous`（同 block 内合并，保持最早/最晚时间）

--------------------------------
## E. 缓存
--------------------------------
- `translation_cache.jsonl`
- key = hash(block_text + engine + target_lang)

--------------------------------
## F. Config
--------------------------------
```
ENABLE_SUBTITLE_TRANSLATE
SUBTITLE_TRANSLATE_ENGINE
SUBTITLE_TRANSLATE_TARGET_LANG
SUBTITLE_TRANSLATE_SOURCE_LANG
SUBTITLE_TRANSLATE_BILINGUAL
SUBTITLE_TRANSLATE_MERGE_MODE
SUBTITLE_TRANSLATE_BLOCK_*
SUBTITLE_TRANSLATE_LLM_*
```

--------------------------------
## G. Pipeline 串接位置
--------------------------------
transcribe -> diarize -> streamer_subtitles -> subtitle_translate -> (burn/render)
