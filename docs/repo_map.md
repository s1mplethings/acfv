# Repo Map (ACFV)

MVP Product Layer 版本，记录当前真实结构、统一 backend 主线与 Creator Library 产品层。

## 0. CGNK Navigation
- Level 1: `.cgnk/project.yaml` is the machine-readable navigation entry.
- Level 2: `docs/context/` contains current truth and `specs/capabilities/index.yaml`
  resolves each production capability to one owner.
- Level 3: capability specs, `.agents/skills/`, `knowledge/`, and promoted `evidence/`
  provide task-specific detail without requiring a full-repository scan.
- Runtime data remains under ignored `runs/` and `var/`; it becomes evidence only through
  the promotion rules in `evidence/README.md`.

## 1. Entry Points
- `acfv` console script -> `src/acfv/cli/_entry.py` -> `src/acfv/cli/__main__.py`
- CLI clip 入口 -> `src/acfv/cli/pipeline.py`
  - `clip(...)` 支持 `--dry-run-plan` 输出统一 stage plan
  - 实际执行进入 `src/acfv/backend/service.py`
  - 再到 `src/acfv/pipeline/orchestrator.py::run_clip_pipeline`
  - 最后调用 `src/acfv/modular/pipeline.py::run_pipeline`
- GUI 入口 -> `src/acfv/cli/gui.py` / `src/acfv/gui.py`
  - `_launch()` -> `src/acfv/app/gui.py::launch_gui`
  - `launch_gui()` 启动前会先走 `src/acfv/app/gui_startup_doctor.py` 轻量自检；缺少可安全修复的 Python 依赖时会尝试自动安装
  - `launch_gui()` -> `src/acfv/app/interest_adapter.py::create_interest_main_window`
  - 当前实际主窗口仍是 `src/acfv/main_window.py::MainWindow`
- Stream monitor 入口
  - CLI: `src/acfv/cli/stream_monitor.py`
  - GUI: `src/acfv/cli/stream_monitor_ui.py` / `src/acfv/ui/stream_monitor_editor.py`
- Creator Library 入口
  - CLI: `acfv library ...` -> `src/acfv/cli/library.py`; `acfv download vod/status`
    -> `src/acfv/cli/download.py`
  - Moment/Search/Clip: `acfv moments ...`, `acfv search`, `acfv clip ...`
  - service: `src/acfv/library/service.py`
  - persistent state: `var/acfv.db`

## 2. Current Layer Map

### Live Processing
- `src/acfv/live/service.py`
  - canonical closed-segment coordinator; owns segment manifest/events, once-only ASR,
    absolute transcript merge, PROVISIONAL Moment/index update, retry, and finalization.
- `src/acfv/runtime/stream_monitor.py`
  - continues to own StreamGet detection and FFmpeg recording; capture now uses the FFmpeg
    segment muxer (60-second TS by default), emits `segment_closed`, then concatenates a
    stable final MP4.
- `src/acfv/library/capture.py`
  - translates recorder/chat events into Creator Library state and delegates closed media
    to `LiveProcessingService` on a single ASR worker.

### Twitch VOD Download
- `src/acfv/library/vod_download.py`
  - canonical VOD lifecycle owner: strict URL normalization, metadata mapping,
    platform+VOD dedupe, durable progress/state, partial preservation, ffprobe/decode/
    silence validation, atomic promotion, and handoff to `LibraryService.process_recording`.
- `src/acfv/providers/download.py`
  - thin TwitchDownloaderCLI process adapter for `info` and range/full downloads.
- `src/acfv/ui/tabs/library_tab.py` and `src/acfv/cli/download.py`
  - thin GUI/CLI adapters over the same persisted `VodDownload` state.

### Creator-Adaptive Corpus Safety
- `src/acfv/creator_adaptive/corpus.py`
  - owns frozen VOD-level TRAIN/VALIDATION/HOLDOUT roles and rejects memory writes outside the allowed role.
- `src/acfv/creator_adaptive/final_holdout.py`
  - owns immutable V1/V2 final-holdout states, durable leakage events, and atomic one-time claims after preflight.
  - a final-holdout VOD is rejected before training/calibration even if a malformed split labels it TRAIN.
- `scripts/run_five_creator_adaptive_v2.py`
  - builds the three new Creator voice/voice-mode, identity, trusted-speech, lexicon/acoustic, and adaptive-shadow artifacts from frozen TRAIN VODs, using VALIDATION only for independent calibration and never opening a final holdout.
  - each execution uses a new immutable `runs/<run-id>` directory under the external V2 derived root.
- `scripts/validate_five_creator_v2_gates.py`
  - combines the two retained legacy profiles with the three new profiles for a no-holdout 5×5 support-only score audit and an executable cross-Creator poisoning gate.
- `scripts/run_five_creator_v2_soak.py`
  - runs the bounded creator-adaptive critical tests for 2–6 hours while enforcing stable evidence hashes and a non-drifting working tree.

### GUI / UI
- `src/acfv/ui/tabs/library_tab.py` / `conversation_tab.py`
  - 主窗口最前方的 MVP 产品入口；Library 只调用 LibraryService，Conversation 只调用 retrieval/conversation service。
  - Evidence Preview 复用 PyQt multimedia 并跳转到 Moment 的 start_ms。
- `src/acfv/main_window.py`
  - 当前主 GUI 容器，负责标签页、状态栏、错误弹窗、进度组件、部分线程清理
  - 2026-04 冷启动修复后，主窗口只保留轻量初始化；`faiss`、断点管理、RAG 总结、直播监控页以及切片缩略图/时长探测改为按需或延迟执行
- `src/acfv/ui/`
  - 标签页与 GUI 组件
  - `tabs/` 下包含本地视频、Twitch、字幕渲染、RAG 偏好等页面
  - 2026-04 起，字幕渲染页和设置页的 AI 高光配置改成精简模式：界面只保留统一 `LLM模型`、候选倍数和偏好提示，不再单独暴露本地模型/视觉模型输入框
- `src/acfv/features/modules/`
  - GUI 辅助组件、进度 UI、缩略图加载、旧 backend 工具
  - `clips_manager.py` 启动时走 fast refresh，只加载切片清单；完整缩略图和时长探测保留在手动刷新路径
- `src/acfv/steps/local_video_manager/impl.py`
  - 当前 GUI 本地视频处理的关键桥接层
  - 现在只在 `ThreadSafeWorker` 中做轻量 job 提交准备
  - 通过 `GuiJobController` 轮询 `backend.service` 的 job state 与 runtime state
  - 同一视频重复处理时，默认复用最新未完成的 `runs/run_XXX` 作为恢复点；只有显式重新开始才新建 run
  - 负责把 backend/job/runtime 摘要映射回 GUI 进度、错误与结果入口
- `src/acfv/processing/checkpoint_manager.py`
  - 轻量断点管理模块
  - 从旧 `processing/analyze_data` 兼容入口中拆出，避免 GUI 启动时误导入完整分析栈
- `src/acfv/app/gui_job_controller.py`
  - Phase 4 新增的 GUI 薄控制层
  - 统一读取 `backend.service.create_job/get_job_status/cancel_job/get_logs/get_runtime_state`
  - 为 GUI 提供当前 job、runtime 摘要、错误摘要、结果目录入口

### Backend / Pipeline Core
- `src/acfv/library/`
  - Product Layer 的 Creator / Source / Recording 持久化边界。
  - SQLite + SQLModel 保存业务状态与 artifact locator；媒体、transcript、events 仍由 pipeline artifact 管理。
  - `artifacts.py` owns portable `library_root_id + relative_path` locators and legacy-root resolution;
    `transcript_quality.py` owns transcript-derived language profiles, background-lyrics classification,
    and non-destructive display corrections while raw transcript artifacts remain immutable.
  - `LibraryService` 是 CLI/GUI 共用入口，并把处理任务委托给现有 `backend.service`。
  - Analysis Profile GUI selector 通过 `LibraryService` 保存 Recording override 或
    Creator/Source default；GUI 不直接写数据库。
- `src/acfv/moments/`
  - 从 canonical transcript/chat evidence 构建持久化 PROVISIONAL/FINAL Moment。
  - 直播增量输入通过稳定时间窗口 identity 幂等写入，不复制原始 artifact。
- `src/acfv/retrieval/`
  - 使用可配置的真实 multilingual embedding + FAISS/NumPy，并以 FTS5/RRF/可配置 multilingual reranker 组成统一检索路径。
  - production 模型失败时显式进入 `DEGRADED_FTS_ONLY`；deterministic hash 仅允许显式 test mode。
  - v5 index 以 Moment 为 parent/result 单元，索引 SUMMARY、FULL_TRANSCRIPT、重叠 PASSAGE、
    NEIGHBOR_CONTEXT、CORRECTED_SPEECH 与独立降权的 BACKGROUND_LYRICS representations；
    FTS5 同样按 representation 建索引，并可按精确 representation identity 复用旧 embedding。
  - `var/moment_index/manifest.json` 保存模型、维度、配置 hash、representation schema/config hash、Moment UUID/scope；模型或版本不匹配必须仅重建 retrieval index。
  - Dense/FTS 各取 128，按 best representation + 小幅 second-hit bonus 聚合 parent，融合后最多 50 个 Moment 进入 CrossEncoder，避免长文本截断与长度偏置。
- `src/acfv/conversation/`
  - Evidence-first 的薄问答层；先检索和充分性检查，再选择性调用现有 LLM provider。
  - 明确返回 `GROUNDED_LLM` / `EVIDENCE_ONLY` / `DEGRADED`；citation 存在不再等同 grounded。
  - LLM 只看到 request-local `E1/E2/...` evidence ID；citation 经映射校验后才返回真实 SearchResult cards。超时或 malformed output 最多修复一次，随后诚实降级。
  - 返回短答案与真实 SearchResult evidence cards，不保存复杂聊天历史。
- `src/acfv/clips/`
  - 将一个有足够语义/事件证据的 Moment 转为一个可编辑 Clip proposal；句子/停顿边界优先，正常自动 Clip 上限 90 秒。
  - `candidates.py` 是 Retrieval Top-10 到 3–5 个候选的正式产品层：区分
    `MOST_RELEVANT` / `MOST_COMPLETE` / `MOST_WATCHABLE`，执行 watchability、
    eligibility 与 source-edge gate，再复用既有 review renderer 生成 preview。
  - `subtitles.py` 定义 recording-relative Word/Cue/Track、共享双语时间轴、
    translation cache、语义 Cue 切分、ASS/SRT 与 timeline quality report；本地 Qwen JSON
    provider 与 Argos fallback 都必须返回非空目标文本，失败不得复制源文冒充翻译。
  - `duration.py` 只在语义单元边界上选择 SHORT/STANDARD/LONG/FULL_EVENT/CUSTOM；
    `variants.py` 组合 profile 与双语字幕并继续调用现有 review renderer。
  - `refinement.py` 是最终成片字幕的二阶段 owner：只转录 `FULL_EVENT + context`，保存 Library/raw-final/corrected/aligned 四层数据，按事件缓存并供全部 duration variants 复用；Library ASR 仍只负责搜索底稿。
  - 2026-10 language hardening 后，`refinement.py` 额外拥有词级 confidence/source/quality flags、
    低置信局部 ±2s 重解码、证据约束 source correction 与 ASR release gate；每个事件写
    `final_transcript_quality.json`。`subtitles.py` 拥有 contextual localization v2 的结构化
    event context、adaptive batch、逐 Cue provider provenance、semantic guards 与 translation gate；
    `variants.py` 只负责汇总 `final_language_quality.json`，并始终保留 human review pending。
  - 2026-10 language calibration 后，`refinement.py` 区分四态 source-correction decision 与五类
    口语句式，`subtitles.py` 统一拥有 semantic importance/position、typed entity guard、可解释
    risk score 和三态 release gate；`scripts/build_language_quality_calibration.py` 只对冻结的
    12-Clip 历史快照生成固定集、mutation、对比和人工复核包，不写 Creator Library。
  - production Create Clip 默认由 `ClipVariantService` 选择 semantic STANDARD；固定窗口只能作为带 `is_preview=true` 的 `PREVIEW_PROXY`，不得进入 final 统计。
  - 最终翻译默认使用 Qwen 的 5-9 Cue 上下文化 `LOCALIZED_CREATOR` JSON 输出，Argos 仅在 provider 失败时 fallback；翻译不拥有时间轴。
  - `gui_workflow.py` 是 Review 页的持久化产品编排层：加载 Event Plan、恢复/生成变体、
    保存双语 Cue edits、创建 `revision_NNN` 重渲染、选择最终版本并记录决策；UI 不直接写
    SQLite、ASS/SRT 或调用 FFmpeg。
  - 经 `backend.service.render_review_clip` 适配现有 render_clips 实现，不创建第二套 FFmpeg renderer。
- `src/acfv/feedback/`
  - 持久化 Accept/Reject、相对 Moment 的边界 delta 与 USER_EXPLICIT preference。
  - retrieval 仅用显式关键词做透明加减分，不推断偏好或训练模型。
- `src/acfv/backend/`
  - Phase 1 新增的统一 backend 边界。
  - `service.py`：提供 `create_job`、`get_job_status`、`cancel_job`、`list_artifacts`、`get_logs`、`wait_for_job`。
  - `job_manager.py`：统一管理 job 创建、后台执行、状态流转与取消请求。
  - `job_state.py`：定义 job 状态、阶段、进度摘要、错误摘要、artifact 引用。
- `src/acfv/pipeline/`
  - Phase 2 新增的单主线薄层。
  - `stages.py`：唯一 stage source，定义固定主线、stage 名称、输入/输出、optional 标记与 legacy/raw stage 映射。
  - `orchestrator.py`：统一 clip 主线入口，负责 `ingest_video` 与 `stage_plan.json` 落盘，再调用 `modular.pipeline`。
  - `contracts.py`：Phase 2 hardening 新增的 contract 校验器，用于验证 6 个主线 artifact 的存在性和前后对齐关系。
  - `runtime.py`：Phase 3 新增的 runtime state 写盘工具；负责 `work/runtime/*.json` 的原子写盘与阶段内 dispatcher 状态更新，不改 contract artifact 语义。
- `src/acfv/modular/`
  - 当前正式的模块化 pipeline 核心
  - `pipeline.py`: 组装 registry / store / progress emitter，并执行 end-to-end run
  - `runner.py`: 依据 artifact 依赖执行 module plan
  - `planner.py`: 根据 goal artifact 和可用 artifact 推导执行计划
  - `store.py`: `run_dir/artifacts/` artifact store，维护 `index.json` 与 `producer_index.json`
  - `progress.py`: 把阶段进度写成 `Progress:stage.v1` artifact
  - `contracts.py`: artifact type 常量
- `src/acfv/modular/plugins/`
  - 现有 step/plugin 注册点
  - 当前 clip 主线涉及：`extract_audio`、`transcribe_audio`、`video_emotion`、`speaker_separation`、`analyze_segments`、`semantic_merge`、`llm_highlight`、`render_clips`
  - 可选屏幕语义相关插件：`screen_detect`、`screen_understanding`
  - 字幕相关插件：`streamer_subtitles`、`subtitle_translate`
  - `transcribe_audio` 插件在子进程转录失败时，会先按 `work/chunks/chunk_XXXX/transcript.json` 回填已完成 chunk，再只把真实卡住的 chunk 标为 failed，避免 runtime 把后续未处理 chunk 一并污染成 failed
- `src/acfv/providers/`
  - 2026-04 新增的 provider/adapters 薄层
  - `download.py`：统一本地文件 / TwitchDownloader / Streamlink 的入口解析
  - `asr.py`：统一 faster-whisper / WhisperX / hf-whisper provider 选择
  - `vision.py`：统一 PySceneDetect / OCR provider 选择；RapidVideOCR 不可用时回退到 pytesseract
  - `config.py`：兼容 CLI YAML `providers.*` 与旧 `WHISPER_* / ENABLE_*` 键读取

### Step Implementations
- `src/acfv/steps/`
  - 每个 plugin 的具体实现
  - 典型文件：
  - `steps/transcribe_audio/impl.py`
  - `steps/render_clips/impl.py`
  - `steps/llm_highlight/impl.py`
  - `steps/screen_detect/impl.py`
  - `steps/screen_understanding/impl.py`
  - `steps/transcribe_audio/impl.py` 现在在进程内缓存最近使用的 ASR 模型对象，避免 GUI/脚本重复转录时反复加载同一 Whisper 模型
  - `steps/transcribe_audio/impl.py` 现在会优先查找本地 `faster-whisper` 缓存；若模型未缓存且访问 Hugging Face 失败，会尽快报出“模型未缓存/网络不可用”的明确错误，而不是长时间重复刷同一条 50% 进度
  - `steps/transcribe_audio/impl.py` 在 chunk 模式下会在每个 chunk 结束后立即删除临时 wav，并执行 `gc.collect()`；CUDA 路径还会额外做 `torch.cuda.empty_cache()/ipc_collect()`，降低长回放中途卡死的概率
  - `steps/transcribe_audio/impl.py` 现在还会对 `faster-whisper` 长回放做分批子进程回收；默认每处理 `60` 个新 chunk 就主动重启子进程，并复用 `work/chunks/chunk_XXXX/transcript.json` 断点续跑，避免同一个 native 进程一路跑到 90+ chunk 后退化卡死
  - `steps/analyze_segments/impl.py` 的 `tqdm` 进度条和阶段名现在会按当前终端编码做安全降级，避免 Windows GBK 控制台因 emoji 日志把 `optional_analysis` 整段打死
  - `main_logging.py` 与旧 `features/modules/core` 的控制台日志 handler 现在统一使用安全 stream handler；即使终端是 GBK/CP936，`✅/⚡/❌` 这类字符也只会被替换显示，不会再把流程打死
  - `steps/extract_chat/impl.py` 现在把 `transformers` 改成按需导入；即使本机 `PIL/_imaging` 或聊天情感分析依赖损坏，只要关闭逐条聊天情感分析，HTML 弹幕解析仍可正常产出 `work/chat.json`
  - `modular/plugins/semantic_merge.py` 现在会先生成语义连续段，再按分析高光重叠区收缩到“高光核心”；默认目标时长也从长段调整到更像高光短切的 `45-150s` 区间，避免输出总被拉成接近固定长度
- `src/acfv/selection/`
  - 片段合并 / 选段契约实现

### Legacy / Transitional Paths
- `src/acfv/features/modules/pipeline_backend.py`
  - 仍保留旧模块名，但 `run_pipeline(...)` 已在 Phase 1 降为兼容转发壳。
  - 核心执行统一转发到 `acfv.backend.service`，避免新旧 backend 双轨。
  - `generate_content_indexes(...)` 等辅助函数仍保留在该模块。
- `src/acfv/interest/`
  - 当前基本是兼容导出层
  - `interest/main_window.py` 直接转发到 `acfv.main_window.MainWindow`
  - `interest/modules/pipeline_backend.py` 转发到旧 `features.modules.pipeline_backend`

## 3. Current Dependency Direction
- GUI 本地视频处理:
  - `MainWindow`
  - -> `LocalVideoManager`
  - -> `GuiJobController`
  - -> `backend.service.create_job / get_job_status / cancel_job / get_runtime_state / get_logs`
  - -> `pipeline.orchestrator.run_clip_pipeline`
  - -> `modular.pipeline.run_pipeline`
  - -> `modular.plugins.*`
  - -> `steps/*`
- CLI clip:
  - `acfv.cli.pipeline`
  - -> `backend.service.create_job / wait_for_job`
  - -> `pipeline.orchestrator.run_clip_pipeline`
  - -> `modular.pipeline.run_pipeline`
  - -> `modular.plugins.*`
  - -> `steps/*`
- 现状结论:
  - GUI 和 CLI 已开始共享 `modular.pipeline`
  - Phase 1 起二者已统一通过 `backend.service` 发起和管理 job
  - job 创建、状态查询、取消、日志和 artifact 列表现在有统一边界
  - 2026-04 起主链默认切到“本地开源优先”：下载走 TwitchDownloader/Streamlink provider，ASR 走 faster-whisper/WhisperX provider，LLM 高光保持 optional

## 4. Current Workflow Shape
- CLI 与 GUI 当前主线都显式收敛到 `run_clip_pipeline(...)`
- GUI 当前主线是:
  - 用户选择本地视频
  - `LocalVideoManager` 创建 `clips/<video>/runs/run_xxx`
  - 后台 `ThreadSafeWorker` 只提交 job，不等待主线执行
  - `GuiJobController` 定时轮询 job state 与 `work/runtime/*.json`
  - GUI 直接显示 canonical stage、错误摘要、runtime 摘要与结果目录入口
- `pipeline/stages.py` 当前固定主线：
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
- `modular.pipeline` 当前 goal 是 `ART_CLIPS`
  - 起始 artifact: `ART_VIDEO`，可选 `ART_CHAT_SOURCE`
  - Stage 与现有 module 的映射:
    - `extract_audio` -> `extract_audio`
    - `build_audio_chunk_manifest` + `transcribe_chunks` + `merge_transcript` -> `transcribe_audio`
    - `optional_analysis` -> `screen_detect` / `screen_understanding` / `video_emotion` / `speaker_separation` / `streamer_subtitles` / `subtitle_translate` / `analyze_segments` / `semantic_merge` / `llm_highlight`
    - `select_segments` + `build_clip_manifest` + `render_clips_batch` + `export_results` -> `render_clips`
- 当前问题:
  - `audio_chunk_manifest` 与 `clip_manifest` 已固定为 plan input，但复杂 retry、更强取消、多 GPU ASR 仍未进入本轮
  - GUI 仍保留兼容适配层，但主线已不再由 GUI 自己等待或猜阶段

## 5. Config Entry Points
- 事实源:
  - `pyproject.toml`
- 运行配置:
  - `src/acfv/config/config.py::ConfigManager`
  - `src/acfv/configs/settings.py`
  - `src/acfv/config/default.yaml`
  - `config.txt`
  - `var/settings/*.yaml`
  - 2026-04 起默认 YAML 以 `providers.download/asr/scene/ocr/llm` + `features.*` 为主，旧 `WHISPER_* / ENABLE_*` 键仍保留兼容
- CLI clip:
  - `--cfg` YAML 经 `src/acfv/cli/pipeline.py::_YamlConfigAdapter` 注入 `modular.pipeline`
- GUI:
  - 主要通过 `ConfigManager` 读写，并传入 `LocalVideoManager` / `MainWindow`
  - `acfv gui --open-recording ... --open-review --event-plan ... [--output-root ...]`
    可通过正式 MainWindow deep link 打开 Review；Review 复用 PyQt Multimedia 播放器并默认
    加载 STANDARD，但不会自动播放。
  - 2026-04 当前转录默认值：`WHISPER_MODEL=medium`、`SEGMENT_LENGTH=120`
  - 2026-04 当前高光时长默认值：`MIN_TARGET_CLIP_DURATION=45`、`TARGET_CLIP_DURATION=90`、`MAX_TARGET_CLIP_DURATION=150`；语义高光默认 `SEMANTIC_TARGET_DURATION=90`
  - 若使用 `faster-whisper + large-v3/large-v3-turbo`，长段切块会自动压到 `60s` 以降低 CUDA OOM 风险

## 6. Output / Artifact Paths
- 稳定运行目录:
  - `var/processing/`
  - `var/logs/`
  - `var/settings/`
  - `var/tools/`
  - intelligence 质量重建使用 `var/intelligence_quality_*/library_v2.db` 与同目录索引；原 Library DB 不覆盖。
- 固定评测证据:
  - baseline: `evidence/product-evaluation-baseline/`
  - v2: `evidence/product-evaluation-v2/`
  - 小型 receipts/mapping: `evidence/validation/`
- CLI 默认输出:
  - `runs/out/run_<timestamp>/`
- GUI 本地视频输出:
  - `clips/<video_slug>/runs/run_<nnn>/`
- modular run 目录内部:
  - `artifacts/`
  - `index.json`
  - `producer_index.json`
  - `work/stage_plan.json`
  - `work/audio_chunk_manifest.json`
  - `work/transcription.json`
  - `work/transcript_merged.json`
  - `work/segments.json`
  - `work/selected_segments.json`
  - `work/clip_manifest.json`
  - `work/clips_manifest.json`
  - `work/export_results.json`
  - `work/runtime/transcribe_runtime.json`
  - `work/runtime/render_runtime.json`
  - `work/runtime/events.jsonl`
- 兼容输出:
  - `clips_manifest.json` 也会复制到 run 根目录，方便 GUI / 用户浏览

## 7. Thread / Worker Hotspots
- `src/acfv/main_window.py`
  - `SimpleWorker`
  - `VideoProcessWorker`
  - `DownloadWorker`
  - `ProgressUpdateWorker` 的生命周期管理
- `src/acfv/features/modules/ui_components.py`
  - 通用 `Worker`
  - 缩略图加载 QThread
- `src/acfv/steps/local_video_manager/impl.py`
  - `ThreadSafeWorker`
  - GUI 当前真正的 pipeline 后台执行点
- `src/acfv/ui/stream_monitor_worker.py`
  - 独立 stream monitor worker
- `src/acfv/steps/twitch_downloader/impl.py`
  - 下载 / 拉取 VOD 列表相关 worker

## 8. Current GUI / Backend / Modular Relation
- 当前关系
  - GUI 负责输入、状态显示、错误弹窗、日志入口与结果目录入口
  - `LocalVideoManager` 当前作为 GUI 兼容适配层，调用 `GuiJobController`
  - `GuiJobController` 再统一读取 `backend.service`
  - `modular.pipeline` 负责 plugin 编排、artifact store、contract output
  - 旧 `features.modules.pipeline_backend` 只保留兼容入口，不再拥有独立 job backend 主路径
- 目标关系
  - GUI 只保留输入、任务提交、进度展示、错误展示、结果打开
  - backend service 统一提供 `create_job/get_job_status/cancel_job/list_artifacts/get_logs/get_runtime_state`
  - orchestrator 显式维护长视频单主线
  - worker/executor 层负责阶段内并发与资源池

## 9. Phase 2 Summary
- 已共享:
  - GUI 本地视频主处理路径与 CLI `pipe clip` 都能走 `modular.pipeline`
  - GUI / CLI / legacy compat path 都通过 `backend.service` 管理 job
- 已显式化:
  - clip pipeline 固定主线与 stage vocabulary 统一来自 `src/acfv/pipeline/stages.py`
  - `job_state.current_stage` 通过同一份 stage 映射反映当前主线阶段
  - `stage_plan.json`、`audio_chunk_manifest.json`、`transcript_merged.json`、`selected_segments.json`、`clip_manifest.json`、`export_results.json` 已纳入主线摘要产物
- 已新增执行态:
  - `audio_chunk_manifest.json` 作为 `transcribe_chunks` plan input
  - `clip_manifest.json` 作为 `render_clips_batch` plan input
  - 运行态单独写入 `work/runtime/*.json`
- 已落地的阶段内执行器:
  - `transcribe_audio` 现在按 chunk 读取 `audio_chunk_manifest.json` 并用 `gpu_asr_pool` dispatcher 执行
  - `render_clips` 现在按 clip 读取 `clip_manifest.json` 并用 `render_pool` dispatcher 执行
  - 配置项统一走现有配置体系：
    - `gpu_asr_pool.max_workers`
    - `render_pool.max_workers`
- 2.1.0 streaming window 已变更:
  - canonical 10-stage 仍是语义与最终汇总边界，不再等同于所有内部工作都必须全局硬 barrier。
  - `transcribe_audio` 在 chunk 成功后立即写 `work/chunks/<chunk_id>/transcript.json`，并通过 `work/runtime/events.jsonl` 记录 incremental merge / clip work item 事件。
  - fast path 现在按归一化 `(start_ms,end_ms)` 生成稳定窗口 identity；同一逻辑窗口只允许生成一个 clip work item。
  - 去重分两层：`transcribe_audio` 先拦截重复 chunk result / 重复窗口，render 入队前再基于窗口 identity 拒绝重复提交，并写 `clip_work_item_deduplicated` / `render_enqueue_skipped_duplicate` 事件。
  - `steps/transcribe_audio/impl.py` 内部使用 `io_pool` 预取音频 chunk，单 GPU `gpu_asr_pool:0` 连续消费已准备好的 chunk，避免 ffmpeg 切片阻塞 GPU worker。
  - streaming fast path 可用局部 transcript 粗选片段并提前投喂 `render_pool`；最终 `render_clips` stage 仍重建完整 `selected_segments.json`、`clip_manifest.json`、`clips_manifest.json` 与 `export_results.json`。
  - `runtime.py` 先追加 `events.jsonl`，summary JSON 采用周期刷新与 finalize 强制刷新；相同 item 状态更新按幂等处理，避免重复成功事件把 runtime/event 计数撑脏。
- 本阶段未解决:
  - 复杂 retry
  - 更强取消
  - 多 GPU ASR 扩展
- Phase 4 GUI 已落地:
  - GUI 当前阶段显示直接来自 `job_state.current_stage`
  - GUI 当前任务摘要直接来自 `backend.service.get_job_status(...)`
  - GUI 细粒度摘要直接来自 `backend.service.get_runtime_state(...)`
  - GUI 通过按钮提供取消、查看日志、打开结果目录
- 后续改造原则:
  - 保留现有入口
  - 不删兼容层
  - 继续在已显式化主线上补阶段内并发，而不是另起一套新 pipeline

## 10. Phase 5 Regression Closure
- 已回归确认:
  - GUI / CLI / legacy compat 都继续经由 `backend.service`
  - canonical 10-stage 主线、`orchestrator.py`、contract artifact 语义未被回归破坏
  - `audio_chunk_manifest.json` / `clip_manifest.json` 仍保持 plan input 身份
  - `work/runtime/transcribe_runtime.json` / `work/runtime/render_runtime.json` 仍保持独立执行态
- 已验证入口:
  - `python -m acfv.cli --help`
  - `python -m acfv.cli gui --help`
  - `python -m acfv.cli pipe clip --help`
  - `python -m acfv.cli pipe clip --url demo --dry-run-plan`
- 仍保留的限制:
  - `cancel_job(...)` 仍是 best-effort
  - `attempt` 仅为预留字段，未实现复杂 retry
  - `cpu_pool` 当前只落在插件层轻量整理/窗口选择职责，尚未抽象为独立可配置执行器
  - GUI 的 chunk / clip 展示仍以摘要为主

## 11. 2.1.0 Streaming Execution Update
- 核心原则:
  - `stage_plan.json` 中的 10 个 canonical stages 不变。
  - `audio_chunk_manifest.json` 与 `clip_manifest.json` 继续是 plan/contract artifact，不写入 worker、attempt、running 等执行态字段。
  - 执行态固定在 `work/runtime/`，其中 `events.jsonl` 是细粒度事件流，`transcribe_runtime.json` / `render_runtime.json` 是 GUI 可轮询的稳定摘要。
- fast path:
  - `extract_audio -> build_audio_chunk_manifest -> transcribe_chunks -> incremental merge -> coarse segment -> clip work item -> render_pool`。
  - fast path 只用局部 transcript 做粗选，目标是让长视频尽早产出可渲染 work item。
- enrich path:
  - `screen_detect`、`screen_understanding`、`video_emotion`、`speaker_separation`、`streamer_subtitles`、`subtitle_translate`、`llm_highlight` 仍属于 `optional_analysis`。
  - enrich 结果可以补充最终排序/元数据，但不再作为 streaming fast path 的关键阻塞点。
- ASR / render 职责:
  - `io_pool`: 预取/切片下一批 audio chunk。
  - `gpu_asr_pool`: 单 GPU 默认一个 worker，连续消费已准备好的 chunk。
  - `cpu_pool`: 当前以插件内轻量整理、incremental merge、coarse selection 表达，后续可独立抽象。
  - `render_pool`: 既能处理 streaming work item，也能在最终 `render_clips` stage 复用已存在输出并完成汇总。

## 12. 2.1.0 Validation / Benchmark Harness
- `scripts/benchmark_streaming.py`
  - `run`: 通过正式 CLI/backend 主线执行 pipeline，并收集 benchmark 输出。
  - `collect`: 分析已有 `run_dir`，复用同一套 artifact/runtime/events 校验。
  - 输出固定在 `var/benchmarks/<run_id>/meta.json`、`results.json`、`timeline.json`、`report.md`。
- `tests/integration/test_benchmark_streaming.py`
  - 用 fake run_dir 自动验证 TTFCk / TTFC / TAT / TTR 推导、streaming proof、contract/runtime 分离和报告写出。
- `tests/integration/test_provider_contracts.py`
  - 聚焦 `providers/*` 与本地开源主链 fallback：download / asr / scene / ocr / llm 五类 provider contract。
- `tests/integration/test_clip_workflow_smoke.py`
  - 用真实小样本 `sample.mp4` 跑 clip 主链 smoke，覆盖 core-only、scene+ocr、whisperx、llm disabled、llm endpoint unavailable。
- `tests/e2e/test_clip_workflow_e2e.py`
  - 跑真实主链 e2e：本地视频、Twitch/VOD mock 下载链路、ASR fallback 链路。
- `tests/integration/test_contract_output_checks.py`
  - 生成真实 `selected_segments.json / clips_manifest.json / export_results.json` 后，再调用 `scripts/contract_checks.py --run-dir --require-artifacts` 做真实产物校验。
- Final Clip quality harnesses:
  - `scripts/build_asr_quality_review.py` 固定抽取 30 段真实音频并生成盲评包；未成功加载的模型保留显式 unavailable 状态。
  - `scripts/build_translation_quality_review.py` 生成 40 组带上下文的 Qwen/Argos 对照与人工评审表。
  - `scripts/render_final_clip_quality_pack.py` 通过 canonical duration/final-ASR/subtitle/render 链生成 12 个 STANDARD 与多 profile 最终 MP4，支持内容缓存和断点续跑。
- `docs/benchmark_validation.md`
  - 记录 short / medium / long 测试集准备、运行命令、结果读取和 GUI smoke 验证方式。

## 13. Active Creator Adaptive V2 Final Validation
- Active scope is fixed to `saruei / atelieranoko / snuffy / laphipi`; inactive `anny` is recorded as `OUT_OF_SCOPE_INACTIVE_CREATOR` and is not evaluated.
- `scripts/prepare_active_creator_v2_calibration.py` creates a TRAIN/VALIDATION-only, unlabelled human-calibration queue; Final media is explicitly excluded.
- `scripts/validate_five_creator_v2_gates.py --creators ...` runs the scope-selected N×N identity and poisoning audit and emits `creator-gate-receipt.json`.
- `scripts/prepare_active_creator_final_holdout_v1.py` freezes one disjoint public VOD per active creator plus the clean Git and model/profile hashes.
- `scripts/download_active_creator_final_holdout_v1.py` performs canonical single-worker, best-quality acquisition and strict media-integrity checks without claiming the holdout.
- `scripts/run_active_creator_final_holdout_v1.py` checks all frozen inputs, atomically claims the holdout once, freezes automated results, and only then emits unlabelled human-review tasks.
- Final bulk media, receipts, databases, logs, and review queues live under the configured external `<bulk-root>`; no runtime artifact is committed to Git.

# Runtime launcher portability

- `scripts/build_real_library.py` resolves its transcription Python from an explicit resolver argument, then `ACFV_PYTHON`, then the current `sys.executable`; invalid configured paths fail explicitly.
- `scripts/start_gpu_gui.ps1` resolves Python from `-PythonExecutable` (legacy alias `-PythonPath`), `ACFV_PYTHON`, active `CONDA_PREFIX`, then `PATH`, without a machine-specific default.
