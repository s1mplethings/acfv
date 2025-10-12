@echo off
chcp 65001 >nul
title 打包结果查看

echo.
echo ========================================
echo        Interest Rating 打包结果
echo ========================================
echo.

if exist "dist\InterestRating\InterestRating.exe" (
    echo ✅ 打包成功！
    echo.
    echo 📁 可执行文件位置: dist\InterestRating\InterestRating.exe
    
    for %%A in ("dist\InterestRating\InterestRating.exe") do (
        echo 📊 文件大小: %%~zA 字节
        echo 📅 创建时间: %%~tA
    )
    
    echo.
    echo 📋 包含的文件:
    dir "dist\InterestRating" /b
    
    echo.
    echo 🚀 现在你可以:
    echo    1. 双击 InterestRating.exe 运行程序
    echo    2. 复制整个 InterestRating 文件夹到其他电脑
    echo    3. 程序包含所有依赖，无需安装Python
    echo.
    
    set /p choice="是否打开输出目录？(y/n): "
    if /i "%choice%"=="y" (
        explorer "dist\InterestRating"
    )
    
) else (
    echo ❌ 打包失败：未找到exe文件
    echo.
    echo 请检查:
    echo    1. 是否完成了打包过程
    echo    2. 是否有错误信息
    echo    3. 重新运行打包脚本
)

echo.
echo 按任意键退出...
pause >nul
