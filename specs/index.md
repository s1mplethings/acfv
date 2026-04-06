# specs/index.md

> 模块 specs 与 input/output 契约的索引（SDDAI / ACFV）

## 模块 specs
- `specs/modules/analyze_segments/spec.md`：分段/评分/选段（切片）规则（边界/排序/空输入策略）
- `specs/modules/semantic_merge/spec.md`：语义合并（文本相似度拼接为目标时长片段）
- `specs/modules/render_clips/spec.md`：剪辑渲染与导出（命名/原子写/manifest）
- `specs/modules/subtitle_generator/spec.md`：字幕生成（SRT/ASS）
- `specs/modules/streamer_subtitles/spec.md`：主播字幕导出（仅主播）
- `specs/modules/subtitle_translate/spec.md`：字幕翻译（上下文块 + 时间轴稳定）

## 输出契约（contract_output）
- `specs/contract_output/segments.schema.json`：候选段列表（segments）JSON Schema
- `specs/contract_output/clips_manifest.schema.json`：剪辑清单（manifest）JSON Schema

## 模板
- `specs/templates/module_spec_template.md`：模块 spec 模板
