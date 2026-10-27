# Audio Routing & Transcription Spec

## 1) Purpose
- 负责：对输入视频进行音频分流和标注转录，区分不同音频来源（主播/TTS/游戏对白/游戏背景音）
- 输出：结构化的带角色标签转录段，供后续字幕/弹幕生成使用
- 不负责：字幕/弹幕文件生成、画面ROI、自动放大切换、RAG推荐

## 2) Inputs
- `input.mp4`：输入视频文件
- `refs/streamer.wav`：主播参考音频（10-60秒，可选但推荐）
- `refs/tts.wav`：TTS参考音频（10-60秒，可选但推荐）
- `refs/game_speech.wav`：游戏角色对白参考音频（10-60秒，可选）
- `config/audio_routing.yaml`：配置文件

## 3) Outputs
### 必须输出（work/目录）
- `work/audio.wav`：提取的音频（16kHz mono）
- `work/stems/vocals.wav`、`work/stems/no_vocals.wav`：人声/伴奏分离（若启用demucs）
- `work/vad_speech.json`：语音活动检测结果
- `work/diarization.json`：说话人分离结果
- `work/speaker_profiles.json`：说话人角色映射
- `work/labeled_segments.json`：**最终输出** - 带角色标签的转录段
- `work/game_non_speech.json`：游戏非语音段（bgm/sfx）
- `work/logs.txt`：处理日志

### 可选输出（debug）
- `work/role_tracks/streamer.wav`、`tts.wav`、`game_speech.wav`：各角色语音拼接
- `work/game_non_speech.wav`：bgm/sfx拼接导出

## 4) Process
### Step 1 - 音频抽取
- FFmpeg从input.mp4提取work/audio.wav：pcm_s16le, 16kHz, mono

### Step 2 - Stem分离（可选但推荐）
- Demucs分离vocals.wav（人声）和no_vocals.wav（背景）
- 降级策略：失败时vocals=audio, no_vocals=audio，并记录日志

### Step 3 - VAD（语音活动检测）
- Silero VAD在vocals.wav上检测语音区间
- 合并与清洗规则：
  - min_speech_sec < 0.25s的丢弃或并入
  - merge_gap_sec < 0.20s的合并
- 输出vad_speech.json（排序、无重叠）

### Step 4 - Diarization（说话人分离）
- pyannote.audio对vocals.wav进行说话人分离
- 强制对齐到VAD结果（取交集）
- 降级策略：失败时生成单speaker覆盖全部VAD区间

### Step 5 - 角色映射
- Resemblyzer提取每个speaker的embedding
- 与参考音频计算余弦相似度
- 决策规则：
  - sim(streamer) >= thr_streamer且最大 → role=streamer
  - sim(tts) >= thr_tts且最大 → role=tts
  - sim(game) >= thr_game且最大 → role=game_speech
  - 其他 → role=game_speech（默认兜底）

### Step 6 - 转录（WhisperX）
- 对每个语音段转录（长段按20s切分）
- 输出labeled_segments.json，包含：
  - start/end/speaker_id/role/text
  - words[]（词级时间戳，可选）

### Step 7 - 游戏非语音检测
- 计算no_vocals.wav的短时RMS
- 候选区间：rms_db >= thr_game_bgm_db
- 减去所有VAD区间
- 合并碎片（min_bgm_sec, merge_gap_bgm_sec）
- 输出game_non_speech.json

## 5) Configuration
```yaml
use_demucs: true

vad:
  min_speech_sec: 0.25
  merge_gap_sec: 0.20

diarization:
  enabled: true

role_mapping:
  thr_streamer: 0.75
  thr_tts: 0.75
  thr_game: 0.72
  default_role: game_speech

asr:
  max_asr_sec: 20.0
  language: auto

game_non_speech:
  thr_game_bgm_db: -28.0
  min_bgm_sec: 0.40
  merge_gap_bgm_sec: 0.20
```

## 6) Dependencies
- FFmpeg：音频抽取
- Demucs：人声/伴奏分离
- Silero VAD：语音活动检测
- pyannote.audio：说话人分离
- Resemblyzer：说话人embedding
- WhisperX：语音转录

## 7) Data Structures
### vad_speech.json
```json
[
  {"start": 12.30, "end": 15.80},
  {"start": 16.10, "end": 18.40}
]
```

### diarization.json
```json
[
  {"start": 12.30, "end": 15.80, "speaker_id": "spk_0"},
  {"start": 16.10, "end": 18.40, "speaker_id": "spk_1"}
]
```

### speaker_profiles.json
```json
{
  "spk_0": {"role": "streamer", "score": 0.84},
  "spk_1": {"role": "tts", "score": 0.78},
  "spk_2": {"role": "game_speech", "score": 0.62}
}
```

### labeled_segments.json（关键输出）
```json
[
  {
    "start": 12.30,
    "end": 15.80,
    "speaker_id": "spk_0",
    "role": "streamer",
    "text": "我们继续下一关",
    "words": [{"w":"我们","s":12.40,"e":12.55}]
  }
]
```

### game_non_speech.json
```json
[
  {"start": 0.00, "end": 1.20, "rms_db": -18.2},
  {"start": 5.10, "end": 9.80, "rms_db": -14.6}
]
```

## 8) CLI Interface
```bash
audio_route_transcribe \
  --input input.mp4 \
  --workdir runs/run_001/work \
  --refs refs/ \
  --config config/audio_routing.yaml
```

## 9) Error Handling
- refs不全：可运行，但在logs提示"缺少参考音频，映射可能降级"
- demucs失败：降级为vocals=audio, no_vocals=audio
- diarization失败：生成单speaker覆盖全部VAD区间
- 任何失败都必须输出labeled_segments.json（即使role粗糙）

## 10) Performance Budget
- 音频抽取：< 5秒（1小时视频）
- Demucs分离：~30秒-2分钟（取决于GPU）
- VAD：< 10秒
- Diarization：~1-3分钟（取决于时长）
- 转录：~音频时长的10-30%（GPU加速）
- 总体：1小时视频 < 10分钟处理时间

## 11) Acceptance Criteria
- AC-AR-001：labeled_segments.json中每条都有role ∈ {streamer, tts, game_speech}
- AC-AR-002：game_non_speech.json存在且能覆盖明显bgm/sfx段
- AC-AR-003：提供refs时，至少80%的主播段正确标记为streamer
- AC-AR-004：时间轴无重叠、排序正确
- AC-AR-005：任意模块失败时有降级输出

## 12) Trace Links
- Implementation: `src/acfv/audio_routing/`
- Tests: `tests/integration/test_audio_routing.py`
- Config: `config/audio_routing.yaml.example`
- CLI: `src/acfv/cli/audio_routing.py`

## 13) Interface Contract for Next Patch
下一个功能（字幕/弹幕生成）只允许依赖：
- `work/labeled_segments.json`（必须）
- `work/game_non_speech.json`（可选，用于弹幕密度调整）
- `work/speaker_profiles.json`（可选）

**禁止**重新做ASR/diarization，避免重复计算和不一致。
