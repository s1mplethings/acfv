# Stream Monitor Spec

## 1) Purpose
- 负责：后台轮询 Twitch 频道，自动录制直播，抓取弹幕并落盘；可选触发后续流水线。
- 不负责：剪辑/转写（由 pipeline/processing 负责）、UI 渲染（由 GUI 负责）。

## 2) Inputs
- 配置文件：`var/settings/stream_monitor.yaml`（或 `-c` 指定），包含 targets/interval/paths。
- 外部依赖：ffmpeg、TwitchDownloaderCLI、网络与凭证（Client ID/Token）。
- CLI 参数：`acfv stream-monitor [-c cfg]`.
- 字段与约束：见 `contract_input.md`。

## 3) Outputs
- 录制视频文件（含时间戳命名），默认落在配置指定目录。
- chat JSON（在直播结束后抓取），与视频同目录。
- 日志：`var/logs/stream_monitor.log` 或配置指定路径。
- 详情：见 `contract_output.md`。

## 4) Process
1) 读取配置并校验 targets 列表与输出目录。
2) 轮询直播状态，发现开播后启动录制（ffmpeg/streamlink/streamget），记录进程状态。
3) 直播结束后抓取 chat（TwitchDownloaderCLI），写入 JSON。
4) 可选：调用剪辑流水线或发送通知；循环继续下一次轮询。

## 5) Configuration
- `targets`: 频道/房间列表（必填）。
- `interval_sec`: 轮询周期，默认 60。
- `output_dir`: 录制输出目录。
- `twitch.client_id/token`: API 调用凭证。
- `chat.enabled`: 是否抓取弹幕；`chat.format`: json。
- `postprocess.enabled`: 是否在录制完成后触发 pipeline。

## 6) Performance Budget
- 轮询应在 1s 内完成（不含网络延迟）；录制写盘需保持实时。

## 7) Error Handling
- 配置缺失/非法：启动时直接报错退出。
- 录制失败：重试 N 次；仍失败写日志并返回非零。
- chat 抓取失败：记录错误与返回码，不影响已录制视频文件。

## 8) Edge Cases
- 频道频繁上下线：避免重复启动录制，需状态去抖。
- 磁盘不足：提前检测剩余空间，记录并中止录制。
- 长路径：输出目录需支持 `\\?\\` 前缀。

## 9) Acceptance Criteria
- AC-SM-001 配置校验：Given 缺少 targets，When 启动，Then 报错并退出非零。
- AC-SM-002 命名契约：Given 录制一场直播，When 完成，Then 输出文件名包含频道+时间戳，日志记录路径。
- AC-SM-003 chat 抓取：Given chat.enabled=true，When 直播结束，Then 生成 chat JSON 与视频同目录。

示例输入：`acfv stream-monitor -c var/settings/stream_monitor.yaml`

示例输出：`recordings/<channel>/20240101_120000.mp4`, `recordings/<channel>/20240101_120000_chat.json`

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
