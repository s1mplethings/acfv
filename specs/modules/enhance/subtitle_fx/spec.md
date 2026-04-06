# Subtitle FX (字幕特效) Spec

## 1) Purpose
- 负责：生成带特效的ASS字幕文件（POP/COLOR/SHAKE等）。
- 不负责：ASR转写、视角切换、渲染。

## 2) Inputs
- `segments.json`（来自ASR模块）
- 关键词配置（regex/boost权重）
- 字幕风格配置（style_profiles.yaml）
- 详见 `contract_input.md`

## 3) Outputs
- `subtitles.ass`：包含基础样式 + 特效标签的ASS文件
- `subtitle_events.json`（可选）：特效事件列表供timeline汇总
- 详见 `contract_output.md`

## 4) Process
1) 加载segments.json和风格配置
2) 按分句规则调整换行（中文12-18字/行，插入\N）
3) 检测关键词（regex匹配），注入特效标签：
   - POP：`{\fscx120\fscy120\t(\fscx100\fscy100)}`
   - COLOR：`{\c&H0000FF&}`（蓝色示例）
   - SHAKE（可选）：`{\move(x,y,x+2,y-2,0,50)}`
4) 使用pysubs2生成.ass文件
5) 验证时间轴不重叠

## 5) Configuration
- `style_profile`: clean / bold_outline / meme_heavy
- `max_line_chars`: 18（中文）/ 40（英文）
- `min_segment_duration`: 0.8秒
- `keyword_fx_rules`: [{regex, fx_type, priority}]

## 6) Performance Budget
- 1000条字幕：< 5秒生成时间
- 输出文件大小：< 500KB（纯文本）

## 7) Error Handling
- segments.json缺失：报错退出
- 风格配置不存在：使用默认clean风格
- 关键词regex错误：跳过该规则并记录

## 8) Edge Cases
- 空segments：生成空.ass文件但保留样式定义
- 时间戳重叠：按start排序并调整end避免重叠
- 超长句子（>60字）：强制分行或截断

## 9) Acceptance Criteria
- AC-SUBFX-001 ASS格式校验：输出文件可被ffmpeg/libass解析
- AC-SUBFX-002 特效注入：关键词匹配时正确添加fx标签
- AC-SUBFX-003 时间轴稳定：字幕start/end递增且不重叠

## 10) Trace Links
- Contracts: `contract_input.md`, `contract_output.md`
- Implementation: `src/acfv/enhance/subtitle/ass_builder.py`
- Tests: `tests/integration/test_subtitle_fx.py`
