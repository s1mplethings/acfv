# Enhance / TTS Spec

## Purpose
提供“当前 TTS（edge-tts） vs VibeVoice”的可重复 A/B 试验入口，帮助在本地项目内快速比较听感与稳定性。

## Inputs
- `text`: 待合成文本（建议 1~3 句）
- `config.TTS_CURRENT_*`: 当前引擎参数（voice/rate/pitch）
- `config.TTS_VIBEVOICE_*`: VibeVoice 参数（base_url/api_key/model/voice/format/timeout）
- `out_dir`: 输出目录（默认 `work/tts_compare/`）

## Outputs
- `tts_current_edge_<ts>.mp3`
- `tts_vibevoice_<ts>.<format>`
- `tts_compare_report_<ts>.json`:
  - 每个后端是否成功
  - 输出文件路径与字节数
  - 生成耗时
  - 错误信息（若失败）

## Process
1. 校验输入文本与必要配置。
2. 调用 `edge-tts` 生成当前版本音频。
3. 调用 OpenAI-compatible `/audio/speech` 接口生成 VibeVoice 音频。
4. 写入统一 JSON 报告并返回 GUI 状态摘要。

## Config
- `TTS_CURRENT_VOICE`
- `TTS_CURRENT_RATE`
- `TTS_CURRENT_PITCH`
- `TTS_VIBEVOICE_BASE_URL`
- `TTS_VIBEVOICE_API_KEY`
- `TTS_VIBEVOICE_MODEL`
- `TTS_VIBEVOICE_VOICE`
- `TTS_VIBEVOICE_FORMAT`
- `TTS_VIBEVOICE_TIMEOUT_SEC`
- `TTS_AB_TEST_TEXT`

## Acceptance Criteria
- GUI “字幕预览/渲染”页可一键触发 TTS A/B。
- 至少一个后端成功时，报告文件可生成且含有效路径字段。
- 任一后端失败不影响另一后端执行，错误写入报告。
- 不改变现有 clip pipeline/CLI 默认行为与输出路径。

