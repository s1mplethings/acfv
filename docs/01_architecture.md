# 架构与数据流

Phase 2 目标：在不重写 `modular.pipeline` 的前提下，把 clip 主线显式收敛为统一 stage list，并继续保持 GUI/CLI/legacy backend 共用同一 backend service。

## 1. 当前架构现状

### 1.1 真实入口结构
- GUI:
  - `acfv gui`
  - -> `acfv.cli.gui`
  - -> `acfv.app.gui.launch_gui`
  - -> `acfv.app.interest_adapter.create_interest_main_window`
  - -> `acfv.main_window.MainWindow`
- CLI:
  - `acfv pipe clip`
  - -> `acfv.cli.pipeline.clip`
  - -> `acfv.ingest.twitch.fetch_vod`
  - -> `acfv.modular.pipeline.run_pipeline`

### 1.2 当前真正的 pipeline 核心
- 当前 end-to-end clip 处理的正式核心已经是 `src/acfv/modular/`
  - `pipeline.py` 负责组装 registries、artifact store、progress emitter
  - `runner.py` 负责根据 artifact 依赖执行 plugins
  - `plugins/` 负责接入 `steps/*` 具体实现
- `run_pipeline(...)` 当前 goal artifact 是 `ART_CLIPS`
- pipeline 结果会写出:
  - run 级 artifact store
  - `work/segments.json`
  - `work/transcription.json`
  - `work/clips_manifest.json`
  - contract output summary

### 1.3 Phase 2 已新增的单主线薄层
- `src/acfv/pipeline/stages.py`
  - 作为 clip pipeline 的单一 stage source
  - 定义固定主线 stages、输入/输出 artifact contract 摘要、`optional` 标记、以及 raw progress 到 canonical stage 的映射
- `src/acfv/pipeline/orchestrator.py`
  - 作为统一 orchestrator 入口
  - 负责 `ingest_video`
  - 负责写出 `work/stage_plan.json`
  - 之后继续调用 `modular.pipeline.run_pipeline(...)`
- `backend.job_manager`
  - 现在直接依赖 `pipeline/stages.py`
  - `job_state.current_stage` 由同一份 canonical stage 语义驱动，而不是 GUI/CLI 各自维护一套阶段表

### 1.3a Phase 3 Step 1 新增的执行态层
- `src/acfv/pipeline/runtime.py`
  - 负责 `work/runtime/transcribe_runtime.json`
  - 负责 `work/runtime/render_runtime.json`
  - 只做阶段内 item 生命周期写盘，不改变 canonical stage，也不替代 backend/job manager
- 设计边界：
  - plan input 继续留在 `work/audio_chunk_manifest.json` 与 `work/clip_manifest.json`
  - runtime state 固定分离到 `work/runtime/`
  - `work/runtime/events.jsonl` 记录 item 生命周期、incremental merge、clip work item 入队等细粒度事件
  - `work/runtime/transcribe_runtime.json` / `work/runtime/render_runtime.json` 作为 GUI/backend 可轮询的周期摘要
  - `export_results.json` 仍是摘要，不充当执行态文件
  - streaming fast path 的临时 clip work item 使用归一化窗口 identity `(start_ms,end_ms)` 去重；同一逻辑窗口不会因重复 chunk callback 或重复 merge 扫描而反复入队 render。

### 1.4 GUI 当前与 backend 的关系
- GUI 已开始收敛为前端控制层
- `MainWindow`、`LocalVideoManager`、若干 `QThread` helper 目前仍承担:
  - 任务提交前的轻量准备
  - GUI 适配层级别的轮询/刷新
  - 错误弹窗、日志入口、结果目录入口
  - 部分 run 目录创建
- 现状中最关键的桥接点是 `steps/local_video_manager/impl.py`
  - Phase 1 前它直接调用 `modular.pipeline.run_pipeline`
  - Phase 1 后它改为通过 `acfv.backend.service` 创建 job
  - Phase 4 后它不再等待 job 完成，而是通过 `acfv.app.gui_job_controller.GuiJobController` 轮询统一 job state / runtime state
  - GUI 不再直接拥有 pipeline 调用边界，但仍暂时保留兼容适配线程

### 1.5 仍然存在的遗留 backend
- `src/acfv/features/modules/pipeline_backend.py` 仍保留一套旧式 monolithic backend
- 该文件仍承载历史逻辑:
  - 串行切片
  - 旧进度估算
  - 自动索引辅助能力
- 当前审计结论:
  - 它不是 CLI `pipe clip` 的主线
  - GUI 本地视频主路径也不再通过它执行 job 主线
  - Phase 1 后其 `run_pipeline(...)` 已被降为兼容转发壳，统一转发到 `acfv.backend.service`

## 2. 当前主要耦合问题

### 2.1 Phase 1 已落地的 backend service 边界
- 已新增:
  - `acfv.backend.service`
  - `acfv.backend.job_manager`
  - `acfv.backend.job_state`
- 当前统一接口:
  - `create_job`
  - `get_job_status`
  - `cancel_job`
  - `list_artifacts`
  - `get_logs`
- 结果:
  - GUI 与 CLI 现在共用同一 job/service 边界
  - `modular.pipeline` 继续作为唯一正式 pipeline 核心
  - 仓库内不再保留两套并行 job backend 主路径

### 2.2 Phase 2 后的主线阶段定义
- 当前 `modular.pipeline` 仍是“artifact goal + plugin 依赖”驱动
- 但 Phase 2 已在其上补出一层显式主线定义，固定为：
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
- 这份阶段语义现在是 backend / CLI / GUI compat adapter 的单一来源
- 现状限制:
  - 现有 `transcribe_audio` 与 `render_clips` 仍然是一对多 stage 映射，不是已经拆开的并发执行器
  - optional analysis 仍在 modular 内部展开，但对 job_state 只暴露一个总阶段

### 2.3 GUI 仍有兼容线程，但已经不再承载核心业务主线
- 当前 `QThread` / worker 分散在:
  - `main_window.py`
  - `features/modules/ui_components.py`
  - `steps/local_video_manager/impl.py`
  - `ui/stream_monitor_worker.py`
  - `steps/twitch_downloader/impl.py`
- Phase 4 后 GUI 已不再自己等待 pipeline 完成，也不再维护独立 stage vocabulary
- 仍待后续继续收敛的点:
  - 兼容 QThread 适配层仍存在
  - MainWindow 仍保留较重的历史进度组件

### 2.4 Phase 3 已引入最小阶段内调度，但仍不是全局资源编排
- 当前转录和渲染已经在各自 stage 内使用显式 dispatcher
- 已经有显式的:
  - `gpu_asr_pool`
  - `render_pool`
  - chunk / clip 级状态模型
- Phase 2 已补出的最小契约:
  - `work/audio_chunk_manifest.json`
  - `work/transcript_merged.json`
  - `work/selected_segments.json`
  - `work/clip_manifest.json`
  - `work/export_results.json`
- Phase 3 Step 1 已补出的最小执行态:
  - `work/runtime/transcribe_runtime.json`
  - `work/runtime/render_runtime.json`
- Phase 3 第二子步后，这些执行态文件已经成为 stage-local dispatcher 的真实执行态来源之一
- 仍未引入的能力:
  - 全局 DAG/跨阶段调度
  - 复杂 retry
  - 更强取消
  - 多 GPU 扩展

### 2.5 2.1.0 Streaming Window Execution
- canonical 10-stage 继续作为语义阶段和最终汇总边界，但执行层允许滑动窗口推进。
- `transcribe_chunks` 的 chunk 完成后可立即触发 chunk transcript 落盘、incremental merge 事件、coarse segment selection、clip work item 入队和 `render_pool` 提前消费。
- fast path 先在 `transcribe_audio` 内做窗口级去重，再在 render submit 前做第二层保护；这比继续扩线程更优先，因为重复窗口会直接浪费 render/CPU/IO 并污染 runtime 观察面。
- `merge_transcript`、`select_segments`、`build_clip_manifest`、`export_results` 的最终 contract 输出仍由 canonical 汇总阶段写出，避免 contract artifact 被执行态污染。
- `optional_analysis` 被视为 enrich path。screen、emotion、speaker、subtitle、LLM 等增强仍可参与最终排序/元数据补充，但不再阻塞 fast path 的早期 clip 产出。

## 3. 当前到目标的约束
- 保留现有入口:
  - `acfv gui`
  - `acfv pipe clip`
- 不删除旧导入路径
- 不改输出目录契约
- 不推倒 `modular.pipeline` / registry / artifact store
- GUI 继续优先，但 GUI 不再继续扩展为业务线程容器

## 4. 目标架构草图

### A. GUI Layer
- 负责:
  - 参数输入
  - 任务创建
  - 任务列表 / 当前阶段 / chunk 级进度展示
  - 取消任务
  - 打开结果目录
  - 查看结果摘要 / 错误摘要
- 不负责:
  - 直接跑转录
  - 直接跑渲染
  - 直接编排 pipeline
  - 直接维护核心 worker 生命周期

### B. Backend Service Layer
- 新的统一边界
- 对 GUI / CLI 暴露统一接口:
  - `create_job(...)`
  - `get_job_status(...)`
  - `cancel_job(...)`
  - `list_artifacts(...)`
  - `get_logs(...)`
  - `resume_job(...)`（如适配现有 run 目录）
- 该层负责:
  - job 元数据
  - 生命周期状态机
  - 进度快照
  - 错误汇总
  - 结果查询

### C. Pipeline / Orchestrator Layer
- 继续建立在 `modular.pipeline` 之上
- 但现在已经显式维护单主线 stage 定义:
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
- 该层负责 stage contract、artifact 传递、对 job manager 发状态
- 当前 stage 到 module 的映射:
  - `ingest_video` -> `pipeline/orchestrator.py`
  - `extract_audio` -> `modular.plugins.extract_audio`
  - `build_audio_chunk_manifest` / `transcribe_chunks` / `merge_transcript` -> `modular.plugins.transcribe_audio`
  - `optional_analysis` -> `screen_detect` / `screen_understanding` / `video_emotion` / `speaker_separation` / `streamer_subtitles` / `subtitle_translate` / `analyze_segments` / `semantic_merge` / `llm_highlight`
  - `select_segments` / `build_clip_manifest` / `render_clips_batch` / `export_results` -> `modular.plugins.render_clips`

### D. Worker / Executor Layer
- 不再按 GUI thread 命名职责
- 改为按资源职责划分:
  - `io_pool`
  - `gpu_asr_pool`
  - `cpu_pool`
  - `render_pool`
- 第一阶段只做“阶段内并发”
  - ASR: chunk 级
  - render: clip 级
  - 不做全局 DAG scheduler
- 2.1.0 当前落地执行模型：
  - `io_pool`：音频 chunk 预取/切片，提前准备下一批输入
  - `gpu_asr_pool`：chunk ASR，单 GPU 默认 `max_workers=1`，一个 ASR worker 连续消费已准备好的 chunk
  - `cpu_pool`：插件层 incremental merge、结果整理、coarse selection 等轻量 CPU 小任务；尚未抽象为独立配置执行器
  - `render_pool`：持续消费 streaming work item，并在最终 render stage 复用已存在输出
- 当前已落地的最小调度器：
  - `gpu_asr_pool`：`transcribe_chunks` 内部按 chunk 调度；当前为单 GPU 保守模式，`max_workers` 默认且实际上保持 `1`
  - `render_pool`：`render_clips_batch` 内部按 clip 调度；并发度由 `render_pool.max_workers` 控制
- 这些 pool 仍只在单阶段内部生效，不改变 orchestrator / backend service 的外层主线职责

### E. Artifact / Output Layer
- 保留现有 `ArtifactStore`、`clips_manifest.json`、`segments.json`、run/work 结构
- 新增的 manifest 应优先作为 artifact，而不是临时 UI 数据

## 5. 目标分离边界
- GUI -> backend service
- backend service -> orchestrator
- orchestrator -> modular plugins / steps
- executor -> stage-internal concurrency
- artifact/output -> run_dir / work / manifest / logs

这条边界必须做到:
- GUI 不直接触达 step 实现
- CLI 也通过同一 backend service，而不是自己拼一套 orchestration
- `modular.pipeline` 继续保留为核心执行能力，而不是被新 service 替换掉

## 6. Phase 1 当前状态
- 已完成:
  - CLI `acfv.cli.pipeline` -> `backend.service`
  - GUI `LocalVideoManager` -> `backend.service`
  - 旧 `features.modules.pipeline_backend.run_pipeline` -> `backend.service` compat wrapper
- 仍保留的兼容层:
  - `LocalVideoManager` 的 QThread 适配层
  - `features.modules.pipeline_backend` 的辅助函数与旧导入路径
- 仍待后续 phase 解决:
  - chunk / clip manifest
  - 阶段内并发和资源池

## 6.1 Phase 2 当前状态
- 已完成:
  - 单一 stage source
  - `job_state.current_stage` 绑定 canonical stages
  - `ingest_video` 从 CLI 中抽离回 orchestrator
  - 最小 stage contract 文件写入 `work/`
- 尚未完成:
  - chunk/clip 级执行器
  - resource pool
  - GUI 纯前端化

## 6.2 Phase 3 当前状态
- 已完成:
  - `transcribe_chunks` 按 chunk 建立 runtime item
  - `render_clips_batch` 按 clip 建立 runtime item
  - queued/running/succeeded/failed/cancelled 最小状态流转落盘
  - plan input 与 runtime state 彻底分离
  - `transcribe_chunks` 现在真实按 chunk 调度执行
  - `render_clips_batch` 现在真实按 clip 调度执行
  - `gpu_asr_pool.max_workers` / `render_pool.max_workers` 已进入现有配置体系
- 尚未完成:
  - 多 attempt/retry 策略
  - 更可靠的取消语义
  - 多 GPU / 更复杂资源池编排

## 6.3 Phase 4 当前状态
- 已完成:
  - GUI 任务提交统一经由 `GuiJobController -> backend.service`
  - GUI 当前阶段直接读取 `job_state.current_stage`
  - GUI 在 `transcribe_chunks` / `render_clips_batch` 阶段直接读取 `work/runtime/*.json` 的摘要
  - GUI 已提供取消、查看日志、打开结果目录等入口
- 仍未完成:
  - 更强取消
  - 更丰富的 chunk/clip 级可视化
  - 将剩余兼容线程进一步收敛为更薄的 watcher

## 7. 分阶段收敛路径

### Phase 1
- 抽出 backend service 和 job manager
- GUI / CLI 都通过同一 service 创建任务
- 保留兼容层

### Phase 2
- 在 `modular.pipeline` 基础上，把 clip 主线显式化为统一 stage list
- 已落地，不再依赖 GUI/CLI 分散维护阶段表

### Phase 3
- 引入音频 chunk manifest、clip manifest、资源池和阶段内并发

### Phase 4
- GUI 收敛为真正前端
- 只看 job 状态与 artifact，不再直接承载业务线程模型

### Phase 5
- verify / regression / compatibility / output contract 回归

## 6.4 Phase 5 当前状态
- 已确认稳定:
  - `orchestrator.py` 仍是统一主线入口
  - `backend.service / job_manager` 仍是唯一 job 外层驱动
  - GUI / CLI / legacy compat 未重新分叉出第二条 backend 主线
  - contract artifact 与 runtime state 分离仍成立
- 已确认入口:
  - CLI help / GUI help / `pipe clip --dry-run-plan` 均可用
  - GUI 代码路径继续通过 `GuiJobController -> backend.service`
  - GUI 当前阶段仍来自 `job_state.current_stage`
  - GUI transcribe/render 摘要仍来自 `get_runtime_state(...)`
- 仍未纳入本轮:
  - 更强取消
  - 有限 retry
  - 多 GPU ASR
  - `io_pool` / `cpu_pool` 完整执行器
  - 更丰富的 GUI 细粒度可视化

## 6.5 2.1.0 Validation Harness
- `scripts/benchmark_streaming.py` 是当前 streaming execution 的统一 benchmark / regression harness。
- harness 不引入新主线，不调用 GUI 业务线程；`run` 模式复用正式 CLI -> backend service -> orchestrator -> modular pipeline。
- harness 自动采集：
  - commit、Python、OS、ffmpeg、CUDA/GPU、输入视频时长、cfg、输出目录、pool worker 配置
  - contract/runtime 分离状态
  - `events.jsonl` 时间线与 TTFCk / TTFC / TAT / TTR / E2E
  - 可用时的 `nvidia-smi` 轻量 GPU 采样
- harness 的结构校验会失败于：
  - `audio_chunk_manifest.json` / `clip_manifest.json` 出现 runtime-only 字段
  - `work/runtime/` 出现 `transcribe_runtime.json`、`render_runtime.json`、`events.jsonl` 以外文件
  - canonical contract artifact 缺失或不对齐

## 8. Phase 2 结论
- 当前项目已经同时具备：
  - 统一 backend service 边界
  - 显式单主线 stage 定义
- 下一步应基于这层显式主线继续做 Phase 3 的阶段内并发，而不是回头重造 backend 或改写全局 DAG
