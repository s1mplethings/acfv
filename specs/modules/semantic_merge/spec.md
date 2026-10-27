# Semantic Merge Spec

## 1) Purpose
- 负责：根据转录文本的语义相似度，将原始短片段拼接成 4–5 分钟左右的连续语义段。
- 不负责：评分/渲染/字幕生成。

## 2) Inputs
- 转录片段（start/end/text）。
- 可选：评分/候选片段（用于为语义段聚合评分）。
- 详细字段：见 `contract_input.md`。

## 3) Outputs
- 合并后的语义段列表（按时间升序）。
- 详情：见 `contract_output.md`。

## 4) Process
1) 读取转录片段并按 start 升序排序。
2) 计算相邻片段语义相似度（TF-IDF 优先，失败则 BOW）。
3) 满足以下条件则切块：间隔超过阈值 / 达到最大时长 / 接近目标且相似度不足。
4) 为语义段聚合评分（从候选段覆盖内取平均），无评分则用时长作为兜底。

## 5) Configuration
- `SEMANTIC_SEGMENT_MODE`：是否启用（默认 true）。
- `SEMANTIC_TARGET_DURATION`：目标时长（秒，默认 240）。
- `MIN_TARGET_CLIP_DURATION`：最小窗口下限（默认 180 秒）。  
- `MIN_CLIP_DURATION` / `MAX_CLIP_DURATION`：最小/最大时长约束（最终最小值会被提升到 `MIN_TARGET_CLIP_DURATION`）。  
- 语义相似度不足时，已达到最小窗口即可切块（语义权重更高，避免机械固定时长）。
- `SEMANTIC_SIMILARITY_THRESHOLD`：相似度阈值（默认 0.75）。
- `SEMANTIC_MAX_TIME_GAP`：允许最大间隔（默认 60s）。
- `SEMANTIC_STICKINESS_SEC`：语义粘性窗口（默认 60s），达到最小时长后仍会继续合并的缓冲时间。
- `SEMANTIC_MIN_TEXT_CHARS`：语义段最小有效字符数（默认 20；不足会被剔除或降权）。
- `SEMANTIC_MIN_TEXT_PER_SEC`：每秒最小有效字符数（默认 0.2；与上项取更高要求）。

## 6) Performance Budget
- O(n) 线性合并，文本向量化 O(n * vocab)。

## 7) Error Handling
- 转录为空：直接透传候选段（若有）。
- 相似度计算失败：回退到词袋余弦。

## 8) Edge Cases
- 极长静默：会在 max_gap 处切块。
- 文本为空/有效字符过少：该片段被跳过。
- 无评分输入：score 退化为段时长。

## 9) Acceptance Criteria
- AC-SM-001：输入转录为空时，不崩溃，输出为空或透传。
- AC-SM-002：输出按时间升序，窗口时长接近目标。
- AC-SM-003：相似度不足时会断开合并。

## 10) Trace Links
- Contracts：`contract_input.md`, `contract_output.md`
- Traceability：`traceability.md`
