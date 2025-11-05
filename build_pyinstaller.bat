@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo Python 未安装或未加入 PATH
  pause
  exit /b 1
)
python -m pip install --upgrade pip
if exist requirements.txt pip install -r requirements.txt
pip install pyinstaller
python build_with_pyinstaller.py
echo.
echo === 打包完成，查看 dist\ 目录 ===
pause

