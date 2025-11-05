@echo off
REM 设置环境变量以优化运行环境
set TF_ENABLE_ONEDNN_OPTS=0
echo TensorFlow OneDNN optimization disabled

REM 设置其他可能有用的环境变量
set PYTHONIOENCODING=utf-8
set CUDA_VISIBLE_DEVICES=""
echo Environment variables set for ACFV