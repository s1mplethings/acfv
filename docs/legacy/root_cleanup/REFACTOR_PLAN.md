# ACFV 项目重构修复计划

## 问题现状分析

### 🚨 严重问题清单

#### 1. 导入依赖混乱
- **相对导入错误**：多处使用错误的相对导入路径
- **缺失模块引用**：引用不存在或路径错误的模块
- **循环导入风险**：模块间可能存在循环依赖

**影响文件**：
- `src/acfv/processing/analyze_data.py` - 使用 `from main_logging import`
- `src/acfv/processing/clip_video.py` - 使用 `from main_logging import` 
- `src/acfv/processing/extract_chat.py` - 使用 `from main_logging import`
- `src/acfv/processing/clip_video_clean.py` - 使用 `from main_logging import`
- `src/acfv/processing/transcribe_audio.py` - 使用 `from main_logging import`
- `src/acfv/features/modules/pipeline_backend.py` - 使用 `from processing.xxx import`

#### 2. 配置系统冲突
- **双配置系统**：同时存在 `config/` 和 `configs/` 两套配置
- **API不统一**：ConfigManager vs Settings 两套配置API
- **导入混乱**：代码中混用两套配置系统

**冲突文件**：
- `src/acfv/config/config.py` - ConfigManager类（旧系统）
- `src/acfv/configs/settings.py` - Settings类（新系统）
- 多个processing文件使用 `from acfv import config`

#### 3. 模块重复和冲突
- **pipeline_backend重复**：
  - `src/acfv/features/modules/pipeline_backend.py` (2179行)
  - `src/acfv/interest/modules/pipeline_backend.py` (简化版)
- **功能分散**：相同功能在不同位置实现

#### 4. 入口点混乱
- **多入口点**：存在多个启动器，职责不清
  - `src/acfv/main.py` (782行，旧式)
  - `src/acfv/launcher.py` (123行，打包用)
  - `src/acfv/cli/_entry.py` (新式CLI)
  - `src/acfv/legacy_cli.py` (兼容性)

## 🎯 修复计划 - 分阶段实施

### 阶段1：修复导入依赖（高优先级）

#### 1.1 统一日志模块导入
**目标**：将所有 `from main_logging import` 改为 `from acfv.main_logging import`

**涉及文件**：
- [ ] `src/acfv/processing/analyze_data.py`
- [ ] `src/acfv/processing/clip_video.py`
- [ ] `src/acfv/processing/extract_chat.py`
- [ ] `src/acfv/processing/clip_video_clean.py`
- [ ] `src/acfv/processing/transcribe_audio.py`

**修改模式**：
```python
# 修改前
from main_logging import log_debug, log_info, log_error, log_warning

# 修改后
from acfv.main_logging import log_debug, log_info, log_error, log_warning
```

#### 1.2 修复processing模块内相对导入
**目标**：修复processing模块中的相对导入问题

**涉及文件**：
- [ ] `src/acfv/processing/analyze_data.py` - `from rag_vector_database import`
- [ ] `src/acfv/features/modules/pipeline_backend.py` - `from processing.xxx import`

### 阶段2：整合配置系统（中优先级）

#### 2.1 决策：保留哪套配置系统
**决策**：保留新系统（configs/settings.py），废弃旧系统（config/）

**原因**：
- Settings使用现代的Pydantic，类型安全
- 支持YAML配置文件
- 结构更清晰

#### 2.2 迁移步骤
- [ ] 统计所有使用 `from acfv import config` 的文件
- [ ] 逐个替换为 `from acfv.configs.settings import Settings`
- [ ] 更新配置调用方式
- [ ] 删除旧的config目录

### 阶段3：清理重复模块（中优先级）

#### 3.1 合并pipeline_backend
**决策**：保留 `features/modules/pipeline_backend.py`，迁移必要功能

**步骤**：
- [ ] 分析两个pipeline_backend的差异
- [ ] 将interest版本的特有功能合并到features版本
- [ ] 更新所有引用interest版本的代码
- [ ] 删除重复文件

### 阶段4：简化入口点（低优先级）

#### 4.1 整合启动器
**决策**：以CLI为主入口，保留必要的兼容性

**步骤**：
- [ ] 确认 `cli/_entry.py` 作为主入口
- [ ] 迁移 `main.py` 和 `launcher.py` 的必要功能
- [ ] 更新pyproject.toml入口点配置
- [ ] 保留legacy_cli.py作为过渡

## 📋 实施检查清单

### 导入修复检查清单
- [ ] 所有 `main_logging` 导入已修复
- [ ] 所有 `config` 导入已统一
- [ ] 相对导入路径已修正
- [ ] 导入测试通过

### 配置系统检查清单  
- [ ] 旧config目录已移除或重命名
- [ ] 所有配置调用已更新
- [ ] 配置文件路径已统一
- [ ] 配置加载测试通过

### 模块清理检查清单
- [ ] 重复模块已识别
- [ ] 功能已合并
- [ ] 引用已更新
- [ ] 重复文件已删除

### 入口点检查清单
- [ ] 主入口点已确定
- [ ] 启动流程已简化
- [ ] 兼容性已保持
- [ ] CLI命令正常工作

## 🔍 测试验证计划

### 基础导入测试
```python
# 测试基础导入是否正常
python -c "import acfv"
python -c "from acfv.main_logging import log_info"
python -c "from acfv.configs.settings import Settings"
```

### 功能测试
```bash
# 测试CLI入口点
acfv --help
acfv gui
python -m acfv

# 测试配置加载
python -c "from acfv.configs.settings import Settings; print(Settings())"
```

## 📅 实施时间表

### 第一天：导入修复
- 修复所有main_logging导入
- 修复processing模块相对导入
- 基础导入测试

### 第二天：配置整合
- 分析配置使用情况
- 迁移到统一配置系统
- 配置系统测试

### 第三天：模块清理
- 合并pipeline_backend
- 清理重复代码
- 模块功能测试

### 第四天：入口整合
- 简化入口点
- 更新配置文件
- 端到端测试

## 🚨 风险提醒

1. **备份重要**：修改前务必备份或使用git分支
2. **渐进修复**：一次只修复一类问题，避免同时修改太多
3. **测试优先**：每完成一个阶段都要进行测试验证
4. **依赖检查**：注意外部依赖包的安装要求

## 📝 修改记录

- [2025-10-14] 创建修复计划
- [✅] 阶段1完成 - 修复导入依赖
  - ✅ analyze_data.py - 修复main_logging和rag_vector_database导入
  - ✅ clip_video.py - 修复main_logging导入  
  - ✅ extract_chat.py - 修复main_logging导入
  - ✅ clip_video_clean.py - 修复main_logging导入
  - ✅ transcribe_audio.py - 修复main_logging导入
  - ✅ 基础导入测试通过
- [✅] 阶段2完成 - 配置系统整合
  - ✅ 在config/__init__.py中创建字典兼容层
  - ✅ 解决config vs configs冲突
  - ✅ 所有processing模块能正常使用config.get()
- [✅] 阶段3完成 - 清理重复模块  
  - ✅ 删除重复的interest/modules/pipeline_backend.py
  - ✅ 统一使用features/modules/pipeline_backend.py
  - ✅ 更新interest_adapter.py引用
- [✅] 阶段4完成 - 简化入口点
  - ✅ 修复CLI依赖问题，添加降级机制
  - ✅ python -m acfv 现在正常工作
  - ✅ 综合导入测试通过

## 🎉 修复成果总结

**修复前**：❌ 项目无法运行，大量导入错误
**修复后**：✅ 基础功能正常，模块导入成功

**关键修复**：
1. 统一了导入路径（main_logging, rag_vector_database）  
2. 解决了配置系统冲突（创建兼容层）
3. 清理了重复模块（pipeline_backend）
4. 修复了入口点问题（CLI降级机制）

---

**项目现在处于可用状态！** 🚀