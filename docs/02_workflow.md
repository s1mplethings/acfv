# 工作流（Spec-first，端到端，含现成实现选型）

## 阶段总览（输入/输出/首选实现）
1) **入口（GUI / CLI / 守护）**  
   - 输入：CLI 参数或 GUI 表单（URL/本地路径/out-dir/cfg），守护配置 `var/settings/stream_monitor.yaml`。  
   - 输出：启动命令、参数解析结果，写入日志；必须校验路径可写/令牌存在。  
   - 日志与可观测性：无论 GUI 还是 CLI，所有用户可见进度/结果必须镜像到终端 stdout（便于采集），同时写入结构化日志（JSONL）。  
   - 建议：CLI 解析用 `typer`/`click`，配置落盘 `config.txt`，日志用 `structlog`；GUI 事件同样调用同一 logging pipeline（避免“GUI-only”消息）。
2) **Ingest（下载 / 本地定位 / 录制）**  
   - 目标：把远端/直播流变成本地可复现的媒体 + 弹幕/聊天原始数据。  
   - 首选实现：  
     - VOD/点播：`yt-dlp >=2025.11.12`（修复 YouTube 403；需外部 JS runtime，如 Deno；Python ≥3.10）。  
     - 直播拉流：`streamlink >=8.0.0`（2025-11-11 发布，Kick/Twitch 支持；低延迟可用 `--twitch-low-latency`）。  
     - Twitch API：Helix `clips` 下载；Highlights/Uploads 自 2025-04-19 起总容量限 100 小时，需本地归档。  
   - 输入：URL 列表、凭证（OAuth token）、输出目录。  
   - 输出：本地媒体文件（`processing/` 或指定目录）、chat JSON（若平台可抓取）、原始清单。  
   - 契约：长路径处理、重试策略（指数退避）、断点续传、鉴权失败回退（提示 scope 或 cookie）。  
3) **预处理（抽取 / 重采样 / 探测）**  
   - 目标：产出统一格式音频 + 元数据。  
   - 首选实现：`ffmpeg 7.1.3`（2025-11-21 最新稳定，7.1 LTS 分支；避免 7.0 API 变更）。  
   - 输入：媒体文件路径。  
   - 处理：转 WAV PCM 16kHz mono（或配置），可选 VAD 先切音频块（Silero/WebRTC）。  
   - 输出：`audio.wav`、`media_meta.json`（时长/采样率/声道/bitrate）。  
4) **转写（Transcribe Audio）**  
   - 目标：高精度、可重现转写 JSON。  
   - 首选实现：  
     - 模型：OpenAI Whisper `large-v3-turbo`（2024-10-01 公布，4 解码层，≈8× large-v3 速度，WER 接近 large-v2/v3）。  
     - 引擎：`faster-whisper` + `CTranslate2` INT8 量化；可选 `whisper.cpp` 做 CPU fallback。  
     - 语种检测开启；长音频使用分块 + 重叠并做分段对齐。  
   - 输入：音频路径、设备/模型配置、语言 hint（可空）。  
   - 输出：`transcript.json`（schema_version，按开始时间排序的 segments），可选 SRT/ASS。  
   - 性能参考：LibriSpeech clean WER ≈2.7%（large-v3），实景混音 WER ≈7.8%；Turbo 在混合场景 ≈7.7%。  
5) **说话人分离 / 合并（可选）**  
   - 目标：给转写加 speaker 标签、支持多说话人剪辑。  
   - 首选实现：`pyannote.audio 4.0.3`（2025-12-07 发布，Python ≥3.10）+ 预训练管线 `speaker-diarization-community-1`（2025-09-29 发布，VBx 聚类）。  
   - 输入：音频 wav；可复用转写的时间戳。  
   - 输出：`diarization.rttm` / JSON（speaker, start_ms, end_ms, confidence）。  
6) **分段 / 评分 / 选段（Highlight Detection）**  
   - 目标：生成稳定、可排序的候选片段。  
   - 方法库：  
     - 视觉语义：HL-CLIP（CVPRW 2024，QVHighlights mAP≈41.9 / Hit@1≈70.6；代码 `github.com/dhk1349/HL-CLIP`）。  
     - 多模态 Transformer：MCT-VHD（JVCIR 2024，视频+音频+文本对齐）；SPOT（Electronics 2025，CNN+TimeSformer）。  
     - 规则/信号：音量峰值、笑声检测、chat 峰值、表情/语气高亢检测。  
   - 输入：转写、情绪特征、弹幕时间线、可选视频帧特征。  
   - 输出：`segments.json`（schema_version，score，start_ms，end_ms，labels，feature_debug），排序规则固定：`score desc` → `start_ms asc` → `end_ms asc`。  
   - 边界策略：`min_duration_ms` / `max_duration_ms` / `merge_gap_ms` / `allow_overlap=false` / `clamp_to_duration=true`。  
   - 空输入处理：返回 `segments=[]` + 可诊断日志。  
7) **渲染 / 导出**  
   - 目标：生成可分发的剪辑/清单。  
   - 实现：`ffmpeg 7.1.x` 裁剪拼接；字幕烧录可选 `ass`；缩略图用 `-ss` 抽帧；模板配置参见 `specs/modules/render_clips/spec.md`。  
   - 输出：`runs/out/<job_id>/clip_*.mp4`、`thumb_*.jpg`、`captions.srt/ass`、`clips_manifest.json`（契约文件）。  
   - 日志要求：渲染进度、帧抽取、失败/重试等必须实时写 stdout，并附带 job_id/segment_id，便于终端监控；GUI 进度条仅为镜像展示，不可成为唯一输出。
8) **守护循环（Stream Monitor）**  
   - 目标：按计划拉流、落盘、触发后续 pipeline。  
   - 实现：`streamlink` 轮询 + `Twitch EventSub`（如有）触发；支持多目标并发；健康检查写 `logs/monitor.log`。  
   - 输入：`var/settings/stream_monitor.yaml`（targets，interval_ms，retry）。  
   - 输出：持续落盘媒体/聊天，触发 ingest→预处理→后续流水线。

## 模块 Spec 必填字段
- Purpose / Inputs / Outputs / Process / Config / Performance / Error / Edge / AC / Trace Links。  
- AC 用 Given/When/Then，需给出样例输入输出及关联测试用例 ID。  
- 输入/输出契约用表格列字段/类型/必填/约束/示例，并声明错误处理与降级策略。

## Tasks 拆解与 DoD
- 每条 task 写明 DoD（完成定义）+ 验证命令。  
- 流程：更新 spec → 更新/新增测试 → 实现 → 运行 verify（Win: `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`；*nix: `bash scripts/verify.sh`）→ 记录 decision/problem。

## 实现循环
1) 选定 task，确认相关 spec/contract 最新。  
2) 先写/更新测试（unit/integration/e2e/golden）覆盖 AC。  
3) 实现或修复，保持与 spec 一致。  
4) 运行 verify；失败记录 `ai_context/problem_registry.md`（症状→根因→修复→预防）。

## Drift 处理
- 发现实现≠spec：先改 spec + tests，再改实现；临时偏离需 `decision_log`。  
- 输出契约变更：同步更新 contract_output + golden + tests。

## 切片（分段/评分/选段）硬性规则
- 时间单位统一 ms；输出含 `schema_version`。  
- 排序确定性：`score desc` → `start_ms asc` → `end_ms asc`。  
- 边界策略：`min_duration_ms` / `max_duration_ms` / `merge_gap_ms` / `allow_overlap` / `clamp_to_duration` 必须在 spec + contract 明确。  
- 空输入返回 `segments=[]` + 明确日志；不得产出不可诊断空文件。
