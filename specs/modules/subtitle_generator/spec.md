# Subtitle Generator Spec

## 1) Purpose
- 负责：将转写/分段结果生成字幕文件（SRT/ASS），可含样式和时间戳校准。
- 不负责：转写本身、渲染视频。

## 2) Inputs
- 转写或分段列表（start/end/text/可选 speaker）。
- 输出目录、字幕格式、时间偏移/帧率（可选）。
- 详见 `contract_input.md`。

## 3) Outputs
- 字幕文件（SRT/ASS），命名包含源标识。
- 可选元数据（schema_version、段数）。
- 详见 `contract_output.md`。

## 4) Process
1) 校验输入段落与格式。
2) 按格式生成字幕文本，应用时间偏移或帧率换算（ASS）。
3) 写出文件，返回路径与元数据。

## 5) Configuration
- `format`: `srt|ass`
- `time_offset_sec`: 可正负，默认 0
- `framerate`: 生成 ASS 时可用
- `out_dir`: 默认与源同目录

## 6) Performance Budget
- 线性于段落数；应在几万段内快速完成。

## 7) Error Handling
- 段落缺失必需字段或格式非法：报错。
- 写入失败：记录并返回非零。

## 8) Edge Cases
- 空段落：输出空字幕文件或拒绝，需记录策略。
- 重叠/未排序段：按 start 排序后输出。
- 时间偏移导致负值：裁剪到 0 并记录。

## 9) Acceptance Criteria
- AC-SUB-001 输入校验：缺 start/end/text 报错。
- AC-SUB-002 排序与时间戳：输出按 start 升序，时间偏移生效。
- AC-SUB-003 命名与 schema_version：输出命名包含源标识并写入 schema_version。

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Tasks：`tasks.md`
- Traceability：`traceability.md`
- Tests：`tests/integration/test_spec_presence.py`
