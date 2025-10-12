#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本 - 无控制台版本
用于将 Interest Rating 项目打包成独立的可执行文件
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path

def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"🧹 清理目录: {dir_name}")
            shutil.rmtree(dir_name)

def create_spec_file():
    """创建PyInstaller spec配置文件"""
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# 数据文件
datas = [
    ('icon.png', '.'),
    ('config.py', '.'),
    ('gui_config.json', '.'),
    ('pr_style.qss', '.'),
    ('vscode_style.qss', '.'),
    ('nltk_data', 'nltk_data'),
    ('pyannote_models', 'pyannote_models'),
    ('checkpoints', 'checkpoints'),
    ('save', 'save'),
]

# 隐藏导入
hiddenimports = [
    'torch',
    'torchvision',
    'torchaudio',
    'transformers',
    'nltk',
    'sklearn',
    'faiss',
    'sentence_transformers',
    'librosa',
    'pydub',
    'soundfile',
    'cv2',
    'moviepy',
    'numpy',
    'pandas',
    'scipy',
    'requests',
    'urllib3',
    'PIL',
    'tqdm',
    'whisper',
    'pyannote.audio',
    'pyannote.core',
    'yaml',
    'colorlog',
    'joblib',
    'dateutil',
    'cryptography',
    'rarfile',
    'psutil',
    'memory_profiler',
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.sip',
]

# 排除模块
excludes = [
    'matplotlib',
    'jupyter',
    'notebook',
    'IPython',
    'pytest',
    'unittest',
    'doctest',
    'pdb',
    'tkinter',
    'turtle',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='InterestRating',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.png',  # 应用图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='InterestRating',
)
'''
    
    with open('InterestRating.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("📝 已创建 InterestRating.spec 配置文件")

def run_pyinstaller():
    """运行PyInstaller打包"""
    try:
        print("🚀 开始PyInstaller打包...")
        cmd = [
            'pyinstaller',
            '--clean',
            '--noconfirm',
            'InterestRating.spec'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode == 0:
            print("✅ PyInstaller打包成功!")
            print("📁 输出目录: dist/InterestRating/")
            print("🎯 主程序: dist/InterestRating/InterestRating.exe")
        else:
            print("❌ PyInstaller打包失败!")
            print("错误输出:")
            print(result.stderr)
            
    except FileNotFoundError:
        print("❌ 错误: 未找到PyInstaller，请先安装:")
        print("pip install pyinstaller")
    except Exception as e:
        print(f"❌ 打包过程中出现错误: {e}")

def create_launcher():
    """创建启动器脚本"""
    launcher_content = '''@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 Interest Rating...
start "" "InterestRating.exe"
'''

    # 使用 UTF-8 BOM (utf-8-sig) 以确保 Windows 资源管理器 & 记事本正确识别为 UTF-8
    with open('dist/InterestRating/启动程序.bat', 'w', encoding='utf-8-sig') as f:
        f.write(launcher_content)
    
    print("📝 已创建启动器脚本: 启动程序.bat")

def create_readme():
    """创建说明文档"""
    readme_content = '''# Interest Rating 程序说明

## 文件说明
- InterestRating.exe - 主程序
- 启动程序.bat - 启动脚本（双击即可运行）

## 运行要求
- Windows 10/11 64位系统
- 无需安装Python环境
- 首次运行可能需要等待几秒钟

## 注意事项
- 程序运行时会在同目录创建logs文件夹存放日志
- 如果遇到问题，请查看logs文件夹中的错误日志
- 建议将整个文件夹复制到其他位置使用

## 技术支持
如有问题请联系开发者
'''
    
    with open('dist/InterestRating/README.txt', 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    print("📝 已创建说明文档: README.txt")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='PyInstaller打包脚本')
    parser.add_argument('--clean', action='store_true', help='清理构建目录')
    parser.add_argument('--spec-only', action='store_true', help='仅创建spec文件')
    parser.add_argument('--build', action='store_true', help='执行完整打包')
    
    args = parser.parse_args()
    
    if args.clean:
        clean_build_dirs()
        return
    
    if args.spec_only:
        create_spec_file()
        return
    
    if args.build:
        print("🔨 开始完整打包流程...")
        clean_build_dirs()
        create_spec_file()
        run_pyinstaller()
        
        # 检查打包是否成功
        if os.path.exists('dist/InterestRating/InterestRating.exe'):
            create_launcher()
            create_readme()
            print("\n🎉 打包完成!")
            print("📁 输出目录: dist/InterestRating/")
            print("🚀 双击 '启动程序.bat' 即可运行程序")
        else:
            print("❌ 打包失败，请检查错误信息")
        return
    
    # 默认执行完整流程
    print("🔨 开始完整打包流程...")
    clean_build_dirs()
    create_spec_file()
    run_pyinstaller()
    
    # 检查打包是否成功
    if os.path.exists('dist/InterestRating/InterestRating.exe'):
        create_launcher()
        create_readme()
        print("\n🎉 打包完成!")
        print("📁 输出目录: dist/InterestRating/")
        print("🚀 双击 '启动程序.bat' 即可运行程序")
    else:
        print("❌ 打包失败，请检查错误信息")

if __name__ == '__main__':
    main()
