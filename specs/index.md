# specs/index.md

> 模块 specs 与 input/output 契约的索引（SDDAI / ACFV）

## 模块 specs
- `specs/modules/unified_pipeline/spec.md`：本轮改造顶层 spec（单主线 pipeline + GUI/backend 分离 + 阶段内并发）
- `specs/modules/unified_pipeline/contract_output.md`：Phase 2 hardening 后的主线 contract 输出、stage->plugin 映射与取消边界
- `specs/modules/analyze_segments/spec.md`：分段/评分/选段（切片）规则（边界/排序/空输入策略）
- `specs/modules/semantic_merge/spec.md`：语义合并（文本相似度拼接为目标时长片段）
- `specs/modules/screen_detect/spec.md`：机械式电脑画面检测（关键帧、bbox、窗口）
- `specs/modules/screen_understanding/spec.md`：电脑画面理解（关键帧 + 结构化时间轴）
- `specs/modules/llm_highlight/spec.md`：LLM 语义高光精排（结构化 JSON）
- `specs/modules/render_clips/spec.md`：剪辑渲染与导出（命名/原子写/manifest）
- `specs/modules/subtitle_generator/spec.md`：字幕生成（SRT/ASS）
- `specs/modules/streamer_subtitles/spec.md`：主播字幕导出（仅主播）
- `specs/modules/subtitle_translate/spec.md`：字幕翻译（上下文块 + 时间轴稳定）

## 输出契约（contract_output）
- `specs/contract_output/audio_chunk_manifest.schema.json`：音频 chunk manifest JSON Schema
- `specs/contract_output/clip_manifest.schema.json`：clip manifest JSON Schema
- `specs/contract_output/segments.schema.json`：候选段列表（segments）JSON Schema
- `specs/contract_output/clips_manifest.schema.json`：剪辑清单（manifest）JSON Schema

## 模板
- `specs/templates/module_spec_template.md`：模块 spec 模板
