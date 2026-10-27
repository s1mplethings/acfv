#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interest Rating 项目自动打包脚本
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

def check_python_version():
	print("检查Python版本...")
	if sys.version_info < (3, 7):
		print(f"需要Python 3.7+，当前版本: {sys.version}")
		return False
	print(f"Python版本: {sys.version}")
	return True

def install_dependencies():
	print("安装依赖...")
	subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
	subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

def install_pyinstaller():
	print("检查PyInstaller...")
	result = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
	if result.returncode == 0:
		print(f"PyInstaller已安装: {result.stdout.strip()}")
		return True
	print("未检测到PyInstaller，开始安装...")
	subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])
	return True

def create_spec_file():
	print("生成spec文件...")
	spec_content = '''# -*- mode: python ; coding: utf-8 -*-
block_cipher = None
added_files = [
	('config.py', '.'),
	('config.txt', '.'),
	('gui_config.json', '.'),
	('icon.png', '.'),
	('pr_style.qss', '.'),
	('vscode_style.qss', '.'),
	('progress_styles.py', '.'),
	('core', 'core'),
	('utils.py', '.'),
	('warning_manager.py', '.'),
	('progress_manager.py', '.'),
	('ui_components.py', '.'),
	('beautiful_progress_widget.py', '.'),
	('progress_widget.py', '.'),
	('simple_progress_bar.py', '.'),
	('smart_progress_predictor.py', '.'),
	('main_window.py', '.'),
	('pipeline_backend.py', '.'),
	('speaker_diarization_module.py', '.'),
	('speaker_separation_integration.py', '.'),
	('video_emotion.py', '.'),
	('video_emotion_infer.py', '.'),
	('rag_vector_database.py', '.'),
	('subtitle_generator.py', '.'),
	('transcribe_audio.py', '.'),
	('twitch_downloader.py', '.'),
	('local_video_manager.py', '.'),
	('new_clips_manager.py', '.'),
	('optimized_clips_manager.py', '.'),
	('clip_processing_tracker.py', '.'),
	('clip_video.py', '.'),
	('extract_chat.py', '.'),
	('analyze_data.py', '.'),
	('subprocess_utils.py', '.'),
	('nltk_data', 'nltk_data'),
	('pyannote_models', 'pyannote_models'),
	('checkpoints', 'checkpoints'),
	('save', 'save'),
	('best.pt', '.'),
	('requirements.txt', '.'),
	('COPYRIGHT.txt', '.'),
	('THIRD-PARTY-LICENSES.txt', '.'),
	('tools', 'tools'),
]
hiddenimports = ['torch', 'transformers', 'nltk', 'sklearn', 'faiss', 'sentence_transformers', 'librosa', 'pydub', 'soundfile', 'cv2', 'moviepy', 'numpy', 'pandas', 'scipy', 'requests', 'PIL', 'tqdm', 'whisper', 'pyannote.audio', 'yaml', 'colorlog', 'logging', 'joblib', 'dateutil', 'cryptography', 'rarfile', 'zipfile', 'tarfile', 'psutil', 'subprocess', 'multiprocessing', 'threading', 'memory_profiler', 'gc', 'PyQt5']
excludes = ['tkinter', 'matplotlib', 'seaborn', 'plotly', 'bokeh', 'jupyter', 'IPython', 'notebook', 'pytest', 'unittest', 'doctest', 'pdb', 'profile', 'cProfile', 'pstats', 'timeit', 'trace', 'pydoc', 'help', 'site', 'distutils', 'setuptools', 'wheel', 'pip', 'ensurepip', 'venv', 'virtualenv']
a = Analysis(['main.py'], pathex=[], binaries=[], datas=added_files, hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=excludes, win_no_prefer_redirects=False, win_private_assemblies=False, cipher=block_cipher, noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='InterestRating', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False, disable_windowed_traceback=False, argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None, icon='icon.png')
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=True, upx_exclude=[], name='InterestRating')
'''
	with open('InterestRating_Optimized.spec', 'w', encoding='utf-8') as f:
		f.write(spec_content)
	print("spec文件已生成")

def clean_build():
	print("清理旧的build/dist...")
	for folder in ['build', 'dist']:
		if os.path.exists(folder):
			shutil.rmtree(folder)

def run_pyinstaller():
	print("开始打包...")
	result = subprocess.run([sys.executable, "-m", "PyInstaller", "InterestRating_Optimized.spec"])
	if result.returncode == 0:
		print("打包成功！")
	else:
		print("打包失败！")

def main():
	if not check_python_version():
		return
	install_dependencies()
	install_pyinstaller()
	create_spec_file()
	clean_build()
	run_pyinstaller()

if __name__ == "__main__":
	main()
