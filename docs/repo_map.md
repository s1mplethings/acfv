# Repo Map (ACFV)

简要索引常用目录/入口，供 AI 修改时快速定位。

- 根目录  
  - `README.md`：使用说明（GUI/CLI/守护）。  
  - `AGENTS.md`：AI 协作规则（本文件）。  
  - `pyproject.toml`：依赖事实源（`requirements*.txt` 仅作安装入口包装）。  
  - 其余一次性报告/迁移说明已归档到 `docs/legacy/root_cleanup/`；根目录不再放 `*_REPORT.md`、`*_PLAN.md`、日志、zip、备份等杂项。  
- 应用代码（Python）  
  - `src/acfv/`：核心包。  
    - `main.py` / `launcher.py`：GUI/入口汇总。  
    - `cli/`：命令行入口（如 `acfv.cli.pipeline`、`acfv.cli.stream_monitor`、`acfv.cli.enhance`）。  
    - `modular/`：模块化管线插件（`plugins/`）与调度（`pipeline.py`、`contracts`）。  
      - `modular/plugins/semantic_merge.py`：语义合并模块（按文本相似度生成目标时长片段）。  
      - `modular/plugins/render_clips.py`：剪辑导出，若启用 ASR 字幕则调用 `steps/subtitle_generator` 生成 `.srt`。  
      - `modular/plugins/streamer_subtitles.py`：主播字幕导出模块。  
    - `processing/`：音视频处理实现（剪辑、转写、情绪等）。  
      - `processing/subtitle_render.py`：字幕样式/预览/烧录入口。  
      - `processing/ffmpeg_runner.py`：统一 ffmpeg 调用封装。  
    - `ui/tabs/subtitle_render_tab.py`：字幕预览/烧录 + 切片设置（GUI 单页合并）。  
    - `steps/`：逐步实现（clip、transcribe、render 等具体 impl）。  
      - `steps/subtitle_generator/impl.py`：按转写生成 clip 级字幕（SRT/ASS）。  
      - `steps/subtitle_generator/streamer_subtitles.py`：仅导出主播字幕（work/subtitles_streamer.*）。  
      - `steps/subtitle_translate/step.py`：主播字幕翻译（上下文块 + 时间轴稳定）。  
      - `steps/transcribe_audio/impl.py`：ASR 转写与切分；运行时会写入 `var/processing/working/transcribe_diagnostic.jsonl` 和 `transcribe_checkpoint.json` 供排障；支持子进程保护（`ACFV_TRANSCRIBE_GUARD=1`，可回退到 CPU）。  
    - `selection/`：高光段筛选与合并。  
    - `runtime/`：运行期配置、守护逻辑。  
    - `utils/`：日志、安全工具等。  
    - `enhance/`：**新增** 成片增强模块（ASR/Subtitle FX/ROI/Policy/RAG/Render）。  
      - `rag/ai_skeleton.py`：**AI骨架** 智能推荐生成框架（自动库检查、多后端支持）。  
      - `rag/__init__.py`：AI骨架导出接口。  
    - `audio_routing/`：**新增** 音频分流和标注转录模块（Step1-7完整流程）。
      - `pipeline.py`：音频分流管道编排器。
      - `schemas.py`：数据结构定义（VAD/Diarization/LabeledSegment等）。
      - `step1_extract.py` ~ `step7_game_non_speech.py`：7个处理步骤实现。
- 测试与校验  
  - `tests/`：测试（若存在）。  
  - `tools/contract_selftest.py`：轻量契约自检。  
  - `tools/selftest_cli.py`：输入驱动的 Adapter/Oracle 自测入口。  
  - `selftest/`：自测框架（adapters/oracles/cases/goldens）。  
  - `scripts/verify.sh` / `scripts/verify.ps1`：统一验收入口（compile → pytest → contract checks）。  
  - `scripts/contract_checks.py`：契约质量门。  
- 规格与文档  
  - `docs/`：工作流、质量门、架构等说明。  
    - `docs/legacy/root_cleanup/`：从根目录归档的一次性报告、迁移说明与备份，避免污染入口层。  
    - `docs/patch_guides/`：Patch 指导文件（面向可回滚改动的执行清单）。  
      - `docs/patch_guides/streamer_subtitles_export.md`：Streamer-only 字幕导出 patch 指南。  
      - `docs/patch_guides/PATCH-02_gui_subtitle_render_preview_and_clip_page.md`：字幕预览/烧录 + 切片设置页 patch 指南。  
  - `specs/`：模块 spec 与输出契约 schema（含 `enhance/` 子模块）。  
  - `assets/subtitle_styles/presets.json`：字幕样式预设。  
  - `ai_context/`：task card、decision/problem 记录模板。  
- 配置与样例  
  - `config.txt`、`.env.example`、`var/settings/*.yaml`（运行配置）。  
  - `secrets/`：凭证模板（已忽略真实内容）。  
  - 关键配置：`WHISPER_ENGINE`（auto/openai-whisper/faster-whisper/hf-whisper）、`HF_WHISPER_MODEL`（默认 `openai/whisper-medium`）。  
- 运行输出（应忽略提交）  
  - `var/`、`runs/`、`clips/`、`logs/`、`dist/`：落盘输出、日志、构建结果；保持在 `.gitignore` 中。  
  - `var/problem_registry.jsonl`：selftest 失败记录（JSONL）。  
  - `var/processing/working/transcribe_diagnostic.jsonl`：转写诊断日志（默认启用，可用 `ACFV_TRANSCRIBE_DIAGNOSTIC=0` 关闭）。  
  - `var/processing/working/transcribe_checkpoint.json`：转写最后进度快照（按关键阶段或时间间隔写入，可用 `ACFV_TRANSCRIBE_CHECKPOINT_INTERVAL_SEC` 调整）。  
  - `var/processing/working/transcribe_payload.json`：转写子进程输入载荷（用于保护模式）。  

验收入口（默认）  
```bash
# Linux/macOS
bash scripts/verify.sh

# Windows
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

CLI 快速入口（当前）  
```bash
python -m acfv.cli --help
python -m acfv.cli pipe clip --help
python -m acfv.cli gui --help
```

如需仅做轻量检查，可运行：
```bash
python -m compileall -q src
python tools/contract_selftest.py
```
