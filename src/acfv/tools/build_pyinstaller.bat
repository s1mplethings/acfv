@echo off
chcp 65001 >nul
echo.
echo ========================================
echo        Interest Rating 打包工具
echo ========================================
echo.
echo 正在启动PyInstaller打包...
echo.

python build_with_pyinstaller.py --build

echo.
echo 打包完成！按任意键退出...
pause >nul
