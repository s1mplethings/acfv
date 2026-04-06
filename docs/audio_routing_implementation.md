# Audio Routing Module - Implementation Summary

## 已完成功能

### 1. 完整Spec文档
- [specs/modules/audio_routing/spec.md](d:\Cliper\acfv\specs\modules\audio_routing\spec.md)：完整模块规格说明
- [specs/modules/audio_routing/contract_input.md](d:\Cliper\acfv\specs\modules\audio_routing\contract_input.md)：输入契约
- [specs/modules/audio_routing/contract_output.md](d:\Cliper\acfv\specs\modules\audio_routing\contract_output.md)：输出契约

### 2. 核心模块实现（Framework Ready）
所有7个处理步骤均已实现框架代码：

- **Step 1** - [step1_extract.py](d:\Cliper\acfv\src\acfv\audio_routing\step1_extract.py)：FFmpeg音频抽取（已实现）
- **Step 2** - [step2_stems.py](d:\Cliper\acfv\src\acfv\audio_routing\step2_stems.py)：Demucs人声分离（框架+降级）
- **Step 3** - [step3_vad.py](d:\Cliper\acfv\src\acfv\audio_routing\step3_vad.py)：Silero VAD语音检测（框架+合并逻辑）
- **Step 4** - [step4_diarization.py](d:\Cliper\acfv\src\acfv\audio_routing\step4_diarization.py)：pyannote说话人分离（框架+对齐+降级）
- **Step 5** - [step5_role_mapping.py](d:\Cliper\acfv\src\acfv\audio_routing\step5_role_mapping.py)：Resemblyzer角色映射（框架+参考加载）
- **Step 6** - [step6_transcribe.py](d:\Cliper\acfv\src\acfv\audio_routing\step6_transcribe.py)：WhisperX转录（框架+段切分）
- **Step 7** - [step7_game_non_speech.py](d:\Cliper\acfv\src\acfv\audio_routing\step7_game_non_speech.py)：bgm/sfx检测（框架+合并）

### 3. 数据Schema（Pydantic）
[schemas.py](d:\Cliper\acfv\src\acfv\audio_routing\schemas.py) 定义了所有数据结构：
- `VADSegment`：语音活动检测段
- `DiarizationSegment`：说话人分离段
- `SpeakerProfile`：说话人角色映射
- `LabeledSegment`：**关键输出** - 带角色标签的转录段
- `GameNonSpeechSegment`：游戏非语音段
- `AudioRoutingConfig`：完整配置schema

### 4. Pipeline编排
[pipeline.py](d:\Cliper\acfv\src\acfv\audio_routing\pipeline.py)：
- `AudioRoutingPipeline`类：完整7步流程编排
- 自动JSON输出：所有中间结果和最终结果
- 日志记录：详细处理日志到logs.txt
- 降级策略：任何步骤失败都有fallback

### 5. CLI入口（暂时禁用）
[cli/audio_routing.py](d:\Cliper\acfv\src\acfv\cli\audio_routing.py)：
- 命令：`acfv audio_route_transcribe`
- 参数：--input, --workdir, --refs, --config, --verbose
- **注意**：CLI入口因typer类型注解问题暂时在__main__.py中禁用
- **解决方案**：可独立运行 `python -m acfv.cli.audio_routing` 或稍后修复类型注解

### 6. 配置与测试
- [config/audio_routing.yaml.example](d:\Cliper\acfv\config\audio_routing.yaml.example)：完整配置模板
- [tests/unit/test_audio_routing.py](d:\Cliper\acfv\tests\unit\test_audio_routing.py)：单元测试（10个测试用例，已通过）
- [requirements.txt](d:\Cliper\acfv\requirements.txt)：新增依赖（demucs/pyannote.audio/resemblyzer）

## 待完善项（需实际库集成）

以下步骤已有完整框架和降级策略，但需集成实际库：

1. **Demucs集成**（Step 2）：当前为fallback（直接复制）
2. **Silero VAD集成**（Step 3）：当前返回空列表
3. **pyannote.audio集成**（Step 4）：当前使用单speaker降级
4. **Resemblyzer集成**（Step 5）：当前使用默认角色
5. **WhisperX集成**（Step 6）：当前返回空转录
6. **RMS计算**（Step 7）：当前返回空bgm段

**集成优先级**：
- P0（必须）：Step 1（已完成）、Step 6（WhisperX转录）
- P1（推荐）：Step 3（VAD）、Step 4（Diarization）、Step 2（Demucs）
- P2（增强）：Step 5（角色映射）、Step 7（bgm检测）

## 验证状态

✅ **Verify通过**：43 passed, 1 skipped
- 语法检查：通过
- 单元测试：新增10个测试全部通过
- 契约检查：通过

## 使用方法

### 方式1：Python直接调用（推荐）
```python
from pathlib import Path
from acfv.audio_routing.pipeline import AudioRoutingPipeline, load_config

config = load_config(Path("config/audio_routing.yaml"))
pipeline = AudioRoutingPipeline(config, Path("runs/001/work"))
success = pipeline.run(
    input_video=Path("input.mp4"),
    refs_dir=Path("refs/")
)
```

### 方式2：独立CLI（临时方案）
```bash
python -m acfv.cli.audio_routing \
  --input input.mp4 \
  --workdir runs/001/work \
  --refs refs/ \
  --config config/audio_routing.yaml
```

### 方式3：集成到主CLI（待修复）
```bash
# 修复类型注解后可用
acfv audio_route -i input.mp4 -w runs/001/work -r refs/
```

## 输出文件

所有输出保存到 `workdir/`：

- **labeled_segments.json** ⭐ 关键输出，用于后续字幕/弹幕生成
- **game_non_speech.json** ⭐ bgm/sfx段，用于弹幕密度调整
- **speaker_profiles.json**：说话人角色映射
- **vad_speech.json**：VAD原始结果
- **diarization.json**：说话人分离结果
- **audio.wav**：提取的音频
- **stems/vocals.wav, stems/no_vocals.wav**：人声/伴奏分离
- **logs.txt**：处理日志

## 下一步工作

1. **修复CLI类型注解**：audio_routing.py中的Optional类型处理
2. **集成实际库**：按优先级逐步集成各库（WhisperX → VAD → pyannote → ...）
3. **端到端测试**：准备测试视频和参考音频，验证完整流程
4. **性能优化**：GPU加速、并行处理、缓存机制

## 接口约定（给下一个patch）

**下一个功能（字幕/弹幕生成）只允许依赖**：
- `work/labeled_segments.json`（必须）
- `work/game_non_speech.json`（可选）
- `work/speaker_profiles.json`（可选）

**禁止**重新做ASR/diarization，确保单一数据源。
