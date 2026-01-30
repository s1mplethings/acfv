# Extract Chat Spec

## 1) Purpose
- 负责：从 Twitch VOD 或录制产物获取弹幕/聊天记录，输出标准 JSON。
- 不负责：视频下载、转写、剪辑。

## 2) Inputs
- VOD URL/ID 或录制目录，输出目录，是否需要清洗/去重。
- TwitchDownloaderCLI 可用，凭证可选（取决于 VOD 权限）。
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- chat JSON 文件（含时间戳、用户名、文本）。
- 可选元数据（总条数、时间范围）。
- 详情：见 `contract_output.md`。

## 4) Process
1) 校验输入 VOD/目录与输出目录。
2) 调用 TwitchDownloaderCLI 下载 chat；可选清洗/排序。
3) 写出 JSON，包含 schema_version。
4) 记录日志并返回路径。

## 5) Configuration
- `out_dir`（默认与视频同目录）
- `clean.enabled`（默认 True）：去重/排序。
- `retries`（默认 2）

## 6) Performance Budget
- 文本下载应随视频长度线性；大直播需注意磁盘空间。

## 7) Error Handling
- URL/目录非法：校验阶段报错。
- CLI 失败：重试；失败记录命令与返回码。
- 写入失败：清理临时文件。

## 8) Edge Cases
- VOD 下架或权限：早期报错。
- 空 chat：允许输出空列表并记录。
- 长路径：处理 `\\?\\`。

## 9) Acceptance Criteria
- AC-EC-001 非法 URL/目录时报错。
- AC-EC-002 输出 JSON 含 schema_version、按时间戳升序。
- AC-EC-003 CLI 失败后重试并记录返回码。

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
