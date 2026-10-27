# Audio Routing - Input Contract

## Required Inputs
- `input.mp4`: 输入视频文件（支持常见格式：mp4/mkv/avi/flv）
- `config/audio_routing.yaml`: 配置文件

## Optional Inputs（强烈推荐）
- `refs/streamer.wav`: 主播参考音频（10-60秒干净录音）
- `refs/tts.wav`: TTS参考音频（10-60秒）
- `refs/game_speech.wav`: 游戏角色对白参考音频（10-60秒）

## Input Validation
- input.mp4必须包含音频轨
- 参考音频格式：WAV/MP3，至少10秒
- config文件必须符合schema（详见spec.md）

## Fallback Behavior
- 缺少refs：使用默认角色映射（所有非主播/TTS段标记为game_speech）
- config缺失：使用默认配置值
