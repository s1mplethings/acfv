# Render Clips Spec（渲染/导出）

## Purpose
将候选段（或选定段）渲染成视频剪辑、字幕、缩略图，并生成剪辑清单（manifest）以便回溯、对比与排障。

## Inputs
- source media file（视频/音频）
- segments candidates（`specs/contract_output/segments.schema.json`）或其子集
- render config：输出目录、编码参数、字幕格式等
  - 目标时长：MIN/TARGET/MAX = 240/270/300 秒（4~5 分钟窗口）
  - 最短片段：>= 6 秒（分析阶段已过滤；渲染阶段再防御性过滤）
  - 必须在输入前剔除纯音乐/带语音的音乐段（可通过 `reason_tags`/空文本判断）

## Outputs
- clips（视频文件）
- subtitles（srt/ass 等）
- thumbnails（可选）
- clips manifest：遵循 `specs/contract_output/clips_manifest.schema.json`

## Naming（必须固定）
命名必须可预测且可回溯，建议：
- `clip_{rank:03d}_{HHhMMmSSs}_{start_ms}-{end_ms}.mp4`（含高光起点时间标签）
- 同名派生：`.srt` / `.ass` / `.jpg`
manifest 必须记录：
- 输入段（start/end/score/rank）
- 输出文件相对路径
- 生成时间/工具版本（若可用）

## Atomic Write（必须）
- 任何输出文件必须采用：写入 `*.tmp` →（可选 fsync）→ rename
- manifest 写入也必须原子写（避免半写导致下游读取失败）

## Process（建议）
1) 读取 candidates 并选出渲染列表（按 rank 或阈值）
2) 对每段调用 ffmpeg（或库）渲染
3) 生成缩略图（可选）
4) 写出 manifest（包含所有 clip 映射）
5) 若某 clip 失败：记录命令与返回码；整体策略（fail-fast 或 partial）需在 config 中声明

## Error Handling
- ffmpeg 不存在/不可执行：立即失败（verify/CI 可提前检测）
- 单个 clip 渲染失败：必须记录“命令+返回码+stderr 摘要”，并在 manifest 中标记（或不写入该 clip；策略需声明）

## Acceptance Criteria (AC)
- AC-1（manifest 可回溯）：Given 1 个候选段 When render_clips Then 输出至少包含 1 个 video 文件与 1 个 manifest；manifest 中能映射到该 video 的相对路径。
- AC-2（命名稳定）：Given 相同输入 When render_clips 运行两次 Then 输出文件名与 manifest 内容一致（除 created_at 等明确允许变化字段）。
