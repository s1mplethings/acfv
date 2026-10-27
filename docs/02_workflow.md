# 工作流

Phase 2 版本同时记录“当前正式 workflow”与“后续 Phase 3 之前不应越界的部分”。

## 1. 当前 Workflow

### 1.1 CLI 当前 workflow
1. `acfv pipe clip --url ... --out-dir ...`
2. `acfv.cli.pipeline.clip` 解析 YAML / CLI 参数
3. 如指定 `--dry-run-plan`，直接输出 `pipeline/stages.py` 中的统一 stage plan
4. 否则创建 `run_dir`
5. 调用 `backend.service.create_job(...)`
6. `backend.job_manager` 在统一 job backend 中执行任务
7. `pipeline.orchestrator.run_clip_pipeline(...)` 先执行 `ingest_video`
8. 然后调用 `modular.pipeline.run_pipeline(...)`
9. `modular` 内部基于 goal artifact `ART_CLIPS` 推导执行计划
10. 产出 clips / manifest / segments / transcript 等结果

### 1.2 GUI 当前 workflow
1. 用户在 GUI 选择本地回放或下载结果
2. `MainWindow` / `LocalVideoManager` 创建输出目录
   - 通常是 `clips/<video>/runs/run_<nnn>/`
3. GUI 用 `ThreadSafeWorker` 只做轻量 job 提交准备
4. `LocalVideoManager` 通过 `GuiJobController` 调 `backend.service.create_job(...)`
5. `backend.job_manager` 内部调用 `pipeline.orchestrator.run_clip_pipeline(...)`
6. orchestrator 写出 `work/stage_plan.json`，并完成 `ingest_video`
7. GUI 定时轮询 `get_job_status(...)` 与 `get_runtime_state(...)`
8. GUI 直接显示 canonical stage、runtime 摘要、错误摘要、日志入口和结果目录入口

### 1.3 当前正式单主线
当前 clip pipeline 已显式收敛为固定 stages：
1. `ingest_video`
2. `extract_audio`
3. `build_audio_chunk_manifest`
4. `transcribe_chunks`
5. `merge_transcript`
6. `optional_analysis`
7. `select_segments`
8. `build_clip_manifest`
9. `render_clips_batch`
10. `export_results`

如果有 chat source，`extract_chat` 会先补出 `ART_CHAT_LOG`；如果没有，则 pipeline 直接种入空 chat log payload。

### 1.4 Stage -> Step(s) 映射
1. `ingest_video`
   - `pipeline.orchestrator.run_clip_pipeline`
   - 负责 `fetch_vod(...)` / 本地路径解析
2. `extract_audio`
   - `modular.plugins.extract_audio`
3. `build_audio_chunk_manifest`
   - `modular.plugins.transcribe_audio`
   - 当前输出 `work/audio_chunk_manifest.json`
4. `transcribe_chunks`
   - `modular.plugins.transcribe_audio`
   - 当前已按 chunk 作为独立执行单元调度
   - 通过 `gpu_asr_pool` 执行；单 GPU 默认 `max_workers=1`
   - 2.1.0 起 `io_pool` 会预取/切片下一批 chunk，单 GPU ASR worker 连续消费已准备好的 chunk
5. `merge_transcript`
   - `modular.plugins.transcribe_audio`
   - 当前输出 `work/transcript_merged.json`
   - chunk 完成后允许先写局部 transcript 并记录 incremental merge 事件；最终完整 `transcript_merged.json` 仍在汇总阶段产出
6. `optional_analysis`
   - `screen_detect`
   - `screen_understanding`
   - `video_emotion`
   - `speaker_separation`
   - `streamer_subtitles`
   - `subtitle_translate`
   - `analyze_segments`
   - `semantic_merge`
   - `llm_highlight`
7. `select_segments`
   - `modular.plugins.render_clips`
   - 当前输出 `work/selected_segments.json`
8. `build_clip_manifest`
   - `modular.plugins.render_clips`
   - 当前输出 `work/clip_manifest.json`
9. `render_clips_batch`
   - `modular.plugins.render_clips`
   - 当前已按 clip 作为独立执行单元调度
   - 通过 `render_pool` 执行；并发度由 `render_pool.max_workers` 控制
   - 当前 runtime state 输出 `work/runtime/render_runtime.json`
   - 2.1.0 起可消费 streaming fast path 已准备好的 clip work item；最终 stage 会复用已存在输出并完成完整 manifest/export 汇总
10. `export_results`
   - `modular.plugins.render_clips`
   - 当前输出 `work/export_results.json` 与最终 `clips_manifest.json`

## 2. 当前 Workflow 的问题
- GUI 和 CLI 已共享统一 job API 与统一 stage source
- `audio_chunk_manifest` 与 `clip_manifest` 已固定为 plan input，且不再承载执行态
- Phase 3 已将执行态分离到 `work/runtime/`
- 现在已有 chunk 级 / clip 级 runtime 状态对象
- 已有阶段内并发配置入口：
  - `gpu_asr_pool.max_workers`
  - `render_pool.max_workers`
- `cancel_job(...)` 当前仍是 best-effort，只能作为统一 job API 的兼容能力，不能视为 Phase 3 chunk/clip 级取消语义的既成基础
- 2.1.0 已将执行顺序从纯 stage barrier 改为 streaming window：
  - canonical stage 名称与最终 contract 输出不变
  - fast path 可以在 chunk 完成窗口后提前推进到 coarse selection 与 render
  - enrich path 不再阻塞早期 clip work item 入队
  - `work/runtime/events.jsonl` 记录细粒度事件，summary JSON 周期刷新
  - fast path 生成的 clip work item 现在按归一化时间窗建立稳定 identity；重复 chunk callback 或重复窗口扫描只记录 dedup 事件，不再重复入队 render

## 3. 目标 Workflow

当前正式主线已经统一为：

1. `ingest_video`
2. `extract_audio`
3. `build_audio_chunk_manifest`
4. `transcribe_chunks`
5. `merge_transcript`
6. `optional_analysis`
7. `select_segments`
8. `build_clip_manifest`
9. `render_clips_batch`
10. `export_results`

## 4. 目标阶段说明

### 4.1 `ingest_video`
- 输入:
  - URL 或本地视频路径
- 输出 artifact:
  - video source
  - optional chat source/log
- 兼容要求:
  - 保留现有 Twitch / 本地文件入口

### 4.2 `extract_audio`
- 输入:
  - ingest 后的视频 artifact
- 输出 artifact:
  - extracted audio
  - media meta
- 兼容要求:
  - 保留现有 ffmpeg 抽音频策略和输出风格

### 4.3 `build_audio_chunk_manifest`
- 输入:
  - extracted audio
- 输出 artifact:
  - `audio_chunk_manifest`
- 说明:
  - Phase 2 当前最小输出为 `work/audio_chunk_manifest.json`
  - 当前先描述 chunk 顺序、时间范围、状态
  - Phase 3 再让它真正承担并发执行输入

### 4.4 `transcribe_chunks`
- 输入:
  - `audio_chunk_manifest`
- 输出 artifact:
  - chunk transcript results
- 说明:
  - 当前语义已经固定
  - `work/runtime/transcribe_runtime.json` 现在既是执行态落盘，也是 chunk dispatcher 的状态来源之一
  - 每个 chunk 都会经历 queued/running/succeeded/failed/cancelled 的真实流转
  - 单 GPU 默认仍保守串行，不允许多个 ASR 任务粗暴抢同一 GPU
  - 单 GPU worker 应持续消费队列；音频切片、结果落盘和局部整理由 IO/CPU 轻任务协同，避免 GPU 被非 ASR 工作频繁阻塞

### 4.5 `merge_transcript`
- 输入:
  - chunk transcript results
- 输出 artifact:
  - merged transcript contract
- 兼容要求:
  - 保持现有 transcript / subtitle 相关下游可继续消费
  - 当前最小输出为 `work/transcript_merged.json`

### 4.6 `optional_analysis`
- 输入:
  - transcript
  - chat
  - optional screen context
  - optional video emotion
- 输出 artifact:
  - candidate segments / semantic segments / llm reranked segments
- 说明:
  - 这一层内部继续沿用现有 modular plugins
  - 对 job_state 先只暴露一个总阶段，避免 GUI/CLI 再维护一套子阶段表
  - 其中 `screen_detect` / `screen_understanding` / `video_emotion` / `speaker_separation` / `subtitle_translate` / `llm_highlight` / `analyze_segments` 都属于 optional_analysis 边界
  - 2.1.0 起 optional analysis 是 enrich path；fast path 只依赖局部 transcript 生成粗选和早期 render work item

### 4.7 `select_segments`
- 输入:
  - optional analysis outputs
- 输出 artifact:
  - selected highlight segments
- 兼容要求:
  - 保持当前 segments contract、排序与命名策略
  - 当前最小输出为 `work/selected_segments.json`

### 4.8 `build_clip_manifest`
- 输入:
  - selected segments
  - source media
- 输出 artifact:
  - `clip_manifest`
- 说明:
  - 当前最小输出为 `work/clip_manifest.json`
  - Phase 3 Step 1 起它正式作为 `render_clips_batch` 的 plan input
  - streaming fast path 只通过 runtime event 表达临时 clip work item，不把这些执行态写入最终 `clip_manifest.json`

### 4.9 `render_clips_batch`
- 输入:
  - `clip_manifest`
- 输出 artifact:
  - rendered clip files
  - subtitles
  - thumbnails
  - per-clip render status
- 说明:
  - `work/runtime/render_runtime.json` 现在既是执行态落盘，也是 clip dispatcher 的状态来源之一
  - 每个 clip 都会经历 queued/running/succeeded/failed/cancelled 的真实流转
  - `render_pool` 已支持最小可用的 clip 级并发
  - render worker 可以在最终 `clip_manifest.json` 完成前消费 streaming work item；最终阶段仍以完整 plan 为准，复用已存在输出或补渲染缺失项

### 4.10 `export_results`
- 输入:
  - render batch outputs
  - run metadata
- 输出 artifact:
  - final manifest
  - result summary
  - stable run directory view
  - 当前最小输出为 `work/export_results.json`

## 5. 当前到目标的映射关系

| 当前模块/步骤 | 目标阶段 | 备注 |
| --- | --- | --- |
| `fetch_vod` / 本地文件解析 | `ingest_video` | 继续保留 |
| `modular.plugins.extract_audio` | `extract_audio` | 已存在 |
| `steps/transcribe_audio/impl.py` | `build_audio_chunk_manifest` + `transcribe_chunks` + `merge_transcript` | 需要拆 stage，不一定拆入口 |
| `analyze_segments` / `semantic_merge` / `llm_highlight` / `screen_*` / `video_emotion` | `optional_analysis` | 保持 modular plugins 思路 |
| `render_clips` | `build_clip_manifest` + `render_clips_batch` | 先显式化 manifest，再做阶段内并发 |
| contract output 汇总 | `export_results` | 维持现有输出契约 |

## 6. 并发策略

### 当前
- 主要是 GUI worker 级后台执行
- step 内部可能各自开线程
- 没有稳定资源池 contract

### 目标
- 只做阶段内并发，不重写成全局 DAG scheduler
- 第一优先级:
  - 音频 chunk 化转录
  - clip manifest 化渲染
  - 资源池拆分
- 资源池目标:
  - `io_pool`
  - `gpu_asr_pool`
  - `cpu_pool`
  - `render_pool`

### 2.1.0 streaming window
- fast path:
  - `extract_audio -> build_audio_chunk_manifest -> transcribe_chunks -> incremental merge -> coarse segment -> clip work item -> render_pool`
- enrich path:
  - screen / emotion / speaker / subtitle / LLM 等增强分析继续归入 `optional_analysis`，可补充最终排序或元数据，但不阻塞 fast path。
- runtime:
  - item 生命周期先进入 `work/runtime/events.jsonl`
  - `transcribe_runtime.json` / `render_runtime.json` 是周期摘要，finalize 时强制刷新，供 GUI/backend 稳定读取
  - 同一逻辑窗口再次出现时写 `clip_work_item_deduplicated` / `render_enqueue_skipped_duplicate`，而不是创建新的 clip_id 去重复渲染

## 7. GUI / CLI 的共同 workflow 约束
- GUI 和 CLI 已经走同一 backend service
- backend service 再去调用同一套 pipeline/orchestrator
- GUI / CLI / legacy compat 看到的 stage 语义统一来自 `src/acfv/pipeline/stages.py`
- GUI 不再直接等待或编排核心业务主线
- CLI 不再直接拼接独立 orchestration 逻辑
- runtime state 只允许新增到 `work/runtime/`，不得回写污染现有 6 个 contract artifact

## 8. Phase 1 兼容策略
- `acfv.cli.pipeline` 保留为 CLI 兼容适配层
- `LocalVideoManager` 保留为 GUI 兼容适配层
- `features.modules.pipeline_backend.run_pipeline(...)` 保留为 deprecated compat wrapper，但其核心执行已统一转发到 `backend.service`

## 9. Phase 2 结论
- Phase 2 解决的是“主线阶段定义隐式”这个问题
- 当前已经有统一主线、统一 stage 语义、统一最小 artifact contract
- Phase 2 hardening 又补上了 6 个 contract artifact 的一致性验证与 stage->plugin 映射说明
- 后续 Phase 3 必须只在这条显式主线上补阶段内并发，不得跳回去做第二套 orchestration

## 10. Phase 3 Step 2 结论
- 当前已经把 chunk / clip 作为真实阶段内执行单元接入调度
- canonical 10-stage 主线、orchestrator 入口、contract artifact 语义都保持不变
- 下一子步只应继续增强 retry / cancel / 多 GPU 等局部能力，不应回头改主线定义

## 11. Phase 4 结论
- GUI 当前已经作为 backend 的控制台与观察面板工作
- 当前阶段来自 `job_state.current_stage`
- transcribe/render 细粒度摘要来自 `get_runtime_state(...)`
- GUI 不再通过 progress callback 或本地 stage 表去猜当前主线阶段

## 12. Phase 5 结论
- verify / regression / compatibility 回归已完成
- CLI 正式入口仍可用:
  - `python -m acfv.cli --help`
  - `python -m acfv.cli gui --help`
  - `python -m acfv.cli pipe clip --help`
  - `python -m acfv.cli pipe clip --url demo --dry-run-plan`
- GUI 入口链路仍成立:
  - GUI 创建任务 -> `backend.service.create_job(...)`
  - GUI 轮询 -> `get_job_status(...)` + `get_runtime_state(...)`
  - GUI 取消 -> `cancel_job(...)`
  - GUI 日志 / 结果目录入口继续可用
- contract / runtime 边界仍成立:
  - `stage_plan.json`、`audio_chunk_manifest.json`、`transcript_merged.json`、`selected_segments.json`、`clip_manifest.json`、`export_results.json` 保持契约/摘要职责
  - `work/runtime/transcribe_runtime.json`、`work/runtime/render_runtime.json` 保持执行态职责

## 13. Benchmark / Regression Workflow
1. 先跑基础回归：
   - `powershell -ExecutionPolicy Bypass -File scripts\verify.ps1`
2. 准备 short / medium / long 输入集，记录固定视频路径和 cfg。
3. 跑 benchmark：
   - `python scripts\benchmark_streaming.py run --case-id short_smoke --input-video <video> --config <cfg> --repeat 1 --preflight smoke`
4. 查看输出：
   - `var/benchmarks/<run_id>/results.json`
   - `var/benchmarks/<run_id>/timeline.json`
   - `var/benchmarks/<run_id>/report.md`
5. 判断 streaming 是否生效：
   - `first_clip_before_all_transcribe_done == true`
   - `incremental_merge_done` 与 `clip_work_item_queued` 出现在 timeline
   - `contract_clean == true`
   - `runtime_separate == true`
6. GUI smoke：
   - `python -m pytest -q tests\unit\test_gui_job_controller.py`
   - GUI 专项以 controller/adapter 层验证为主，不要求引入沉重 GUI 自动化框架。
