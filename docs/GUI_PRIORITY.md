# GUI优先开发指南（AI协作说明）

> 📌 **重要**：本项目当前阶段GUI是主要开发方向，CLI仅作为接口备用

## 开发优先级

### 1️⃣ GUI为主（优先级：高）
- **目标用户**：非技术用户，通过可视化界面操作
- **开发重点**：交互体验、视觉反馈、错误提示、进度显示
- **验收标准**：
  - 所有核心功能必须有GUI入口
  - 用户无需接触命令行即可完成完整流程
  - GUI组件必须实时反馈状态（进度条、提示消息）
  - 错误信息必须用户友好（非技术术语）

### 2️⃣ CLI为辅（优先级：中）
- **目标用户**：开发者、自动化脚本调用
- **开发重点**：接口稳定性、参数完整性、返回值规范
- **验收标准**：
  - 提供基础命令行接口
  - 输出格式规范（JSON/日志）
  - 支持批处理和自动化调用
  - **但不要求交互式体验**

## GUI开发原则

### 功能实现顺序
1. **先GUI后CLI**：新功能必须先实现GUI版本，CLI可延后
2. **GUI独立测试**：每个GUI组件必须可独立测试（不依赖CLI）
3. **配置统一**：GUI和CLI共享同一套配置（ConfigManager），避免重复

### GUI组件规范
- 使用PyQt5标准组件
- 遵循现有UI风格（card_frame_style, wrap_in_card）
- 所有耗时操作必须在后台线程执行（QThread/Worker）
- 提供实时进度反馈（ProgressBar/StatusLabel）

## Enhance模块开发示例

### ✅ 正确做法（GUI优先）
```python
# 1. 先创建GUI面板
class EnhancePanel(QWidget):
    def __init__(self, config_manager):
        # UI组件：复选框、下拉框、滑块
        self.enable_asr = QCheckBox("自动字幕")
        self.style_combo = QComboBox()
        # ...

# 2. 在clips_tab中集成
def init_ui(self, container):
    main_layout = QHBoxLayout()
    main_layout.addWidget(clips_widget, 3)
    main_layout.addWidget(enhance_panel, 1)  # 侧边栏

# 3. CLI作为调用接口（可延后）
@app.command()
def enhance_video(...):
    # 复用GUI逻辑，只是换个入口
    pass
```

### ❌ 错误做法（CLI优先）
```python
# ❌ 不要先实现复杂的CLI参数解析
@app.command()
def enhance_video(
    input_video: Path,
    roi_config: Path,
    style: str,
    # ... 一堆参数
):
    # 然后再想怎么做GUI
    pass
```

## 当前Enhance模块状态

### 已完成（GUI）
- ✅ EnhancePanel侧边栏（切片页面右侧）
- ✅ 功能模块复选框（ASR/字幕特效/ROI/梗贴图/RAG）
- ✅ 字幕风格选择（下拉框）
- ✅ 梗密度控制（滑块）
- ✅ 配置保存到ConfigManager

### 待实现（按GUI优先顺序）
1. **GUI后台任务集成**（优先级：高）
   - [ ] 在pipeline中读取enhance_panel配置
   - [ ] 根据勾选项决定是否执行ASR/字幕特效
   - [ ] 进度条显示enhance各阶段

2. **ASR字幕生成**（优先级：高）
   - [ ] GUI：在enhance_panel添加"测试字幕"按钮
   - [ ] 后台：调用WhisperX生成segments.json
   - [ ] 反馈：显示字幕预览对话框

3. **字幕特效预览**（优先级：高）
   - [ ] GUI：字幕风格实时预览窗口
   - [ ] 交互：拖拽调整关键词特效

4. **ROI配置界面**（优先级：中）
   - [ ] GUI：可视化ROI框选工具（在视频上画框）
   - [ ] 保存：per-channel预设管理

5. **CLI接口补全**（优先级：低）
   - [ ] 完善`acfv enhance run`命令
   - [ ] 批量处理支持
   - [ ] 日志输出规范

## AI实施建议

### 收到新需求时的判断流程
```
用户需求 → 是否涉及用户交互？
           ├─ 是 → GUI优先实现
           │      └─ 创建QWidget组件 → 集成到主窗口 → 测试交互
           └─ 否 → 可先CLI实现
                  └─ 后续再添加GUI入口
```

### 改动量化标准（GUI vs CLI）
- **GUI改动**：
  - 新增组件：≤ 5个文件（panel/dialog/widget）
  - 集成现有页面：修改 ≤ 3个文件
  - 必须通过GUI smoke测试（手动/自动）

- **CLI改动**：
  - 新增命令：1个文件（cli/*.py）
  - 参数完整性测试（pytest）
  - **不要求交互式体验优化**

## 验收清单

### GUI验收（必须）
- [ ] 用户可通过鼠标点击完成操作（无需命令行）
- [ ] 所有输入框有默认值和提示文本
- [ ] 错误提示用对话框展示（非控制台输出）
- [ ] 长时间操作有进度条或加载动画

### CLI验收（可选）
- [ ] 提供`--help`查看用法
- [ ] 参数校验（错误参数返回非0退出码）
- [ ] 输出格式规范（JSON/文本）
- [ ] 可被脚本调用（无交互提示）

## 总结

**记住**：用户主要通过GUI操作，CLI只是备用接口。优先让GUI好用，CLI能用即可。

---

**最后更新**：2026-02-02  
**适用模块**：Enhance（成片增强）及所有新功能
