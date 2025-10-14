#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本 - 适配新文件夹结构
用于将 Interest Rating 项目打包成独立的可执行文件
"""

import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path

def clean_build_dirs(output_name='InterestRating'):
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"🧹 清理目录: {dir_name}")
            shutil.rmtree(dir_name)
    
    # 清理spec文件
    spec_file = f'{output_name}.spec'
    if os.path.exists(spec_file):
        os.remove(spec_file)
        print(f"🧹 清理spec文件: {spec_file}")

def check_files_exist():
    """检查必要文件是否存在"""
    print("🔍 检查必要文件...")
    
    # 必要文件列表
    required_files = [
        'main.py',
        'config.txt',
    ]
    
    # 可选文件列表
    optional_files = [
        'icon.png',
        'pr_style.qss',
        'vscode_style.qss',
    ]
    
    # 必要目录列表
    required_dirs = [
        'modules',
        'processing',
        'config',
        'data',
        'cache',
    ]
    
    # 可选目录列表
    optional_dirs = [
        'nltk_data',
        'pyannote_models',
        'checkpoints',
        'save',
    ]
    
    missing_required = []
    missing_optional = []
    
    # 检查必要文件
    for file_name in required_files:
        if not os.path.exists(file_name):
            missing_required.append(file_name)
        else:
            print(f"✅ 必要文件: {file_name}")
    
    # 检查可选文件
    for file_name in optional_files:
        if not os.path.exists(file_name):
            missing_optional.append(file_name)
        else:
            print(f"✅ 可选文件: {file_name}")
    
    # 检查必要目录
    for dir_name in required_dirs:
        if not os.path.isdir(dir_name):
            missing_required.append(dir_name)
        else:
            print(f"✅ 必要目录: {dir_name}")
    
    # 检查可选目录
    for dir_name in optional_dirs:
        if not os.path.isdir(dir_name):
            missing_optional.append(dir_name)
        else:
            print(f"✅ 可选目录: {dir_name}")
    
    # 报告缺失文件
    if missing_required:
        print(f"❌ 缺失必要文件/目录: {', '.join(missing_required)}")
        return False
    
    if missing_optional:
        print(f"⚠️  缺失可选文件/目录: {', '.join(missing_optional)}")
    
    print("✅ 文件检查完成")
    return True

def create_spec_file(output_name='InterestRating'):
    """创建PyInstaller spec配置文件 - 适配新文件夹结构"""
    
    # 动态构建数据文件列表
    datas = []
    
    # 基础文件
    base_files = ['config.txt']
    for file_name in base_files:
        if os.path.exists(file_name):
            datas.append((file_name, '.'))
    
    # 样式文件
    style_files = ['pr_style.qss', 'vscode_style.qss']
    for file_name in style_files:
        if os.path.exists(file_name):
            datas.append((file_name, '.'))
    
    # 图标文件
    if os.path.exists('icon.png'):
        datas.append(('icon.png', '.'))
    
    # 目录
    dirs_to_include = [
        'nltk_data',
        'pyannote_models', 
        'checkpoints',
        'save',
        'cache',
        'data',
        'processing',
        'modules',
        'config',
    ]
    
    for dir_name in dirs_to_include:
        if os.path.isdir(dir_name):
            datas.append((dir_name, dir_name))
    
    # 构建spec内容
    datas_str = ',\n    '.join([f"('{src}', '{dst}')" for src, dst in datas])
    
    # 图标设置 - 优先使用config目录中的图标
    icon_paths = [
        "./config/icon.png",  # 优先使用配置目录中的图标
        "./icon.png",         # 备用：根目录图标
        "./icons/app.png",    # 备用：icons目录
        "./icons/app.ico"     # 备用：ico格式
    ]
    
    icon_setting = ""
    for icon_path in icon_paths:
        if os.path.exists(icon_path):
            icon_setting = f"icon='{icon_path}'"
            print(f"🎨 使用图标: {icon_path}")
            break
    
    if not icon_setting:
        print("⚠️ 警告: 未找到图标文件，exe将使用默认图标")
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# 数据文件 - 适配新文件夹结构
datas = [
    {datas_str}
]

# 隐藏导入 - 适配新模块结构
hiddenimports = [
    # 核心模块
    'modules.core',
    'modules.progress_manager',
    'modules.progress_widget',
    'modules.beautiful_progress_widget',
    'modules.smart_progress_predictor',
    'modules.ui_components',
    'modules.pipeline_backend',
    'modules.analyze_data',
    'modules.new_clips_manager',
    'modules.gui_logger',
    
    # 处理模块
    'processing.twitch_downloader',
    'processing.local_video_manager',
    'processing.extract_chat',
    'processing.transcribe_audio',
    'processing.clip_video',
    'processing.video_emotion_infer',
    'processing.speaker_separation_integration',
    'processing.subtitle_generator',
    
    # 配置模块
    'config.config',
    'config.progress_styles',
    
    # 第三方库
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
    'test',
    'tests',
    'testing',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
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
    name='{output_name}',
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
    {icon_setting}
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='{output_name}',
)
'''
    
    with open('InterestRating.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("📝 已创建 InterestRating.spec 配置文件")
    print(f"📋 包含的数据文件: {len(datas)} 个")

def check_dependencies():
    """检查依赖是否安装"""
    try:
        import PyInstaller
        print(f"✅ PyInstaller已安装: {PyInstaller.__version__}")
    except ImportError:
        print("❌ PyInstaller未安装，正在安装...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
        print("✅ PyInstaller安装完成")
    
    # 检查其他必要依赖
    required_packages = ['PyQt5', 'torch', 'numpy']
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package} 已安装")
        except ImportError:
            print(f"⚠️  {package} 未安装，可能影响打包")

def run_pyinstaller(output_name='InterestRating'):
    """运行PyInstaller打包"""
    try:
        print("🚀 开始PyInstaller打包...")
        print("⏳ 这可能需要几分钟时间，请耐心等待...")
        
        cmd = [
            'pyinstaller',
            '--clean',
            '--noconfirm',
            f'{output_name}.spec'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode == 0:
            print("✅ PyInstaller打包成功!")
            print(f"📁 输出目录: dist/{output_name}/")
            print(f"🎯 主程序: dist/{output_name}/{output_name}.exe")
        else:
            print("❌ PyInstaller打包失败!")
            print("错误输出:")
            print(result.stderr)
            return False
            
    except FileNotFoundError:
        print("❌ 错误: 未找到PyInstaller，请先安装:")
        print("pip install pyinstaller")
        return False
    except Exception as e:
        print(f"❌ 打包过程中出现错误: {e}")
        return False
    
    return True

def create_launcher(output_name='InterestRating'):
    """创建启动器脚本"""
    launcher_content = f'''@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ========================================
echo        Interest Rating 启动器
echo ========================================
echo.
echo 正在启动程序，请稍候...
echo.
start "" "{output_name}.exe"
echo 程序已启动！
pause
'''
    
    launcher_path = f'dist/{output_name}/启动程序.bat'
    # 使用 UTF-8 BOM 让 Windows 记事本/资源管理器正确显示中文
    with open(launcher_path, 'w', encoding='utf-8-sig') as f:
        f.write(launcher_content)
    
    print(f"📝 已创建启动器脚本: 启动程序.bat")

def create_readme(output_name='InterestRating'):
    """创建说明文档"""
    readme_content = f'''# Interest Rating 程序说明

## 文件说明
- {output_name}.exe - 主程序
- 启动程序.bat - 启动脚本（双击即可运行）
- README.txt - 本说明文件

## 运行要求
- Windows 10/11 64位系统
- 无需安装Python环境
- 首次运行可能需要等待几秒钟

## 使用说明
1. 双击 "启动程序.bat" 运行程序
2. 或者直接双击 "{output_name}.exe"
3. 首次运行会创建必要的配置文件和目录

## 目录结构
- data/ - 数据目录
- cache/ - 缓存目录
- logs/ - 日志目录
- clips/ - 切片输出目录

## 注意事项
- 程序运行时会在同目录创建logs文件夹存放日志
- 如果遇到问题，请查看logs文件夹中的错误日志
- 建议将整个文件夹复制到其他位置使用
- 确保有足够的磁盘空间存储视频文件

## 常见问题
Q: 程序启动很慢？
A: 首次启动需要加载模型，请耐心等待

Q: 提示缺少DLL？
A: 请确保在Windows 10/11系统上运行

Q: 无法下载视频？
A: 请检查网络连接和Twitch API配置

## 技术支持
如有问题请联系开发者
'''
    
    readme_path = f'dist/{output_name}/README.txt'
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    print(f"📝 已创建说明文档: README.txt")

def copy_additional_files(output_name='InterestRating'):
    """复制额外的必要文件"""
    additional_files = [
        'config.txt',
        'pr_style.qss',
        'vscode_style.qss',
    ]
    
    dist_dir = f'dist/{output_name}'
    for file_name in additional_files:
        if os.path.exists(file_name):
            shutil.copy2(file_name, dist_dir)
            print(f"📋 已复制: {file_name}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='PyInstaller打包脚本')
    parser.add_argument('--clean', action='store_true', help='清理构建目录')
    parser.add_argument('--spec-only', action='store_true', help='仅创建spec文件')
    parser.add_argument('--build', action='store_true', help='执行完整打包')
    parser.add_argument('--check-deps', action='store_true', help='检查依赖')
    parser.add_argument('--check-files', action='store_true', help='检查文件')
    parser.add_argument('--name', type=str, default='InterestRating', help='自定义输出文件夹名称（默认：InterestRating）')
    
    args = parser.parse_args()
    
    output_name = args.name
    
    if args.check_files:
        check_files_exist()
        return
    
    if args.check_deps:
        check_dependencies()
        return
    
    if args.clean:
        clean_build_dirs(output_name)
        return
    
    if args.spec_only:
        create_spec_file(output_name)
        return
    
    if args.build:
        print("🔨 开始完整打包流程...")
        clean_build_dirs(output_name)
        
        # 检查文件
        if not check_files_exist():
            print("❌ 文件检查失败，无法继续打包")
            return
        
        check_dependencies()
        create_spec_file(output_name)
        
        if run_pyinstaller(output_name):
            # 检查打包是否成功
            if os.path.exists(f'dist/{output_name}/{output_name}.exe'):
                create_launcher(output_name)
                create_readme(output_name)
                copy_additional_files(output_name)
                print(f"\n🎉 打包完成!")
                print(f"📁 输出目录: dist/{output_name}/")
                print(f"🚀 双击 '启动程序.bat' 即可运行程序")
            else:
                print("❌ 打包失败，请检查错误信息")
        return
    
    # 默认执行完整流程
    print("🔨 开始完整打包流程...")
    clean_build_dirs(output_name)
    
    # 检查文件
    if not check_files_exist():
        print("❌ 文件检查失败，无法继续打包")
        return
    
    check_dependencies()
    create_spec_file(output_name)
    
    if run_pyinstaller(output_name):
        # 检查打包是否成功
        if os.path.exists(f'dist/{output_name}/{output_name}.exe'):
            create_launcher(output_name)
            create_readme(output_name)
            copy_additional_files(output_name)
            print(f"\n🎉 打包完成!")
            print(f"📁 输出目录: dist/{output_name}/")
            print(f"🚀 双击 '启动程序.bat' 即可运行程序")
        else:
            print("❌ 打包失败，请检查错误信息")

if __name__ == '__main__':
    main()
