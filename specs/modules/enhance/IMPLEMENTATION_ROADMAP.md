# Enhance Module Implementation Roadmap

> 按照PATCH文档和AGENTS.md流程，逐步实现完整的自动成片增强功能

## 当前状态（MVP Phase 1 完成）

### ✅ 已完成
1. **Spec设计**：6个子模块完整spec（ASR/Subtitle FX/ROI/Policy/Render/RAG）
2. **目录结构**：`src/acfv/enhance/` + 子模块目录
3. **Timeline Schema**：pydantic验证的统一时间轴格式
4. **配置模板**：roi.yaml, subtitle.yaml, style_profiles.yaml, meme_policy.yaml
5. **依赖更新**：whisperx, stable-ts, pysubs2, scenedetect, llama-index等
6. **CLI入口**：`acfv enhance run` 命令（dry-run模式可用）
7. **测试框架**：integration tests + schema validation
8. **文档同步**：工作流、repo_map、AGENTS.md更新
9. **Verify通过**：27 passed, 1 skipped ✅

### 📋 待实现（按优先级）

#### Phase 2：核心渲染链路（必做）
1. **ASR转写** (`src/acfv/enhance/asr/transcribe.py`)
   - [ ] WhisperX集成：词级时间戳
   - [ ] stable-ts集成：稳定分句
   - [ ] 输出words.json + segments.json
   - [ ] 测试：10s音频 < 30s处理时间

2. **Subtitle FX** (`src/acfv/enhance/subtitle/ass_builder.py`)
   - [ ] pysubs2生成ASS文件
   - [ ] 分句规则实现（12-18字/行）
   - [ ] 关键词特效注入（POP/COLOR）
   - [ ] 测试：生成的ASS可被ffmpeg解析

3. **Render编译器** (`src/acfv/enhance/render/ffmpeg_compile.py`)
   - [ ] Timeline → filter_complex.txt
   - [ ] 字幕烧录（subtitles滤镜）
   - [ ] 执行ffmpeg命令
   - [ ] 测试：10s视频渲染 < 1分钟

#### Phase 3：ROI与视角切换（推荐做）
4. **ROI配置** (`src/acfv/enhance/roi/roi_config.py`)
   - [ ] 读取roi.yaml
   - [ ] 验证坐标合法性
   - [ ] 输出rois.json
   - [ ] 测试：预设配置可用

5. **View Policy** (`src/acfv/enhance/policy/view_policy.py`)
   - [ ] 关键词检测 → V视角
   - [ ] 防抖逻辑（≥1.2s）
   - [ ] 输出view_events.json
   - [ ] 测试：状态机转换正确

#### Phase 4：梗贴图与音效（可选）
6. **Meme Policy** (`src/acfv/enhance/policy/meme_policy.py`)
   - [ ] 触发词匹配
   - [ ] 冷却时间控制
   - [ ] 输出overlay_events.json + sfx_events.json
   - [ ] 测试：密度控制有效

7. **RAG检索**（最后实现，可选）
   - [ ] 素材库索引构建
   - [ ] 用户偏好检索
   - [ ] 输出preference_profile.json

## 实施顺序建议

### Week 1: 最小可用（MVP2）
1. 实现ASR → segments.json
2. 实现Subtitle → subtitles.ass（无特效）
3. 实现Render → final.mp4（仅字幕烧录）
4. 验收：10s视频 → 带字幕的final.mp4

### Week 2: 视角切换
1. ROI纯配置模式
2. View Policy基础规则
3. Render添加crop/scale支持
4. 验收：视角可在FULL/PC/V切换

### Week 3: 特效与梗
1. Subtitle FX关键词特效
2. Meme Policy触发规则
3. Render添加overlay/sfx支持
4. 验收：关键词POP + 梗贴图出现

### Week 4: 可选增强
1. ROI自动跟踪（档2）
2. RAG偏好检索
3. 高级特效（SHAKE等）
4. 性能优化

## 量化验收标准（严格遵守）

### 代码改动量
- Phase 2-3：新增文件 ≤ 15个，总代码行数 ≤ 2000行
- 无重构现有代码（除非fix bug）

### 测试覆盖
- 每个Phase必须通过verify.ps1
- 核心函数覆盖率 ≥ 80%
- 至少1个端到端smoke测试

### 性能指标
- 10s视频完整流程 < 2分钟（GPU），< 5分钟（CPU）
- 内存占用 < 4GB

### 文档同步
- 每个Phase完成后更新对应spec的implementation章节
- 记录遇到的问题到`ai_context/problem_registry.md`

## CLI使用示例

### 当前可用（dry-run）
```bash
# 生成timeline.json（不渲染）
python -m acfv.cli enhance run -i input.mp4 -o final.mp4 --dry-run
```

### Phase 2完成后
```bash
# 基础字幕烧录
python -m acfv.cli enhance run -i input.mp4 -o final.mp4
```

### Phase 3完成后
```bash
# 带ROI和视角切换
python -m acfv.cli enhance run -i input.mp4 -o final.mp4 --roi config/roi.yaml
```

### 最终完整版
```bash
# 全功能增强
python -m acfv.cli enhance run -i input.mp4 -o final.mp4 \
  --roi config/roi.yaml \
  --style assets/styles/meme_heavy.yaml \
  --profile user_profile.json
```

## 风险与回滚

### 依赖风险
- WhisperX需CUDA环境：提供CPU fallback
- llama-index较重：RAG标记为可选模块

### 回滚方法
- Git: `git checkout HEAD -- src/acfv/enhance/`
- 删除: `rm -rf src/acfv/enhance specs/modules/enhance`
- Verify: 确保现有功能不受影响

## 参考资源

### 库文档
- [WhisperX](https://github.com/m-bain/whisperX)
- [stable-ts](https://github.com/jianfch/stable-ts)
- [pysubs2](https://pysubs2.readthedocs.io/)
- [FFmpeg Filters](https://ffmpeg.org/ffmpeg-filters.html)
- [Grounded SAM 2](https://github.com/IDEA-Research/Grounded-SAM-2)

### 内部文档
- [Workflow](../docs/02_workflow.md) - 完整流程说明
- [AGENTS.md](../AGENTS.md) - AI编程规范
- [Specs](../specs/modules/enhance/) - 各模块详细规格

---

**下一步行动**：选择Phase 2的ASR模块开始实现，遵循spec-first原则。
