# Clip Pipeline Spec

## 1) Purpose
- 负责：从 Twitch VOD 或本地媒体到剪辑/字幕/缩略图的全流程编排（下载/转写/选段/渲染/导出）。
- 不负责：守护式录制（由 stream_monitor 负责）、UI 事件处理、第三方模型下载。

## 2) Inputs
- CLI 参数：`--url`, `--out-dir`, `--cfg`, 可选 `--no-chat`, `--no-clip`.
- 配置文件：YAML 覆盖处理选项（模型大小、选段规则、渲染模板等）。
- 前置资源：ffmpeg、TwitchDownloaderCLI（用于下载 VOD/弹幕）、可用磁盘空间。
- 详细字段与约束：见 `contract_input.md`。

## 3) Outputs
- 媒体与数据：剪辑视频、字幕文件、评分/选段 JSON、缩略图（如启用）。
- 目录结构：默认落在 `runs/out/<vod_id>/...` 或 `--out-dir` 指定路径。
- 稳定性：输出文件命名包含源标识与阶段后缀；关键 JSON/SRT 需携带 `schema_version`。
- 详情：见 `contract_output.md`。

## 4) Process
1) 解析参数与配置，合并优先级（CLI > cfg > defaults）。
2) 下载或定位媒体；可选抓取 chat（TwitchDownloaderCLI）。
3) 抽取音频 → 转写（调用 transcribe_audio）→ 评分/选段。
4) 渲染剪辑与字幕，生成缩略图（可选）。
5) 写出产物并更新索引/日志；返回执行状态。

## 5) Configuration
- `download.retries`, `download.chat`: 控制 VOD/弹幕下载。
- `transcribe.model_size`, `transcribe.language`, `transcribe.device`: 透传到转写步骤。
- `selection.strategy`, `selection.min_score`: 选段策略。
- `render.template`, `render.codec`, `render.fps`: 渲染参数。
- `output.out_dir`, `output.naming`: 输出目录与命名规则。

## 6) Performance Budget
- 单 VOD 60 分钟应在 GPU 场景下 20 分钟内完成（含下载）；如超出需在 spec 中记录。
- 并发下载/处理需限制线程，避免 I/O 争用。

## 7) Error Handling
- 下载失败：重试后失败则返回非零，记录 URL 与返回码。
- 转写/渲染失败：保留部分中间产物并写日志；整体失败返回非零。
- 配置非法：在输入校验阶段直接报错终止。

## 8) Edge Cases
- 无网络或无 Twitch 凭证：允许处理本地文件；下载路径需跳过。
- VOD 下架/版权限制：早期检测并报错。
- 超长路径或磁盘不足：提前检查并提示。

## 9) Acceptance Criteria
- AC-CP-001 参数合并：Given CLI 提供 out-dir 与 cfg，When 运行，Then out-dir 以 CLI 为准且记录生效路径。
- AC-CP-002 输出结构：Given 成功运行，When 检查输出目录，Then 存在 clips/subtitles JSON/SRT 且包含 schema_version。
- AC-CP-003 失败路径：Given 下载失败，When 重试耗尽，Then 返回非零并记录 URL 与返回码。

示例输入：`acfv clip --url https://www.twitch.tv/videos/123 --out-dir runs/out --cfg var/settings/pipeline.yaml`

示例输出：`runs/out/123/clip_001.mp4`, `runs/out/123/clip_001.srt`, `runs/out/123/segments.json`

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
