# PATCH 指导文件：主播字幕（细切分 + 时间轴对齐）SRT/ASS

> 目的：在现有 run/work 产物基础上导出 **仅主播** 字幕，切分更自然、时间更贴近发声边界。  
> 范围：新增字幕导出 step + 配置 + GUI 开关 + 最小单测。

## 0) 任务标题
主播字幕（细切分 + 时间轴对齐）SRT/ASS

## 1) 目标（可验收）
- 在现有 ACFV pipeline 中新增主播字幕导出步骤。
- 输入：`work/transcription.json` + `work/speaker_separation/speaker_separation_result.json`
- 输出：  
  - `work/subtitles_streamer.srt`  
  - `work/subtitles_streamer.ass`
- 生成细切分字幕（更像人工剪辑）。
- 时间轴更贴近真实发声（lead-in/out 微调）。
- GUI 有明确开关入口。

## 2) 影响范围（模块/文件）
**允许改动：**
- `src/acfv/steps/subtitle_generator/`（新增 streamer_subtitles step）
- `src/acfv/modular/plugins/streamer_subtitles.py`（串入 pipeline）
- `src/acfv/modular/pipeline.py`（参数透传）
- `src/acfv/ui/enhance_panel.py`（GUI 开关）
- `src/acfv/config/_config_impl.py`（默认配置）
- `tests/unit/`（最小单测）
- `specs/modules/streamer_subtitles/*`
- `docs/repo_map.md`

**不允许改动：**
- CLI 参数与输出路径（保持不变）
- 既有 clip/manifest 的命名规则

## 3) 兼容要求（OS/CLI/输出目录）
- OS：Windows + *nix
- CLI：保持 `python -m acfv.cli pipeline ...` 行为不变
- 输出目录：固定写到 `runs/<job>/work/`

## 4) 依赖建议（可选）
> 以下库为“更精准对齐/更强切分”可选项，本 patch 以 **无新增依赖** 的内建实现为默认。

字幕读写：
```
https://github.com/tkarabela/pysubs2
```

词级时间戳（可选三选一/可叠加）：
```
https://github.com/m-bain/whisperX
https://github.com/jianfch/stable-ts
https://github.com/linto-ai/whisper-timestamped
```

VAD（可选二选一）：
```
https://github.com/snakers4/silero-vad
https://github.com/wiseman/py-webrtcvad
```

强制对齐（可选）：
```
https://github.com/MahmoudAshraf97/ctc-forced-aligner
```

## 5) 输入/输出约定（run/work）
**输入：**
- `work/transcription.json`（转写结果）
- `work/speaker_separation/speaker_separation_result.json`（说话人分段 + host_speaker）

**输出：**
- `work/subtitles_streamer.srt`
- `work/subtitles_streamer.ass`
- `work/subtitles_streamer.debug.json`（可选）

## 6) 主播识别策略（MVP）
- 优先使用 `host_speaker`。
- 否则选择“说话时间最长”的 speaker。
- 允许配置覆盖：`STREAMER_PRIMARY_SPEAKER=...`

## 7) 切分策略（细切分）
**基本配置：**
- `max_chars_per_line = 16`
- `max_lines = 2`
- `target_duration = 1.6s`
- `min_duration = 0.7s`
- `max_duration = 3.2s`
- `pause_split = 0.28s`

**逻辑：**
- 先将主播词流提取出来（词级优先；否则按段内均分）
- 采用“贪心 + 边界评分”切分

## 8) 时间轴对齐（基础版）
- 统一 lead-in/out 微调：
  - `start = start - 0.12s`
  - `end = end + 0.06s`
- 保证时间单调（不倒退）

## 9) Pipeline 接入
- 模块：`streamer_subtitles`
- 位置：`transcribe_audio` + `speaker_separation` 之后、`render_clips` 之前
- 输出：写入 `work/subtitles_streamer.*`

## 10) 配置项（新增/默认）
```yaml
ENABLE_STREAMER_SUBTITLES: false
STREAMER_PRIMARY_SPEAKER: ""
STREAMER_SUB_MAX_CHARS: 16
STREAMER_SUB_MAX_LINES: 2
STREAMER_SUB_TARGET_DUR: 1.6
STREAMER_SUB_MIN_DUR: 0.7
STREAMER_SUB_MAX_DUR: 3.2
STREAMER_SUB_PAUSE_SPLIT: 0.28
```

## 11) 测试（最小单测）
- 构造：转写段 + 说话人分段
- 断言：
  - SRT/ASS 均生成
  - start < end 且单调
  - 仅主播词流

## 12) 量化 DoD
- 改动文件数 ≤ 10
- 新增/删除代码行数 ≤ 必要最小
- 新增功能有 unit test
- `verify` 通过

## 13) 验收方式（verify）
```bash
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

## 14) 回滚
- `git apply -R patch.diff`
