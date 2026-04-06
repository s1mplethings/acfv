# Render (FFmpeg渲染编译器) Spec

## 1) Purpose
- 负责：将timeline.json编译为FFmpeg命令并执行渲染，输出final.mp4。
- 不负责：策略决定、ASR转写、ROI检测。

## 2) Inputs
- `timeline.json`（汇总所有事件）
- `subtitles.ass`（带特效字幕）
- `rois.json`（PC/V区域）
- 原视频文件
- 详见 `contract_input.md`

## 3) Outputs
- `filter_complex.txt`：FFmpeg滤镜脚本
- `final.mp4`：最终成片
- `render.log`：渲染日志
- 详见 `contract_output.md`

## 4) Process
1) 验证timeline.json格式（schema校验）
2) 编译字幕层：`subtitles=subtitles.ass`
3) 编译视角切换层：
   - 按view事件生成crop/scale/pad滤镜
   - 使用enable='between(t,t0,t1)'控制时间段
4) 编译overlay层：
   - 按overlay事件叠加贴图
   - 支持alpha透明和动画（scale/fade）
5) 编译音频层：
   - 混合原音频和sfx事件
   - 使用volume/adelay控制时间和增益
6) 生成filter_complex.txt
7) 执行ffmpeg命令，输出final.mp4
8) 验证输出文件存在且时长正确

## 5) Configuration
- `output_format`: mp4 / webm
- `video_codec`: libx264 / libx265 / av1
- `crf`: 23（质量控制）
- `preset`: medium / fast / slow
- `subtitle_font`: 默认字体路径

## 6) Performance Budget
- 10分钟视频：< 5分钟渲染时间（硬件编码）
- 内存占用：< 4GB

## 7) Error Handling
- timeline.json格式错误：报错并输出详细位置
- FFmpeg命令失败：保留filter_complex.txt便于调试
- 素材文件缺失：跳过该overlay并记录警告

## 8) Edge Cases
- 空timeline（无事件）：只烧录字幕
- 超大视频（>2小时）：建议分段渲染
- 硬件编码不可用：自动fallback到软件编码

## 9) Acceptance Criteria
- AC-RENDER-001 schema校验：非法timeline.json时报错
- AC-RENDER-002 时长一致：输出视频时长 = 输入视频时长 ±0.5秒
- AC-RENDER-003 字幕烧录：final.mp4包含可见字幕（目视检查）

## 10) Trace Links
- Contracts: `contract_input.md`, `contract_output.md`
- Implementation: `src/acfv/enhance/render/ffmpeg_compile.py`
- Tests: `tests/integration/test_render_pipeline.py`
