# Unified Pipeline 输出契约

## Canonical Stage -> Plugin Mapping
| Canonical Stage | 执行单元 | 输入摘要 | 输出摘要 | 备注 |
| --- | --- | --- | --- | --- |
| `ingest_video` | `pipeline.orchestrator.run_clip_pipeline` | URL / 本地路径 | resolved video source | 统一 ingest 边界 |
| `extract_audio` | `modular.plugins.extract_audio` | `video_source` | `audio_extracted` | 正式抽音频 |
| `build_audio_chunk_manifest` | `modular.plugins.transcribe_audio` | `audio_extracted` | `audio_chunk_manifest.json` | 稳定 plan input |
| `transcribe_chunks` | `modular.plugins.transcribe_audio` | `audio_chunk_manifest` | chunk transcripts | 当前按 chunk dispatcher 执行；单 GPU 默认 `gpu_asr_pool.max_workers=1` |
| `merge_transcript` | `modular.plugins.transcribe_audio` | chunk transcripts | `transcript_merged.json` | 下游统一读 merged transcript |
| `optional_analysis` | `screen_detect` / `screen_understanding` / `video_emotion` / `speaker_separation` / `streamer_subtitles` / `subtitle_translate` / `analyze_segments` / `semantic_merge` / `llm_highlight` | transcript + optional enrichments | candidate/semantic/llm segments | 对 job_state 只暴露一个总阶段 |
| `select_segments` | `modular.plugins.render_clips` | analysis outputs | `selected_segments.json` | 固定最终选段 |
| `build_clip_manifest` | `modular.plugins.render_clips` | selected segments + media | `clip_manifest.json` | 稳定 plan input |
| `render_clips_batch` | `modular.plugins.render_clips` | clip manifest | rendered clips | 当前按 clip dispatcher 执行；并发度由 `render_pool.max_workers` 控制 |
| `export_results` | `modular.plugins.render_clips` | rendered clips + clip manifest + transcript | `export_results.json` + final manifest | 负责导出汇总 |

## Phase 2 Contract Files

### 1. `work/stage_plan.json`
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 当前版本号 |
| `pipeline` | str | 是 | 固定为 `clip` |
| `input_source` | str | 否 | 原始输入 URL/路径 |
| `stages` | list[object] | 是 | 固定主线阶段列表 |

### 2. `work/audio_chunk_manifest.json`
参考：`specs/contract_output/audio_chunk_manifest.schema.json`

| 字段 | 类型 | 必填 | 约束 / 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `stage` | str | 是 | 固定 `build_audio_chunk_manifest` |
| `audio_path` | str | 是 | 当前 run 实际使用的音频文件 |
| `segment_length_sec` | number | 是 | chunk 规划粒度，必须 > 0 |
| `chunk_count` | int | 是 | 必须等于 `len(chunks)` |
| `chunks[].chunk_id` | str | 是 | 稳定 chunk 标识 |
| `chunks[].index` | int | 是 | 从 0 递增 |
| `chunks[].start_sec` | number | 是 | 起点秒数 |
| `chunks[].end_sec` | number | 是 | 终点秒数，必须 `>= start_sec` |
| `chunks[].status` | str | 是 | 当前固定为稳定计划态，通常为 `planned`；不得写入 runtime 细节 |

### 3. `work/transcript_merged.json`
| 字段 | 类型 | 必填 | 约束 / 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `stage` | str | 是 | 固定 `merge_transcript` |
| `transcript_path` | str | 是 | 原始 `transcription.json` 路径 |
| `audio_chunk_manifest_path` | str | 是 | 必须指向 `audio_chunk_manifest.json` |
| `chunk_count` | int | 是 | 必须与 chunk manifest 对齐 |
| `language` | str | 是 | 当前语言或 `auto` |
| `segments` | list[object] | 是 | 合并后的 transcript 段 |

### 4. `work/selected_segments.json`
| 字段 | 类型 | 必填 | 约束 / 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `units` | str | 是 | 固定 `ms` |
| `sort` | str | 是 | 当前排序策略 |
| `policy` | object | 是 | 选段策略摘要 |
| `segments[].start_ms` | int | 是 | 起点毫秒 |
| `segments[].end_ms` | int | 是 | 终点毫秒 |
| `segments[].score` | number | 是 | 评分 |
| `segments[].rank` | int | 是 | 排序名次 |

### 5. `work/clip_manifest.json`
参考：`specs/contract_output/clip_manifest.schema.json`

| 字段 | 类型 | 必填 | 约束 / 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `stage` | str | 是 | 固定 `build_clip_manifest` |
| `units` | str | 是 | 固定 `ms` |
| `run_id` | str | 是 | 当前 run 标识 |
| `source_media` | str | 是 | 源视频路径 |
| `selected_segments_path` | str | 是 | 必须指向 `selected_segments.json` |
| `naming_policy` | str | 是 | 当前 clip 命名模板 |
| `clip_count` | int | 是 | 必须等于 `len(clips)` |
| `clips[].clip_id` | str | 是 | 稳定 clip 标识 |
| `clips[].rank` | int | 是 | 从 1 递增 |
| `clips[].start_ms/end_ms/duration_ms` | int | 是 | 必须与 selected segments 对齐 |
| `clips[].status` | str | 是 | 当前固定为 `planned`，不写执行态 |
| `clips[].output.video` | str | 是 | 预期导出的视频路径 |

### 6. `work/export_results.json`
| 字段 | 类型 | 必填 | 约束 / 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `stage` | str | 是 | 固定 `export_results` |
| `run_id` | str | 是 | 当前 run 标识 |
| `clip_count` | int | 是 | 成功导出的 clip 数 |
| `planned_clip_count` | int | 是 | 必须与 `clip_manifest.clip_count` 对齐 |
| `selected_segment_count` | int | 是 | 必须与 `selected_segments` 数量对齐 |
| `subtitle_count` | int | 是 | 导出字幕数 |
| `thumbnail_count` | int | 是 | 导出缩略图数 |
| `clips_manifest_path` | str | 是 | 最终 `clips_manifest.json` 路径 |
| `artifact_refs` | object | 是 | 必须反向引用前 5 个 contract 文件 |

## Runtime State Files

### `work/runtime/transcribe_runtime.json`
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `job_id` | str | 是 | 当前 job/run 标识 |
| `stage` | str | 是 | 固定 `transcribe_chunks` |
| `status` | str | 是 | `running/succeeded/failed/cancelled` |
| `total_chunks/completed_chunks/failed_chunks/running_chunks` | int | 是 | 阶段摘要 |
| `pool` | str | 是 | 当前固定 `gpu_asr_pool` |
| `max_workers` | int | 是 | 当前来自 `gpu_asr_pool.max_workers`；单 GPU 默认并实际保持 `1` |
| `updated_at` | str | 是 | UTC 更新时间 |
| `chunks[]` | list | 是 | item 生命周期列表 |

`chunks[]` 最小字段：
- `chunk_id`
- `index`
- `start_sec`
- `end_sec`
- `status`
- `attempt`
- `worker_id`
- `error_summary`
- `started_at`
- `finished_at`
- `result_path`
- `segment_count`

### `work/runtime/render_runtime.json`
| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema_version` | str | 是 | 初始 `1.0.0` |
| `job_id` | str | 是 | 当前 job/run 标识 |
| `stage` | str | 是 | 固定 `render_clips_batch` |
| `status` | str | 是 | `running/succeeded/failed/cancelled` |
| `total_clips/completed_clips/failed_clips/running_clips` | int | 是 | 阶段摘要 |
| `pool` | str | 是 | 当前固定 `render_pool` |
| `max_workers` | int | 是 | 当前来自 `render_pool.max_workers`；默认保守值 `2` |
| `updated_at` | str | 是 | UTC 更新时间 |
| `clips[]` | list | 是 | item 生命周期列表 |

`clips[]` 最小字段：
- `clip_id`
- `rank`
- `start_ms`
- `end_ms`
- `status`
- `attempt`
- `worker_id`
- `error_summary`
- `started_at`
- `finished_at`
- `output_video`
- `subtitle_path`
- `thumbnail_path`

## Consistency Rules
- `stage_plan.json` 的阶段顺序必须与 canonical stage list 完全一致。
- `transcript_merged.audio_chunk_manifest_path` 必须指向同一次 run 的 `audio_chunk_manifest.json`。
- `clip_manifest.selected_segments_path` 必须指向同一次 run 的 `selected_segments.json`。
- `selected_segments` 与 `clip_manifest` 在 Phase 2 中必须一一对应；Phase 3 若引入失败重试/分批渲染，再扩展这一规则。
- `export_results.artifact_refs` 必须反向引用本次 run 的前 5 个 contract 文件。
- `audio_chunk_manifest.json` 与 `clip_manifest.json` 不得写入 `attempt/worker_id/started_at/finished_at` 等执行态字段。
- chunk/clip 的执行态只允许进入 `work/runtime/*.json`。
- runtime state 必须在 item 启动、完成、失败、取消和阶段收口时更新，作为阶段内 dispatcher 的可见执行态。

## Cancellation Note
- `cancel_job(...)` 当前仍是 best-effort。
- 当前的 contract 文件和状态流转不能被视为复杂并发取消语义的完成品。
- Phase 3 如需 chunk/clip 级取消，必须在现有 canonical stage 与 contract 基础上显式扩展，不得反向改写 backend 主线。
