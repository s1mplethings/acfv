# Unified Pipeline Refactor Spec

## Purpose
- 为本轮改造提供唯一顶层约束，目标是在保留现有 `modular.pipeline` / registry / plugin / artifact store 的前提下，逐步收敛为“单主线 pipeline + GUI/后端完全分离 + 支持阶段内并发”的结构。
- 该 spec 约束的是后续 Phase 1~5 的架构收敛方向，不要求 Phase 0 直接改业务逻辑。

## Scope
- 统一 GUI 与 CLI 的 backend service 边界
- 显式化 clip 长视频单主线 stages
- 引入 job lifecycle 与 artifact 查询接口
- 在不重写全局 DAG 的前提下，为转录和渲染准备阶段内并发模型
- 约束进度、错误、输出、兼容层的设计方向

## Phase 1 Baseline
- 已实现统一 backend 边界：
  - `src/acfv/backend/service.py`
  - `src/acfv/backend/job_manager.py`
  - `src/acfv/backend/job_state.py`
- 当前正式调用关系：
  - GUI compat adapter -> backend service -> modular pipeline
  - CLI compat adapter -> backend service -> modular pipeline
- 遗留 `features.modules.pipeline_backend.run_pipeline(...)` 只能作为 compat wrapper 存在，不得继续发展为第二套 backend 主线

## Phase 2 Baseline
- 已实现 clip pipeline 的单一 stage source：
  - `src/acfv/pipeline/stages.py`
  - `src/acfv/pipeline/orchestrator.py`
- 当前正式主线固定为：
  - `ingest_video`
  - `extract_audio`
  - `build_audio_chunk_manifest`
  - `transcribe_chunks`
  - `merge_transcript`
  - `optional_analysis`
  - `select_segments`
  - `build_clip_manifest`
  - `render_clips_batch`
  - `export_results`
- `backend.job_manager`、CLI dry-run 与 legacy compat path 都必须复用同一份 stage 语义
- `specs/modules/unified_pipeline/contract_output.md` 作为 Phase 2 hardening 后的唯一 contract 输出说明

## Phase 3 Step 1 Baseline
- 只在 `transcribe_chunks` 与 `render_clips_batch` 两个 canonical stage 内引入执行态。
- `audio_chunk_manifest.json` 明确作为 `transcribe_chunks` 的 plan input。
- `clip_manifest.json` 明确作为 `render_clips_batch` 的 plan input。
- 执行态单独写入：
  - `work/runtime/transcribe_runtime.json`
  - `work/runtime/render_runtime.json`
- 现有 6 个 contract artifact 继续保持契约/摘要职责，不得承载 `attempt`、`worker_id`、`running` 等执行态字段。

## Phase 3 Step 2 Baseline
- `transcribe_chunks` 现在必须真实按 `audio_chunk_manifest.json` 的 chunk items 调度执行。
- `render_clips_batch` 现在必须真实按 `clip_manifest.json` 的 clip items 调度执行。
- `gpu_asr_pool` 与 `render_pool` 已从字段边界升级为最小可用的 stage-local dispatcher。
- `gpu_asr_pool.max_workers` 与 `render_pool.max_workers` 进入现有配置体系。
- 外层阶段切换仍由 `orchestrator` / `backend service` / `job_manager` 驱动，不得引入第二套主线或全局 DAG。

## 2.1.0 Streaming Window Baseline
- canonical 10-stage 名称、顺序和最终 contract 语义不变。
- 执行模型允许在阶段内部滑动窗口推进：chunk 完成后可先做局部 transcript merge、粗选 segment、clip work item 入队和 render 消费。
- `optional_analysis` 是 enrich path，不得重新成为 fast path 的关键阻塞点。
- 单 GPU 默认仍只允许一个 ASR worker；吞吐提升来自 `io_pool` 预取/切片、GPU 连续消费、CPU 轻量整理，而不是粗暴多开 ASR 抢同一 GPU。
- runtime state 采用事件流 + 周期摘要：
  - `work/runtime/events.jsonl` 记录细粒度 item lifecycle / streaming window / clip work item 事件
  - `work/runtime/transcribe_runtime.json` 与 `work/runtime/render_runtime.json` 保持 GUI/backend 可轮询摘要
  - finalize 必须强制刷新 summary JSON

## Phase 4 Baseline
- GUI 任务创建继续统一走 `backend.service.create_job(...)`。
- GUI 当前阶段必须直接显示 `job_state.current_stage`，不得维护第二套 stage 表。
- GUI 在 `transcribe_chunks` / `render_clips_batch` 阶段必须直接读取 runtime state 摘要，而不是反向解释 contract artifact。
- `LocalVideoManager` 可以保留为 GUI compat adapter，但职责必须收敛为：
  - 调 backend service
  - 轮询 job state / runtime state
  - 发出 UI 更新信号
  - 提供取消 / 日志 / 结果目录入口

## Non-goals
- 不推倒重写 `modular.pipeline`
- 不删除现有 GUI / CLI 入口
- 不在本轮引入新的云服务依赖
- 不修改既有输出目录契约
- 不在 Phase 0 直接实现全局 DAG scheduler

## Inputs
| 字段/文件 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| `job_request.input_url_or_path` | string | 是 | Twitch VOD URL 或本地视频路径 | `https://www.twitch.tv/videos/123` |
| `job_request.mode` | string | 是 | 初期固定为 clip pipeline | `clip` |
| `job_request.cfg_path` | string | 否 | 指向 YAML/config 覆盖 | `var/settings/pipeline.yaml` |
| `job_request.output_root` | string | 否 | 不得破坏现有默认路径行为 | `runs/out` |
| `job_request.gui_context` | object | 否 | GUI 仅传展示/交互相关上下文，不传业务线程对象 | `{ "source": "gui" }` |

## Outputs
| 字段/文件 | 类型 | 必填 | 约束 | 示例 |
| --- | --- | --- | --- | --- |
| `job_id` | string | 是 | 全局唯一，可映射 run 目录 | `run_20260409_120000` |
| `job_status` | object | 是 | 包含阶段、状态、错误摘要、进度摘要 | `{ "stage": "transcribe_chunks", "status": "running" }` |
| `artifacts` | list | 是 | 可列出 run 级 artifact 与关键结果 | `["work/transcription.json", "work/clips_manifest.json"]` |
| `result_summary` | object | 否 | 完成后返回 clips / manifest / output dir 摘要 | `{ "clips": 3 }` |
| `logs` | list/string | 否 | 可按 job 查询 | `["[progress] ..."]` |

## Stages
| Stage | Required | 输入 | 输出 | 说明 |
| --- | --- | --- | --- | --- |
| `ingest_video` | 是 | URL / 本地路径 | video source, optional chat source | 保留现有 Twitch / local 入口 |
| `extract_audio` | 是 | video source | extracted audio, media meta | 保留现有 ffmpeg 抽音频 |
| `build_audio_chunk_manifest` | 是 | extracted audio | audio chunk manifest | Phase 3 显式化 |
| `transcribe_chunks` | 是 | chunk manifest | chunk transcripts | 默认单 GPU 串行 ASR |
| `merge_transcript` | 是 | chunk transcripts | merged transcript | 保持下游兼容 |
| `optional_analysis` | 否 | transcript, chat, screen, emotion | candidate/semantic/llm segments | 继续复用 modular plugins |
| `select_segments` | 是 | analysis outputs | selected segments | 输出契约保持稳定 |
| `build_clip_manifest` | 是 | selected segments, media | clip manifest | Phase 3 显式化 |
| `render_clips_batch` | 是 | clip manifest | rendered clips batch | clip 级并发 |
| `export_results` | 是 | batch outputs | result summary, final manifests | 汇总导出 |

## Config
- GUI 与 CLI 共享同一配置事实源；新接口不能引入第二套平行配置模型。
- 并发相关配置进入现有配置体系，当前至少包括：
  - `gpu_asr_pool.max_workers`
  - `render_pool.max_workers`
- 单 GPU 默认 `gpu_asr_pool.max_workers = 1`，避免多个 ASR 任务同时争抢同一 GPU。
- backend service 允许接收 GUI/CLI 请求，但不能依赖 GUI widget 或 `QThread` 对象。
- Phase 3 当前边界：
  - `io_pool`
  - `gpu_asr_pool`
  - `cpu_pool`
  - `render_pool`
- 2.1.0 当前要求：
  - `io_pool` 真实承担 audio chunk 预取/切片
  - `gpu_asr_pool` 单 GPU worker 连续消费 chunk queue
  - `cpu_pool` 以插件层 incremental merge / coarse selection / 结果整理表达，后续可抽象为独立执行器
  - `render_pool` 可消费 streaming work item，并在最终 render stage 复用已存在输出

## Artifact Contract
- 保留现有 `ArtifactStore`、`work/`、`clips_manifest.json`、`segments.json`、`transcription.json` 风格。
- 新增显式 artifact 时，优先补以下契约：
  - `audio_chunk_manifest`
  - `chunk_transcript_results`
  - `clip_manifest`
  - `render_batch_status`
- 所有阶段产物继续遵循：
  - 可回溯
  - 有稳定 schema/version
  - 可由 GUI 和 CLI 共同消费
- Phase 2 最小 contract 文件：
  - `work/stage_plan.json`
  - `work/audio_chunk_manifest.json`
  - `work/transcript_merged.json`
  - `work/selected_segments.json`
  - `work/clip_manifest.json`
  - `work/export_results.json`
- Phase 2 hardening：
  - `audio_chunk_manifest.json` 受 `specs/contract_output/audio_chunk_manifest.schema.json` 约束
  - `clip_manifest.json` 受 `specs/contract_output/clip_manifest.schema.json` 约束
  - 六个 contract 文件之间必须存在路径和数量上的一致性验证
- Phase 2 说明：
  - 这些文件先承担“主线显式化”和“统一产物摘要”职责
  - 还不承担 Phase 3 的并发调度职责
- Phase 3 Step 1 说明：
  - `audio_chunk_manifest.json` 与 `clip_manifest.json` 升级为 plan input，但仍保持静态计划文件语义
  - runtime state 固定在 `work/runtime/`
  - `transcribe_runtime.json` / `render_runtime.json` 只描述阶段内 item 生命周期，不新增 canonical stage
- Phase 3 Step 2 说明：
  - runtime state 不只是被动记录，而是阶段内 dispatcher 的执行态来源之一
  - `transcribe_chunks` 不再要求所有 chunk 完成后才允许局部 `merge_transcript` 语义工作；最终完整 `transcript_merged.json` 仍必须等所有 chunk 汇总后写出
  - `render_clips_batch` 可提前消费 streaming work item；最终 `clips_manifest.json` / `export_results.json` 仍必须等完整 render plan 汇总后写出
  - `clip_manifest.json` 不得写入 running/worker/attempt 等执行态字段

## Compatibility
- 兼容现有入口：
  - `acfv gui`
  - `acfv pipe clip`
- 兼容现有输出目录习惯：
  - CLI 默认 `runs/out/...`
  - GUI 现有 `clips/<video>/runs/run_xxx/...`
- 兼容现有 modular plugin/step 实现：
  - 优先新增 service / orchestrator / adapter 层
  - 不直接删除旧 import path
- 兼容遗留 backend 导入路径：
  - `features.modules.pipeline_backend.run_pipeline(...)` 保留可调用
  - 但核心执行必须统一转发到 `backend.service`
- 兼容 v1.1.0 行为基线：
  - 不破坏 GUI / CLI 基本行为
  - 不破坏已有 manifest / clips / transcript 输出习惯
- 兼容现有 optional analysis 插件族：
  - `screen_detect`
  - `screen_understanding`
  - `video_emotion`
  - `speaker_separation`
  - `streamer_subtitles`
  - `subtitle_translate`
  - `analyze_segments`
  - `semantic_merge`
  - `llm_highlight`
  - 对外统一归入 `optional_analysis`
- 兼容当前取消语义：
  - `cancel_job(...)` 仍是 best-effort
  - 不能把当前状态模型误当成复杂 chunk/clip 级取消基础

## Acceptance Criteria
- AC-1 Backend Boundary
  - Given GUI 和 CLI 都要触发 clip pipeline
  - When Phase 1 完成
  - Then 二者都通过同一 backend service 创建任务，而不是各自直接编排主线
- AC-1a Legacy Backend Compatibility
  - Given 旧导入路径仍可能被调用
  - When 调用 `features.modules.pipeline_backend.run_pipeline(...)`
  - Then 它只能作为兼容转发壳存在，核心执行统一走 backend service
- AC-2 Unified Mainline
  - Given 任一正式入口创建 clip 任务
  - When Phase 2 完成
  - Then 后端能显式报告当前处于统一 stage list 中的哪个阶段
- AC-2a Single Stage Source
  - Given GUI、CLI、backend service、legacy compat path 都需要理解阶段语义
  - When 查询或打印 stage plan
  - Then 它们必须来自同一份 `pipeline/stages.py` 定义，而不是各自维护阶段表
- AC-2b Stage Contract
  - Given clip pipeline 完成
  - When 查看 run_dir/work
  - Then 至少能看到 `stage_plan.json` 和最小的 transcript/segment/clip/export contract 文件
- AC-3 Stage-local Concurrency
  - Given 长视频转录和多片段渲染
  - When Phase 3 完成
  - Then 后端使用显式 chunk/clip manifest 与资源池执行阶段内并发，而不是全局 DAG 重写
- AC-3a Streaming Window
  - Given 长视频 ASR chunk 逐个完成
  - When 任一窗口达到 chunk/时间阈值
  - Then 系统可以先写局部 transcript、记录 incremental merge 事件、生成 coarse clip work item，并让 `render_pool` 消费，不必等待全部 chunks 完成
  - And streaming clip work item 必须基于归一化窗口 identity 去重；同一逻辑窗口重复扫描时最多只允许一个 render work item 存活
- AC-3b Runtime Event Stream
  - Given chunk/clip item 生命周期发生变化
  - When dispatcher 更新执行态
  - Then 先追加 `work/runtime/events.jsonl`，summary JSON 周期刷新且 finalize 强制刷新；contract artifact 不包含执行态字段
  - And 对相同 item 的重复成功/运行更新按幂等处理，不重复膨胀 event/runtime summary
- AC-4 GUI Separation
  - Given GUI 发起任务
  - When Phase 4 完成
  - Then GUI 只负责输入、任务提交、状态展示、取消和结果查看，不再直接承载核心 pipeline 生命周期
- AC-5 Compatibility
  - Given 现有 GUI / CLI 入口与输出目录契约
  - When Phase 5 回归完成
  - Then verify 通过，兼容层仍有效，输出契约未被破坏

## Phase Notes
- Phase 0：只做审计与文档/spec 落图，不改业务逻辑
- Phase 1：建立 backend service + job manager 边界，已落地
- Phase 2：显式化单主线 stages
- Phase 2：显式化单主线 stages，已落地
- Phase 3：引入 chunk / clip manifest 与阶段内并发
- Phase 4：GUI 收敛为真正前端
- Phase 5：做 verify / regression / compatibility 回归，确认入口、compat wrapper、contract/runtime 分离和阶段内调度均未被破坏

## Phase 5 Regression Notes
- 已确认:
  - CLI / GUI / legacy compat 都继续统一经由 `backend.service`
  - `features.modules.pipeline_backend.run_pipeline(...)` 仍仅作为 compat wrapper
  - `clip_manifest.json` 未被执行态覆盖
  - `export_results.json` 仍只承担阶段完成后的摘要职责
  - `transcribe_chunks` 仍按 chunk 调度，`render_clips_batch` 仍按 clip 调度
- 已知未完成项:
  - 更强取消
  - 有限 retry
  - 多 GPU ASR
  - `cpu_pool` 独立配置化执行器
  - GUI 更丰富的 chunk / clip 可视化

## 2.1.0 Streaming Notes
- 已确认:
  - `transcribe_audio` 子进程内部按 `split_duration` 使用 `io_pool` 预取 chunk，单 GPU worker 连续转写。
  - chunk 成功后立即写 `work/chunks/<chunk_id>/transcript.json`，父插件可基于 result path 做 streaming window。
  - streaming fast path 的 clip work item 只进入 runtime event / render runtime，不污染 `clip_manifest.json`。
  - streaming fast path 先在 work-item 生成处基于归一化 `(start_ms,end_ms)` 去重，再在 render submit 前做第二层保护；重复候选写 `clip_work_item_deduplicated` / `render_enqueue_skipped_duplicate` 事件。
  - 最终 `render_clips` stage 会复用已存在 clip 输出并补渲染缺失项，再写完整 `clips_manifest.json` 与 `export_results.json`。
- 已知未完成项:
  - 多 GPU 分片调度
  - 有限 retry / backoff 策略
  - 更强取消与 render queue drain 语义
  - GUI 消费 `events.jsonl` 的细粒度可视化

## 2.1.0 Validation / Benchmark Baseline
- 必须提供可重复 benchmark harness，而不是只依赖人工读日志。
- 标准输出目录：
  - `var/benchmarks/<run_id>/meta.json`
  - `var/benchmarks/<run_id>/results.json`
  - `var/benchmarks/<run_id>/timeline.json`
  - `var/benchmarks/<run_id>/report.md`
- `meta.json` 至少记录：
  - commit、Python、OS、CUDA/GPU、ffmpeg、输入视频、输入时长、cfg、输出目录、`gpu_asr_pool.max_workers`、`render_pool.max_workers`
- `results.json` 至少记录：
  - case id、TTFCk、TTFC、TAT、TTR、E2E、contract_clean、runtime_separate、first_clip_before_all_transcribe_done、cancel_ok、render_reuse_ok、notes
- AC-6 Benchmark Harness
  - Given 已有 run_dir 或指定输入视频
  - When 执行 `scripts/benchmark_streaming.py collect/run`
  - Then 生成稳定 JSON/MD 报告，并可自动判断 streaming fast path 是否真实生效
- AC-7 Structure Validation
  - Given 任意 benchmark run_dir
  - When harness 校验 artifact
  - Then `audio_chunk_manifest.json` / `clip_manifest.json` / `export_results.json` 不得出现 runtime-only 字段，`work/runtime/` 不得出现非 runtime 文件

## Replay Regression Hardening Notes
- 回放库真实视频回归确认 `audio_chunk_manifest.json` / `clip_manifest.json` 仍是 plan/contract artifact，执行态继续只写入 `work/runtime/`。
- `transcribe_chunks` 的父进程 runtime 语义保持 chunk 级，但受保护转录子进程应在单个 stage invocation 内按 `split_duration` 处理 chunks，避免每个 chunk 重复冷启动模型。
- 当 `transcribe_chunks` 选择非当前进程的 Python 环境执行 ASR 时，子进程环境必须显式继承该 Python 环境的 DLL 搜索路径，尤其是 Windows conda 环境的 `Library/bin` 与 `torch/lib`；这属于运行环境修复，不改变 ASR artifact contract。
- 当首选 ASR 后端因本机 CUDA/cuDNN 依赖缺失失败时，允许在同一 `transcribe_chunks` 阶段内 fallback 到 `openai-whisper`；fallback 不能改变 canonical stage、contract 文件职责或 runtime 文件位置。
- `selected_segments.json` 与 `clip_manifest.json` 必须来自同一份排序后的 clip plan；两者按 index 的 `start_ms/end_ms` 必须逐项对齐。
- contract validator 必须支持 CLI 相对 `--out-dir` 产生的 CWD-relative artifact 引用；该兼容只影响校验解析，不改变既有输出路径契约。
- Windows 控制台输出包含 emoji 的本地视频路径时，日志应降级替换不可编码字符，不能因为 `UnicodeEncodeError` 中断 pipeline。

## Trace Links
- docs:
  - `docs/repo_map.md`
  - `docs/01_architecture.md`
  - `docs/02_workflow.md`
- code:
  - `src/acfv/modular/pipeline.py`
  - `src/acfv/modular/runner.py`
  - `src/acfv/steps/local_video_manager/impl.py`
  - `src/acfv/main_window.py`
  - `src/acfv/cli/pipeline.py`
