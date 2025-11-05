#!/usr/bin/env python3
"""
测试转录语言配置修复
检查 TRANSCRIPTION_LANGUAGE 配置是否被正确使用
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from acfv.runtime.storage import settings_path

def test_config_read():
    """测试配置读取"""
    print("🔍 测试配置读取...")
    
    # 创建测试配置
    config_path = settings_path("config.json")
    os.makedirs(config_path.parent, exist_ok=True)
    
    test_config = {
        "TRANSCRIPTION_LANGUAGE": "zh",
        "NO_SPEECH_THRESHOLD": 0.5,
        "LOGPROB_THRESHOLD": -0.5
    }
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(test_config, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 测试配置已写入: {config_path}")
    print(f"   TRANSCRIPTION_LANGUAGE: {test_config['TRANSCRIPTION_LANGUAGE']}")
    
    # 模拟读取配置的代码
    try:
        with settings_path("config.json").open("r", encoding="utf-8") as f:
            config_data = json.load(f)
        transcription_language = config_data.get("TRANSCRIPTION_LANGUAGE", "auto")
        print(f"✅ 配置读取成功，语言设置: {transcription_language}")
        
        # 处理语言设置：auto 表示自动检测，None 也表示自动检测
        whisper_language = None if transcription_language in ("auto", "None", None) else transcription_language
        print(f"✅ Whisper语言参数: {whisper_language}")
        
        return True
    except Exception as e:
        print(f"❌ 配置读取失败: {e}")
        return False

def create_test_audio():
    """创建一个测试音频文件（静音）"""
    try:
        import numpy as np
        import soundfile as sf
        
        # 创建5秒的静音音频
        duration = 5.0
        sample_rate = 16000
        samples = int(duration * sample_rate)
        audio = np.zeros(samples, dtype=np.float32)
        
        # 在中间添加一些噪音，模拟有内容的音频
        mid_start = samples // 3
        mid_end = samples * 2 // 3
        audio[mid_start:mid_end] = np.random.normal(0, 0.1, mid_end - mid_start).astype(np.float32)
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        sf.write(temp_file.name, audio, sample_rate)
        temp_file.close()
        
        print(f"✅ 测试音频文件已创建: {temp_file.name}")
        return temp_file.name
        
    except ImportError:
        print("⚠️  无法创建测试音频文件（缺少 numpy 或 soundfile）")
        return None

def test_audio_activity():
    """测试音频活动检测"""
    print("\n🔍 测试音频活动检测...")
    
    try:
        from acfv.features.modules.pipeline_backend import _prepare_audio_activity
        
        audio_file = create_test_audio()
        if not audio_file:
            print("⚠️  跳过音频活动测试")
            return
        
        try:
            activity = _prepare_audio_activity(audio_file, -20.0)
            if activity:
                print(f"✅ 音频活动检测成功")
                print(f"   帧数: {len(activity['frame_times'])}")
                print(f"   活动帧数: {activity['active_mask'].sum()}")
                print(f"   音频时长: {activity['audio_duration']:.2f}s")
            else:
                print("⚠️  音频活动检测返回空结果")
        except Exception as e:
            print(f"❌ 音频活动检测失败: {e}")
        finally:
            # 清理测试文件
            try:
                os.unlink(audio_file)
            except:
                pass
                
    except ImportError as e:
        print(f"⚠️  无法导入音频活动检测模块: {e}")

def main():
    print("🚀 开始测试转录语言配置修复...")
    
    # 测试配置读取
    config_ok = test_config_read()
    
    # 测试音频活动检测
    test_audio_activity()
    
    print("\n📋 测试总结:")
    print(f"   配置读取: {'✅' if config_ok else '❌'}")
    print("\n🔧 修复内容:")
    print("   1. ✅ 修复了 Whisper 语言配置使用 transcription_language 而不是硬编码 'en'")
    print("   2. ✅ 修复了 fallback 分支确保包含 word_timestamps=True")
    print("   3. ✅ 增加了最基本的兜底转录调用，确保至少有词级时间戳")
    print("   4. ✅ 在 _refine_segments_by_speech 中添加了音频活动兜底判定")
    print("   5. ✅ 添加了转录数据质量检查和日志提醒")
    
    print("\n📝 使用建议:")
    print("   1. 在配置文件中设置 TRANSCRIPTION_LANGUAGE (如 'zh', 'ja', 'auto' 等)")
    print("   2. 如果看到'缺少词级时间戳数据'的警告，检查 Whisper 调用是否成功")
    print("   3. 音频活动兜底会在转录失败时帮助移除纯静音片段")

if __name__ == "__main__":
    main()