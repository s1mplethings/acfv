# Analyze Segments Spec（分段/评分/选段 / 切片）

## Purpose
从转写/弹幕/情绪等中间件生成“候选片段列表”，用于后续渲染剪辑。该模块**只负责选段与排序，不负责渲染**（见架构表）。

## Inputs
- transcription JSON：来自 `steps/transcribe_audio`（需要可用的时间戳、已排序的 segments）
- optional chat JSON：弹幕/评论
- optional features：情绪、音量峰值、关键词等

## Outputs
- candidates/segments JSON：遵循 `specs/contract_output/segments.schema.json`

## Config（默认建议）
- `units`: 固定为 `ms`
- `min_duration_ms`: 6000
- `max_duration_ms`: 60000
- `merge_gap_ms`: 800
- `allow_overlap`: false
- `clamp_to_duration`: true
- `max_segments`: 30
- `sort`: `score_desc_start_ms_asc_end_ms_asc`
- `seed`（可选）：当涉及随机性时必须提供

## Process（建议实现步骤）
1) 读取转写与可选信号（chat/features）
2) 生成初始候选段（基于句子/停顿/说话人变化等）
3) 评分：产出 `score` 与 `reason_tags`
4) 过滤：按 min/max 时长、黑名单规则等
5) 合并：相邻 gap <= merge_gap_ms 时合并（需更新 score/标签策略）
6) 去重/处理重叠：
   - 默认 `allow_overlap=false`：按 score 优先保留，冲突段剔除或合并（策略必须写入 policy）
7) 归一化与裁剪：若 `clamp_to_duration=true`，将 start/end clamp 到 [0, video_duration_ms]
8) 确定性排序并写出：
   - `score desc`，tie-break：`start_ms asc`，再 `end_ms asc`
9) 原子写：写入 tmp 文件后 rename

## Error Handling（必须）
- 转写缺失/不可解析：返回空 segments（`segments=[]`），并记录清晰日志；CLI/守护返回非零 exit code。
- 转写为空（无有效段）：输出合法的空 JSON（schema_version 等字段齐全），并记录“no segments”原因；禁止写出 2 bytes 空文件。

## Edge Cases
- 极短视频：可能无满足 min_duration 的候选段 → 空输出（合法）
- 视频时长未知：不做 duration 边界校验，但仍需 start/end 非负且 start<end
- 非确定性特征：必须提供 seed 或可重复的排序策略

## Acceptance Criteria (AC)
- AC-1（空转写）：Given transcription segments 为空 When analyze_segments Then 输出 JSON 合法且 `segments=[]`，包含 `schema_version` 与 `units=ms`，并在日志中给出原因。
- AC-2（排序确定性）：Given 相同输入 When analyze_segments 运行两次 Then 输出 `segments` 顺序一致（同分 tie-break 生效）。
- AC-3（边界裁剪）：Given `video_duration_ms` When 产生越界候选段 Then 输出中的 `end_ms <= video_duration_ms`（当 `clamp_to_duration=true`）。
