# 转录语言配置修复报告

## 问题描述

转录过程中存在以下问题：

1. **语言配置被忽略**：`transcribe_audio.py` 中虽然读取了配置里的 `TRANSCRIPTION_LANGUAGE`，但真正调用 Whisper 时仍然硬编码为 `language='en'`
2. **Fallback 分支缺少词级时间戳**：当第一次调用失败时，简化分支没有开启 `word_timestamps=True`
3. **缺少音频活动兜底**：`_refine_segments_by_speech` 在无语音数据时直接放弃，没有利用音频活动检测
4. **字幕时间轴错位**：缺少词级数据时回退到平均分配，导致时间不准确

## 修复内容

### 1. 修复 Whisper 语言配置 (`src/acfv/processing/transcribe_audio.py`)

**修复前**：
```python
result = whisper_model.transcribe(
    temp_audio_path,
    language='en',  # 硬编码英语
    # ...
)
```

**修复后**：
```python
# 处理语言设置：auto 表示自动检测，None 也表示自动检测
whisper_language = None if transcription_language in ("auto", "None", None) else transcription_language

result = whisper_model.transcribe(
    temp_audio_path,
    language=whisper_language,  # 使用配置的语言或自动检测
    # ...
)
```

### 2. 修复 Fallback 分支缺少词级时间戳

**修复前**：
```python
result = whisper_model.transcribe(
    temp_audio_path,
    language='en',
    fp16=False  # 没有 word_timestamps
)
```

**修复后**：
```python
result = whisper_model.transcribe(
    temp_audio_path,
    language=whisper_language,
    word_timestamps=True,  # 确保 fallback 也有词级时间戳
    condition_on_previous_text=False,
    temperature=0.0,
    fp16=False
)
```

### 3. 添加最终兜底转录调用

新增了第三层兜底，确保即使前两次失败也能得到基本的词级时间戳：

```python
# 最后的兜底：使用最基本参数，但必须保证有 word_timestamps
try:
    result = whisper_model.transcribe(
        temp_audio_path,
        word_timestamps=True  # 即使最简单的调用也要有词级时间戳
    )
except Exception as e3:
    log_error(f"[转录] 所有转录尝试都失败: {e3}")
    return []
```

### 4. 增强语音精修的音频活动兜底 (`src/acfv/features/modules/pipeline_backend.py`)

**修复前**：
```python
else:
    removed += 1
    log_debug(f"未检测到语音，已移除")
    continue
```

**修复后**：
```python
else:
    # 兜底：如果没有转录数据，使用音频活动检测
    if audio_activity and np is not None:
        frame_times = audio_activity["frame_times"]
        active_mask = audio_activity["active_mask"]
        
        # 查找该片段内是否有音频活动
        start_idx = int(np.clip(np.searchsorted(frame_times, seg_start, side="left"), 0, frame_count - 1))
        end_idx = int(np.clip(np.searchsorted(frame_times, seg_end, side="right"), 0, frame_count))
        
        if start_idx < end_idx and start_idx < frame_count:
            segment_activity = active_mask[start_idx:min(end_idx, frame_count)]
            if segment_activity.any():
                # 有音频活动，保留片段
                speech_start = seg_start
                speech_end = seg_end
                log_debug(f"使用音频活动兜底检测，保留")
            else:
                # 完全静音，移除
                removed += 1
                log_debug(f"音频活动检测显示为静音，已移除")
                continue
        # ...
    else:
        # 没有转录数据也没有音频活动数据，按原逻辑移除
        removed += 1
        log_debug(f"未检测到语音且无音频活动数据，已移除")
        continue
```

### 5. 添加转录数据质量检查和日志

```python
# 检查转录数据质量并记录日志
if not speech_segments and not speech_words:
    log_debug("[pipeline] 语音精修：无转录数据，跳过语音精修")
    return segments, 0, 0
elif not speech_words:
    log_debug("[pipeline] 语音精修：缺少词级时间戳数据，字幕时间轴可能不准确，建议检查转录配置")
else:
    log_debug(f"[pipeline] 语音精修：加载了 {len(speech_segments)} 个句子段，{len(speech_words)} 个词")
```

### 6. 字幕生成回退时的日志提醒 (`src/acfv/processing/subtitle_generator.py`)

```python
# Fallback to proportional allocation when word-level data missing
from acfv.main_logging import log_debug
log_debug(f"[字幕] 缺少词级时间戳，回退到平均分配，字幕可能对不上")
```

### 7. 改进字幕生成跳过逻辑的诊断日志

```python
else:
    missing_reason = []
    if not os.path.exists(subtitle_transcription):
        missing_reason.append("转录文件不存在")
    if not clip_files:
        missing_reason.append("无切片文件")
    log_info(f"[pipeline] 跳过字幕生成（{', '.join(missing_reason)}）")
```

## 配置建议

### 配置文件设置 (`var/settings/config.json`)

```json
{
  "TRANSCRIPTION_LANGUAGE": "auto",    # 自动检测，或指定 "zh", "ja", "en" 等
  "NO_SPEECH_THRESHOLD": 0.6,
  "LOGPROB_THRESHOLD": -1.0
}
```

### 语言设置说明

- `"auto"` 或 `null`：让 Whisper 自动检测语言
- `"zh"`：强制使用中文
- `"ja"`：强制使用日文
- `"en"`：强制使用英文
- 其他 ISO 639-1 语言代码

## 测试验证

运行测试脚本验证修复：

```bash
python test_transcription_fix.py
```

预期输出：
- ✅ 配置读取成功
- ✅ Whisper语言参数正确设置
- ✅ 音频活动检测工作正常

## 效果预期

1. **中文/日文等非英语内容**：Whisper 现在会使用正确的语言设置，获得更准确的转录结果
2. **词级时间戳**：所有转录调用（包括 fallback）都会尝试获取词级时间戳
3. **静音片段移除**：即使转录失败，音频活动检测也能帮助移除纯静音片段
4. **诊断日志**：更详细的日志帮助排查转录和字幕生成问题

## 后续建议

1. **引入 Granite 句子切分**：在字幕生成中使用 Granite 模型做句子边界检测，再结合 Whisper 词时间戳
2. **音频质量预检**：在转录前增加音频质量检查，对过于安静的音频给出提示
3. **转录结果验证**：添加转录结果的置信度检查，低置信度时给出警告

## 文件清单

修改的文件：
- `src/acfv/processing/transcribe_audio.py` - 主要修复
- `src/acfv/features/modules/pipeline_backend.py` - 音频活动兜底 + 日志改进  
- `src/acfv/processing/subtitle_generator.py` - 字幕回退日志
- `test_transcription_fix.py` - 测试脚本（新增）