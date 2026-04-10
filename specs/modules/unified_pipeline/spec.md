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
- 当前只要求 `gpu_asr_pool` 与 `render_pool` 具备最小可用 dispatcher；`io_pool` / `cpu_pool` 仍是边界约束而非完整调度器

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
  - `transcribe_chunks` 必须等所有 chunk 进入终态后，才进入 `merge_transcript`
  - `render_clips_batch` 必须等所有 clip 进入终态后，才进入 `export_results`

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
  - `io_pool` / `cpu_pool` 执行器
  - GUI 更丰富的 chunk / clip 可视化

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
