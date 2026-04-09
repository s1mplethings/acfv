# Screen Detect Spec

## 1) Purpose
- 负责：机械式检测电脑画面区域、抽取关键帧、组织 screen windows。
- 不负责：屏幕语义理解、高光最终判断。

## 2) Inputs
- `source_path`：输入视频路径。
- 配置：`ENABLE_SCREEN_DETECT`、`SCREEN_DETECT_INTERVAL_SEC`、`SCREEN_MAX_FRAMES_PER_WINDOW`、`SCREEN_ENABLE_OCR`。

## 3) Outputs
- `frames`：抽取后的关键帧元数据。
- `windows`：时间窗、bbox、OCR hint、是否全屏录屏等。

## 4) Process
1) 定时抽帧。
2) 使用 hash 做相似帧去重。
3) 用边缘/线段/结构密度启发式推断 screen bbox。
4) 检测失败时回退到全帧或中心区域，不中断后续流程。
