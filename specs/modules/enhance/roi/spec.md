# ROI (Region of Interest) Spec

## 1) Purpose
- 负责：识别并跟踪电脑画面区（PC）与VTuber小窗区域（V）。
- 不负责：视角切换策略、渲染。

## 2) Inputs
- 视频文件路径
- ROI配置文件（roi.yaml）或自动检测参数
- 详见 `contract_input.md`

## 3) Outputs
- `rois.json`：PC和V的边界框 `{PC: {x,y,w,h}, V: {x,y,w,h}}`
- `roi_track.json`（可选）：按帧记录ROI漂移 `[{frame, roi_id, box}]`
- 详见 `contract_output.md`

## 4) Process
### 档1：纯配置（MVP必做）
1) 读取roi.yaml中预设的PC/V坐标
2) 验证坐标在视频分辨率范围内
3) 输出rois.json

### 档2：自动校准+跟踪（推荐）
1) 首帧或关键帧做粗检测（边缘/运动）
2) 初始化OpenCV Tracker（CSRT/KCF）
3) 逐帧跟踪并更新roi_track.json
4) 检测跟踪失败时重新初始化

### 档3：开放词汇检测（可选）
1) 使用Grounded SAM 2检测"monitor"/"avatar"
2) 后处理：过滤小框、选择置信度最高的2个区域
3) 输出到rois.json

## 5) Configuration
- `mode`: config / auto_track / grounded_sam
- `roi_presets`: per-channel预设（如saruei/anny）
- `tracker_type`: CSRT / KCF（档2）
- `detection_prompt`: ["monitor", "avatar"]（档3）

## 6) Performance Budget
- 配置模式：< 0.1秒
- 跟踪模式：实时处理（30fps视频 < 1.5x实时）
- 检测模式：首帧 < 5秒，后续帧跟踪

## 7) Error Handling
- roi.yaml缺失且mode=config：报错退出
- 跟踪失败：尝试重新检测或回退到配置
- 检测无结果：使用全屏FULL作为fallback

## 8) Edge Cases
- 单ROI（无V或无PC）：允许只输出一个区域
- ROI超出边界：自动裁剪到视频范围
- 布局切换（画中画↔全屏）：按帧记录变化

## 9) Acceptance Criteria
- AC-ROI-001 配置校验：roi.yaml格式错误时报错
- AC-ROI-002 坐标合法：输出的x,y,w,h在分辨率范围内
- AC-ROI-003 跟踪稳定：相邻帧ROI漂移 < 10像素（无场景切换时）

## 10) Trace Links
- Contracts: `contract_input.md`, `contract_output.md`
- Implementation: `src/acfv/enhance/roi/roi_detect.py`
- Tests: `tests/integration/test_roi_tracking.py`
