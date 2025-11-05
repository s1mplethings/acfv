#!/usr/bin/env python3
"""
验证英文转录配置
"""

import json
from pathlib import Path
import sys

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

def test_english_config():
    """测试英文转录配置"""
    print("🔍 检查英文转录配置...")
    
    try:
        from acfv.runtime.storage import settings_path
        
        # 读取配置
        with settings_path("config.json").open("r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        transcription_language = config_data.get("TRANSCRIPTION_LANGUAGE", "auto")
        print(f"✅ 当前语言设置: {transcription_language}")
        
        # 模拟转录代码中的语言处理逻辑
        whisper_language = None if transcription_language in ("auto", "None", None) else transcription_language
        print(f"✅ Whisper 将使用语言: {whisper_language}")
        
        if transcription_language == "en":
            print("✅ 配置正确：强制使用英文转录")
            print("   - 这将确保 Whisper 始终以英文模式运行")
            print("   - 适合处理英文视频内容")
            print("   - 可能会提高英文转录的准确性和速度")
        elif transcription_language == "auto":
            print("⚠️  当前设置为自动检测语言")
            print("   - 如果只处理英文内容，建议设置为 'en'")
        else:
            print(f"⚠️  当前设置为: {transcription_language}")
            print("   - 如果只需要英文转录，建议改为 'en'")
            
        return transcription_language
        
    except Exception as e:
        print(f"❌ 配置检查失败: {e}")
        return None

def main():
    print("🚀 英文转录配置验证")
    
    lang = test_english_config()
    
    print("\n📋 总结:")
    if lang == "en":
        print("✅ 已配置为强制英文转录")
        print("✅ 修复后的代码将正确使用英文设置")
    else:
        print("⚠️  如需强制英文转录，请设置配置文件:")
        print('   在 var/settings/config.json 中设置: "TRANSCRIPTION_LANGUAGE": "en"')
    
    print("\n🔧 英文转录的优势:")
    print("   - 更快的处理速度（无需语言检测）")
    print("   - 更准确的英文识别")
    print("   - 更稳定的词级时间戳")
    print("   - 减少非英文误识别")

if __name__ == "__main__":
    main()