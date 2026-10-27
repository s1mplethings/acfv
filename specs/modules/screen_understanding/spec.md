# Screen Understanding Spec

## 1) Purpose
- 负责：从视频抽取稀疏关键帧，识别电脑画面在做什么，输出时间轴级结构化 screen context。
- 不负责：最终高光决策、视频裁剪。

## 2) Inputs
- `screen_windows`：来自 `screen_detect` 的稀疏关键帧/时间窗。
- `transcript`：相邻时间段转录文本，用于辅助解释画面行为。
- 配置：`ENABLE_SCREEN_UNDERSTANDING`、`LLM_VISION_MODEL` / `SCREEN_UNDERSTANDING_MODEL`。

## 3) Outputs
- `timeline`：按时间排序的画面上下文窗口。
- `frames`：关键帧元数据与落盘路径。
- 详情见 `contract_output.md`。

## 4) Process
1) 读取 `screen_detect` 的时间窗。
2) 组合 OCR hint 与 transcript hint。
3) 可用时调用统一 OpenAI 客户端做结构化视觉理解。
4) 不可用时回退到启发式标签。

## 5) Error Handling
- 无法开视频或缺少依赖时输出空 timeline，并保留 `status`。
- LLM / OCR 失败不终止主流程，回退到 heuristic。
