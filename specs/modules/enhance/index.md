# Enhance Module Index

自动成片增强模块，负责在剪辑后自动添加字幕、特效、视角切换、梗贴图等增强效果。

## 子模块
1. [ASR](asr/spec.md) - 自动语音识别与词级时间戳
2. [Subtitle FX](subtitle_fx/spec.md) - 字幕特效生成（ASS格式）
3. [ROI](roi/spec.md) - 电脑画面与V区域识别
4. [Policy](policy/spec.md) - 视角切换与梗贴图策略
5. [Render](render/spec.md) - FFmpeg渲染编译器
6. [RAG](rag/spec.md) - 用户偏好检索与风格推荐

## 核心产物
- `timeline.json` - 统一时间轴事件（所有模块输出汇总）
- `subtitles.ass` - 带特效的ASS字幕
- `filter_complex.txt` - FFmpeg滤镜脚本
- `final.mp4` - 最终成片

## 依赖库
- WhisperX / stable-ts（ASR）
- pysubs2（ASS编辑）
- scenedetect（场景切分）
- llama-index / langchain（RAG，可选）
- faiss / chroma（向量库，可选）

## Trace Links
- Workflow: `docs/02_workflow.md` 第8阶段
- Tasks: `specs/modules/enhance/tasks.md`
