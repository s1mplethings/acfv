# ACFV 2.1.0 Benchmark Validation

本文件说明如何验证 2.1.0 streaming execution 是否真的生效。canonical 10-stage、orchestrator、backend service、GUI 前后端分离和 contract artifact 语义均保持不变。

## Test Sets

- short smoke: 3-5 分钟视频，用于快速确认 CLI、artifact、events、首个 clip 提前产出。
- medium regression: 20-40 分钟视频，用于重复运行并观察 TTFCk / TTFC / TAT / TTR / E2E 的稳定性。
- long benchmark: 2-6 小时视频或用户真实长视频，用于确认长视频流水线端到端行为。

建议为每类输入准备固定路径和固定 cfg，避免每轮测试手工改参数。

## Run Benchmark

分析已有 run 目录：

```powershell
python scripts\benchmark_streaming.py collect `
  --case-id short_smoke `
  --run-dir runs\out\run_YYYYMMDD_HHMMSS `
  --input-video E:\path\sample.mp4 `
  --config var\settings\sample.yaml
```

实际跑 CLI pipeline 并收集结果：

```powershell
python scripts\benchmark_streaming.py run `
  --case-id short_smoke `
  --input-video E:\path\sample.mp4 `
  --config var\settings\sample.yaml `
  --repeat 1 `
  --preflight smoke
```

长视频基准可把 `--preflight` 改为 `none`，先单独跑一次统一 verify，再执行长视频 benchmark。

## Output

每次 benchmark 输出到：

- `var/benchmarks/<run_id>/meta.json`
- `var/benchmarks/<run_id>/results.json`
- `var/benchmarks/<run_id>/timeline.json`
- `var/benchmarks/<run_id>/report.md`

`run` 模式重复运行时，每次 repeat 还会写：

- `var/benchmarks/<run_id>/repeats/repeat_001/results.json`
- `var/benchmarks/<run_id>/repeats/repeat_001/timeline.json`

顶层 `results.json` 使用重复运行的中位数汇总 `TTFCk`、`TTFC`、`TAT`、`TTR`、`E2E`。

## Metrics

- `TTFCk`: time to first chunk transcript
- `TTFC`: time to first clip
- `TAT`: time to all transcript
- `TTR`: time to render finished
- `E2E`: end-to-end total time

关键布尔结论：

- `contract_clean`: contract artifact 完整且未包含 runtime-only 字段。
- `runtime_separate`: `work/runtime/` 只包含 `transcribe_runtime.json`、`render_runtime.json`、`events.jsonl`。
- `first_clip_before_all_transcribe_done`: 首个 clip 完成早于完整 transcribe 完成。
- `render_reuse_ok`: 最终 render stage 观察到复用 early render 输出。

## Streaming Success Criteria

一次有效的 streaming fast path run 应至少满足：

- `incremental_merge_done` 出现在 `events.jsonl`。
- `clip_work_item_queued` 出现在 `events.jsonl`。
- `render_clips_batch` item `running/succeeded` 事件早于 `transcribe_chunks` finalized。
- `results.json.first_clip_before_all_transcribe_done == true`。
- `contract_clean == true` 且 `runtime_separate == true`。

## Basic Regression

完整回归仍以统一 verify 为准：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify.ps1
```

benchmark runner 的 `--preflight smoke` 会自动运行：

- `python -m compileall -q src`
- `python -m acfv.cli --help`
- `python -m acfv.cli gui --help`
- `python -m acfv.cli pipe clip --help`

## GUI Validation

GUI 自动化以 controller / adapter 层测试为主：

```powershell
python -m pytest -q tests\unit\test_gui_job_controller.py
```

该测试验证：

- GUI 创建任务经由 backend service。
- GUI 读取 `job_state.current_stage`。
- GUI 读取 transcribe/render runtime 摘要。
- GUI 取消动作走 `cancel_job(...)`。
- GUI 日志和结果目录入口由 controller 暴露。
- GUI 错误显示来自 job error summary，不依赖控制台。

## Known Limits

- `cancel_job(...)` 仍是 best-effort。
- retry / backoff 策略未完善。
- 多 GPU ASR 未完善。
- `cpu_pool` 仍是插件层轻量整理职责，未独立配置化。
- GUI 当前仍以 runtime summary 展示为主，尚未消费 `events.jsonl` 做完整细粒度可视化。
