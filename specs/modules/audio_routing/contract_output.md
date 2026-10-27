# Audio Routing - Output Contract

## Guaranteed Outputs
所有输出保存在`workdir/`（由用户指定）

### 1. labeled_segments.json（关键）
**用途**：后续字幕/弹幕生成的唯一输入

**Schema**:
```json
[
  {
    "start": float,       // 开始时间（秒）
    "end": float,         // 结束时间（秒）
    "speaker_id": string, // 说话人ID（spk_0/spk_1...）
    "role": string,       // 角色标签：streamer/tts/game_speech
    "text": string,       // 转录文本
    "words": [            // 可选：词级时间戳
      {"w": string, "s": float, "e": float}
    ]
  }
]
```

**保证**：
- 按时间排序，无重叠
- 每条必有role字段
- role ∈ {streamer, tts, game_speech}

### 2. game_non_speech.json
**用途**：bgm/sfx段，用于弹幕密度调整

**Schema**:
```json
[
  {
    "start": float,
    "end": float,
    "rms_db": float  // 音量dB值
  }
]
```

### 3. speaker_profiles.json
**用途**：说话人角色映射结果

**Schema**:
```json
{
  "spk_0": {"role": "streamer", "score": 0.84},
  "spk_1": {"role": "tts", "score": 0.78}
}
```

### 4. logs.txt
处理日志，包含所有警告和降级信息

## Optional Outputs（debug模式）
- `vad_speech.json`: VAD原始结果
- `diarization.json`: 说话人分离原始结果
- `stems/vocals.wav`: 人声分离结果
- `role_tracks/*.wav`: 各角色音频拼接

## Quality Guarantees
- labeled_segments.json非空（除非输入视频无音频）
- 时间戳精度：± 50ms
- 角色分类准确率：>80%（提供refs时）
