# Twitch Downloader Spec

## 1) Purpose
- 负责：下载 Twitch VOD 视频与 chat，保存到指定目录，可供后续处理。
- 不负责：转写、剪辑、评分、渲染。

## 2) Inputs
- VOD URL 或 ID，输出目录，凭证（Client ID/Token）。
- 配置：重试次数、并发、chat 下载开关。
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- 下载的视频文件（mp4/ts），命名包含 VOD ID。
- chat JSON（可选）。
- 日志记录下载命令与返回码。
- 详情见 `contract_output.md`。

## 4) Process
1) 校验 URL/ID 与输出目录。
2) 调用 TwitchDownloaderCLI 进行视频与 chat 下载（可独立开关）。
3) 校验文件存在性与大小>0；失败则重试。
4) 写日志并返回产物路径。

## 5) Configuration
- `retries`（默认 2）、`concurrency`（默认 1）
- `download_chat`（bool，默认 True）
- `out_dir`（默认 `processing/downloads`）

## 6) Performance Budget
- 单 VOD 下载时间依赖网络；重试总时间需受限（重试间隔/次数）。

## 7) Error Handling
- URL/ID 非法：校验阶段报错。
- CLI 失败：记录命令、返回码、stderr，重试后仍失败返回非零。
- 输出不可写：提前报错。

## 8) Edge Cases
- VOD 下架/权限不足：早期检测并报错。
- 中断或部分下载：清理半成品文件。
- 长路径：处理 `\\?\\` 前缀。

## 9) Acceptance Criteria
- AC-TD-001 输入校验：非法 URL/ID 时拒绝并报错。
- AC-TD-002 输出存在性：成功后视频与 chat（若启用）文件存在且大小>0。
- AC-TD-003 失败重试：CLI 失败后按 retries 重试并在日志中反映。

示例输入：`{"url":"https://www.twitch.tv/videos/123","out_dir":"processing/downloads","download_chat":true}`

示例输出：`processing/downloads/123.mp4`, `processing/downloads/123_chat.json`

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
