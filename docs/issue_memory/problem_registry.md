# Problem Registry (ACFV)

记录已遇到的问题，便于复现与避免回归。每条包含：现象、触发条件、原因、解决方案、验证方式。

示例模板：
```
- 现象：ffmpeg 输出文件 0 字节
- 触发：运行 render_clips 时，输入路径包含特殊字符
- 原因：输出临时文件扩展名无 .mp4 导致 muxer 识别失败
- 解决：临时文件命名改为 *.tmp.mp4，保持 mp4 扩展
- 验证：python tools/contract_selftest.py（通过）
```

请追加新问题至文末，避免覆盖历史记录。

---

### 2026-01-30 sklearn/numpy 二进制不兼容导致 pytest 失败
- 现象：`python -m pytest -q` 崩溃，报错 `ValueError: numpy.dtype size changed, may indicate binary incompatibility. Expected 96... got 88...`，之前 verify.ps1 未检查退出码而误报 PASS。
- 触发：在本地 Anaconda 环境执行 pytest，已安装的 `scikit-learn` 与 `numpy` ABI 不匹配。
- 原因判断：numpy/BLAS 版本与 sklearn 预编译二进制不一致。
- 解决方案：重新安装兼容版本 `pip install --upgrade --force-reinstall "numpy>=1.26,<2" "scikit-learn>=1.3,<2"`；或新建干净虚拟环境后安装依赖。
- 验证：`python -m pytest -q` 正常退出 0；`scripts/verify.ps1`/`verify.sh` 现已检查退出码，可捕获失败。

### 2026-02-06 conda-libmamba-solver 入口加载报错（工具命令输出污染）
- 现象：运行 `rg` / `Get-Content` 等命令时反复输出 `Error while loading conda entry point: conda-libmamba-solver (module 'libmambapy' has no attribute 'QueryFormat')`。
- 触发：在当前 PowerShell 环境执行任意命令（与 ACFV 代码无直接关系）。
- 原因判断：conda 环境内 `libmambapy` 与 `conda-libmamba-solver` 版本不兼容，导致入口加载失败并污染标准输出。
- 解决方案：升级/重装 conda 与 libmamba 相关包，或切换到干净的虚拟环境运行。示例：`conda update conda` 或 `conda install -c conda-forge conda-libmamba-solver libmambapy`。
- 验证：重新运行任意命令，不再输出该报错。

### 2026-02-06 Whisper 转写过程硬崩溃（Fatal Python error: Aborted）
- 现象：GUI 转写过程中进程直接退出，`transcribe_fatal.log` 显示 `Fatal Python error: Aborted`，无 Python 异常。
- 触发：使用 `faster-whisper`/CUDA 路径执行长音频转写。
- 原因判断：原生扩展/驱动层崩溃（torch/ct2/cuda）导致进程被 abort。
- 解决方案：启用转写子进程保护（`ACFV_TRANSCRIBE_GUARD=1` 默认开启），崩溃时仅子进程退出；可自动回退 `openai-whisper` + CPU (`ACFV_TRANSCRIBE_FALLBACK=1`) 或改用小模型。
- 验证：复测长音频转写，GUI 不再被直接终止；失败时写出空转写并记录日志。

### 2026-02-07 转写 fallback 路径触发 TypeError 导致容错失效
- 现象：主转写子进程失败后，fallback 分支未执行完成，直接报 `TypeError: log_warning() takes 1 positional argument but 4 were given`。
- 触发：`process_audio_segments` 在 fallback 分支使用 `%s` 占位写日志。
- 原因判断：`acfv.main_logging` 的 `log_warning/log_info/log_error/log_debug` 包装函数只接受单参数，与标准 logging 的参数风格不兼容。
- 解决方案：日志包装函数改为 `(*args, **kwargs)` 透传到底层 logging；stdout 回显路径增加消息格式化兜底。
- 验证：`python -m pytest -q tests/unit/test_main_logging.py tests/unit/test_transcribe_audio_impl.py` 通过，fallback 单测通过。

### 2026-02-07 Windows GBK 控制台下 emoji 日志触发 UnicodeEncodeError
- 现象：执行 `python -m acfv.cli pipe clip ...` 时，控制台出现大量 `UnicodeEncodeError`（emoji 无法写入 gbk）。
- 触发：导入 `acfv.main_logging` 时输出包含 emoji 的启动日志。
- 原因判断：默认 `StreamHandler(sys.stdout)` 在 gbk 编码下无法写入 emoji 字符。
- 解决方案：stdout/stderr 在可用时统一 `errors=replace`；启动日志移除 emoji；保留日志内容不丢关键信息。
- 验证：重复执行 CLI/pytest，不再出现该 UnicodeEncodeError。

### 2026-04-06 工作目录缺失真实 Git 元数据导致 `git status` 不可用
- 现象：当前目录下能看到 `.git/`，但执行 `git status --short` 返回 `fatal: not a git repository`。
- 触发：在 `E:\\Cliper\\acfv` 直接运行任意 Git 命令。
- 原因判断：该目录中的 `.git/` 只是普通文件夹（仅含 `workflows/`），缺少正常仓库元数据，可能是复制/打包后的残留目录结构。
- 解决方案：不要依赖 Git 状态做清理判断；如需版本管理能力，应重新从真实仓库检出，或恢复完整 `.git` 元数据后再操作。
- 验证：在恢复后的工作副本执行 `git status --short`，应正常返回状态而非 fatal。

### 2026-04-08 GUI 从错误 Python 环境启动，导致转录始终走 CPU
- 现象：GUI 能打开，但转录非常慢；日志显示 `openai-whisper + cpu`，长视频 60 秒音频块要转 90~400 秒。
- 触发：直接用 `D:\\anaconda\\python.exe` 启动 GUI；该 base 环境缺少 CUDA 版 torch 和 `faster-whisper`。
- 原因判断：base 环境是 `torch 2.8.0+cpu`，`torch.cuda.is_available() == False`；而 `D:\\anaconda\\envs\\clip\\python.exe` 同时具备 `PyQt5 + faster-whisper + torch 2.5.1+cu121 + CUDA`。
- 解决方案：在 `acfv.cli.gui` 增加启动自检；若当前 Python 不适合 GUI/转录，则自动重启到更优的 conda 环境（优先 `envs\\clip\\python.exe`），并透传当前 `PYTHONPATH`/临时 API 环境变量。
- 验证：`python -m pytest tests/unit/test_gui_env_selection.py -q` 通过；从 base 环境执行 `python -m acfv.cli gui run` 时，GUI 自动切到 `clip` 环境启动。

### 2026-04-09 转录子进程继承了错误的 `sys.executable`
- 现象：即使 GUI 已尝试切到更好的环境，实际运行中的 `transcribe` 子进程仍显示为 `D:\\anaconda\\python.exe`，GPU 完全没有参与，日志中 chunk 转写耗时仍然很高。
- 触发：主进程或历史运行仍留在 base 环境时，`_run_transcribe_subprocess()` 直接使用 `sys.executable` 启动子进程。
- 原因判断：转录子进程没有独立做 Python 环境选择，导致 GUI 启动修复没有完全覆盖到转录保护子进程。
- 解决方案：在 `steps/transcribe_audio/impl.py` 中增加 `_resolve_transcribe_python()`；优先选择具备 `faster-whisper + CUDA` 的 Python（当前机器上是 `D:\\anaconda\\envs\\clip\\python.exe`），再启动转录子进程。
- 验证：`python -m pytest tests/unit/test_transcribe_audio_impl.py -q` 中新增环境选择单测通过；后续转录日志会额外输出 `[transcribe] subprocess python=...` 用于确认实际使用的解释器。

### 2026-04-09 转录诊断缺少 Python 可执行文件路径，导致慢路径难以确认
- 现象：日志里只能看到 `chunk N` 和重复的进度心跳，难以直接判断当前实际运行的是 `clip` CUDA 环境还是 `base` CPU 环境；用户容易把 15 秒一次的心跳误认为“卡住不动”。
- 触发：查看 `transcribe_diagnostic.jsonl` / GUI 日志排查慢转录时。
- 原因判断：诊断事件只记录 Python 版本，不记录 `sys.executable`；转录子进程切换环境时也没有显式补 `PYTHONPATH` 到仓库 `src`。
- 解决方案：在 `steps/transcribe_audio/impl.py` 的 `start` 诊断事件追加 `python_executable`，并在子进程启动时显式构造环境，补齐 `PYTHONPATH` 与 `KMP_DUPLICATE_LIB_OK`。
- 验证：`python -m pytest tests/unit/test_transcribe_audio_impl.py -q` 通过；新的 `transcribe_diagnostic.jsonl` 可直接看到 `python_executable`，并能确认子进程环境是否切到了 `D:\\anaconda\\envs\\clip\\python.exe`。

### 2026-04-09 GUI/CLI 已共享 modular pipeline，但缺少统一 backend service 边界
- 现象：CLI `pipe clip` 直接调用 `modular.pipeline.run_pipeline(...)`；GUI 本地视频处理也在后台线程直接调用同一个函数，但 job 创建、状态查询、取消、日志获取、artifact 列表并没有统一接口。
- 触发：Phase 0 架构审计，检查 `src/acfv/cli/pipeline.py`、`src/acfv/steps/local_video_manager/impl.py`、`src/acfv/modular/pipeline.py`。
- 原因判断：项目已经完成了“共享 pipeline 核心”的一半迁移，但 service/job manager 层尚未补齐，导致 GUI 仍持有较多任务生命周期与进度映射逻辑。
- 解决方案：在后续 Phase 1 引入 backend service / job manager / job state 边界，统一暴露 `create_job`、`get_job_status`、`cancel_job`、`list_artifacts`、`get_logs`，并让 GUI 与 CLI 都通过该边界调用 pipeline。
- 验证：后续至少补一个 smoke，覆盖 `create_job -> get_job_status -> terminal state` 状态流转，并确认 GUI/CLI 都不再直接编排主线。

### 2026-04-09 Phase 1 已统一 job backend，但取消语义仍属 best-effort
- 现象：Phase 1 后 GUI / CLI / legacy backend 路径都统一通过 `acfv.backend.service` 发起 job，但取消仍主要依赖 cancel flag + progress callback 检查点，不能保证在长时间无回调的底层步骤中立刻生效。
- 触发：实现 `backend.job_manager.cancel_job(...)` 时，需要在不重写 `modular.pipeline` 和不提前进入 Phase 2/3 的前提下提供最小取消能力。
- 原因判断：当前 `modular.pipeline` 与底层 steps 还没有统一的 job token / cancellation contract；立即中断需要更细的阶段边界与步骤配合。
- 解决方案：本阶段只提供统一 `cancel_job(...)` 接口，并兼容写入 `var/processing/stop_flag.txt`；更细粒度、可预期的取消语义留到后续显式 stage contract 后再增强。
- 验证：最小 smoke 验证 `create_job/get_job_status` 与终态流转；取消能力作为 best-effort 兼容能力记录，不在本阶段承诺强实时中断。

### 2026-04-09 Phase 2 已显式主线，但 stage 与 plugin 仍是一对多映射
- 现象：当前 job_state 已能稳定反映 `ingest_video -> ... -> export_results` 这条 canonical 主线，但底层实际执行仍主要依赖 `modular.pipeline` 中的 plugin/goal 规划，`transcribe_audio` 和 `render_clips` 各自覆盖了多个 canonical stages。
- 触发：Phase 2 需要在不重写 `modular.pipeline`、不提前做并发调度的前提下显式化主线。
- 原因判断：现有 modular 结构本来按 artifact/module 组织，不是按未来的 chunk/clip execution unit 组织；如果现在强拆成多个 runner，会过早进入 Phase 3。
- 解决方案：本阶段采用“单一 stage source + stage -> step(s) 映射 + 最小 contract 文件”方案；等 Phase 3 再把 `audio_chunk_manifest` 和 `clip_manifest` 从契约文件升级为真正的并发执行输入。
- 验证：CLI `--dry-run-plan`、backend job logs、legacy compat path 与 `run_dir/work/stage_plan.json` 必须反映同一份 canonical stage 语义。

### 2026-04-09 Phase 3 Step 1 已分离 runtime state，但仍未引入真正的 pool 调度
- 现象：`work/runtime/transcribe_runtime.json` 与 `work/runtime/render_runtime.json` 已能表达 chunk/clip item 生命周期，但当前仍是单 worker 语义，主要用于执行态建模与落盘，而不是吞吐优化。
- 触发：Phase 3 第一子步要求先建立 plan input 与 runtime state 分离，禁止提前做复杂并发优化。
- 原因判断：如果在 runtime state 刚落地时就同时引入完整 pool 调度、重试与取消，会把 Phase 3 的边界重新打散，并增加回归风险。
- 解决方案：本阶段只固化 `gpu_asr_pool` / `render_pool` 等字段与边界；下一子步再在不改变 canonical 主线和 contract artifact 的前提下接入阶段内调度。
- 验证：最小测试覆盖 queued/running/succeeded/failed/cancelled 状态落盘，同时确认 `audio_chunk_manifest.json` / `clip_manifest.json` 未写入执行态字段。

### 2026-04-09 Phase 3 Step 2 已接入阶段内 dispatcher，但 runtime 文件并发写盘曾在 Windows 下冲突
- 现象：`render_pool.max_workers > 1` 的测试中，`work/runtime/render_runtime.json.tmp -> render_runtime.json` 可能报 `[WinError 5] 拒绝访问`。
- 触发：多个 render worker 在短时间内同时更新 runtime state。
- 原因判断：虽然 runtime 写盘已按 path 加锁，但 lock 自身的创建不是线程安全的，导致同一路径可能短暂出现多个不同锁对象。
- 解决方案：在 `src/acfv/pipeline/runtime.py` 增加全局 lock guard，确保 per-path lock 创建本身也串行；同时继续用原子 tmp replace 落盘。
- 验证：`tests/integration/test_phase3_runtime_state.py::test_render_pool_allows_clip_level_parallelism` 通过，`render_pool.max_workers=2` 下 clip 级并发与 runtime 写盘同时成立。

### 2026-04-09 Phase 4 已把 GUI 收敛到 job state/runtime 轮询，但历史进度组件仍偏重
- 现象：GUI 当前阶段与错误信息已经来自 backend job state，runtime 摘要也直接来自 `work/runtime/*.json`，但 MainWindow 里仍保留较重的旧进度组件与兼容线程结构。
- 触发：Phase 4 需要在不重写主窗口和不破坏既有 GUI 风格的前提下，先把 GUI 变成 backend 的控制台。
- 原因判断：直接推倒 MainWindow/ProgressManager 风险过高，也会把 Phase 4 和 UI 重构混在一起。
- 解决方案：本阶段只新增 `GuiJobController`，并让 `LocalVideoManager` 只负责 job 提交、状态轮询、错误/日志/结果入口；更彻底的 GUI 瘦身留待后续增量收敛。
- 验证：`tests/unit/test_gui_job_controller.py` 通过，GUI 代码路径已不再调用 `wait_for_job(...)` 或直接维护独立 stage 语义。

### 2026-04-09 Phase 5 回归确认当前体系稳定，但仍保留若干刻意未实现项
- 现象：全量 verify、CLI smoke、dry-run-plan、GUI controller 回归均通过，说明统一 backend 主线、阶段内调度和 GUI 前端化链路在当前代码上是成立的。
- 触发：Phase 5 只做验证与回归，不继续推进架构演进。
- 原因判断：当前主线、contract artifact、runtime state、compat wrapper 都已形成稳定边界，继续在本阶段做结构变化会打破冻结范围。
- 解决方案：将未完成事项明确保留为后续增量优化，而不是在回归阶段顺手扩写：
  - 更强取消
  - 有限 retry
  - 多 GPU ASR
  - `io_pool` / `cpu_pool` 执行器
  - GUI 更丰富的 chunk / clip 可视化
- 验证：`python -m compileall -q src`、定向 pytest、`scripts/verify.ps1`、CLI `--help` / `--dry-run-plan` 均通过。

### 2026-04-10 长视频转录在 `8/100 audio ready` 停很久，不是做了 8 个 chunk，而是单个子进程卡在模型加载前后
- 现象：6 小时级视频在 GUI 中长时间显示 `progress 8/100 audio ready, duration=0.05h`，用户容易误判为“已经跑了 8 段”；实际日志会持续重复同一条 `audio ready` 心跳。
- 触发：Phase 3 为了避免 `faster-whisper/CUDA` 直接打崩 GUI，把 `transcribe_chunks` 改成“每个 chunk 一个受保护子进程”之后，运行长视频。
- 原因判断：这里的 `8/100` 来自转录子进程内部 checkpoint，不是 chunk 序号；旧实现会对每个 chunk 重复执行：
  - ffmpeg 切片
  - 音频标准化
  - Whisper 模型加载
  - 子进程冷启动
  对 6 小时视频会放大成上百次重复初始化，既慢，也更容易在 `model_loaded` 前后卡住。
- 解决方案：将 `modular.plugins.transcribe_audio` 改成“整个 `transcribe_chunks` 阶段只启一个受保护子进程”，让子进程内部按 `split_duration` 拆 chunk 并复用同一个模型；父进程继续根据 checkpoint 更新 `transcribe_runtime.json`，从而保留 chunk 级 runtime 语义，但不再为每个 chunk 重复冷启动模型。
- 验证：`python -m pytest -q tests/integration/test_phase3_runtime_state.py tests/integration/test_unified_pipeline_contract.py tests/unit/test_transcribe_audio_impl.py tests/unit/test_gui_env_selection.py` 通过；`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` 通过。

### 2026-04-10 回放库真实视频暴露 `faster-whisper` CUDA 依赖缺失与 contract 对齐问题
- 现象：使用 `E:\\boardcasts\\brat 💢_2025-11-02_13-49-06_26078484.mp4` 做完整 `pipe clip` 回归时，`faster-whisper` 路径报 `Could not locate cudnn_ops_infer64_8.dll`；回退后曾在 `audio ready` 阶段长时间停留；首次成功 run 后 contract 校验还发现相对路径解析和 `selected_segments.json` / `clip_manifest.json` 顺序对齐问题。
- 触发：`D:\\anaconda\\envs\\clip\\python.exe -m acfv.cli pipe clip --url <replay mp4> --out-dir runs/out/replay_full_fast_brat... --cfg var/settings/replay_fast_flow.yaml`。
- 原因判断：
  - 当前 `clip` 环境具备 CUDA torch，且 cuDNN DLL 存在于 `clip\\Library\\bin`，但父进程 PATH 未包含该目录，导致 `faster-whisper` 推理阶段不能稳定找到 cuDNN。
  - 回退到过大的 `openai-whisper` 模型时，长音频可能在模型加载/准备后长时间无有效阶段推进。
  - CLI 使用相对 `--out-dir` 时，contract validator 不能假设 artifact 引用都相对 run_dir。
  - `selected_segments.json` 按得分排序，而旧 `clip_manifest.json` 曾按时间排序，真实 run 才暴露两者无法逐项对齐。
- 解决方案：
  - 转录子进程启动时将被选中的 Python 环境运行时目录前置到 `PATH`：`Library\\bin`、`bin`、`DLLs`、`Lib\\site-packages\\torch\\lib`、`Lib\\site-packages\\ctranslate2`；直接转录入口在加载 `faster-whisper` 前也同步补 PATH。
  - `run_transcribe_subprocess_guarded(...)` 在主后端失败后回退到 `openai-whisper`，优先沿用 CUDA，可用模型限制到 `small` 以内。
  - 转录子进程增加 `ACFV_TRANSCRIBE_MODEL_LOAD_TIMEOUT_SEC` watchdog，避免长时间停在 `prepare_audio_done` 无法失败转移。
  - `render_clips` 用同一份得分排序后的 plan 同步生成 `selected_segments.json` 与 `clip_manifest.json`。
  - contract validator 支持已存在的 CWD-relative artifact 引用，不改变输出目录契约。
  - CLI 日志 stdout 增加 `errors=replace`，避免 emoji 文件名在 GBK 控制台触发 `UnicodeEncodeError`。
- 验证：真实回放库 run `runs/out/replay_full_fast_brat_fixed/run_20260410_093639` 成功导出 5 个 clips；`validate_contract_artifacts(...)` 返回空错误；`audio_chunk_manifest.chunk_count = 9`、`transcript_merged.chunk_count = 9`、`clip_manifest.clip_count = 5`、`export_results.clip_count = 5`。

### 2026-04-10 `faster-whisper + large-v3-turbo + CUDA` 需要显式继承所选 conda 环境 DLL 路径
- 现象：`WhisperModel('large-v3', device='cuda')` 可以加载，但实际 `transcribe(...)` 时仍报 `Could not locate cudnn_ops_infer64_8.dll`。
- 触发：从未激活 `clip` 环境的 PowerShell / GUI 父进程启动 `D:\\anaconda\\envs\\clip\\python.exe` 子进程，使用 `WHISPER_ENGINE=faster-whisper`、`WHISPER_MODEL=large-v3-turbo`。
- 原因判断：Windows 下 ctranslate2 推理阶段依赖 `clip\\Library\\bin` 等 DLL 搜索路径；仅切换 `python.exe` 不等于激活 conda 环境，父进程 PATH 仍可能只包含 base 环境路径。
- 解决方案：`_build_transcribe_subprocess_env(...)` 根据实际选中的 `python.exe` 前置该环境 DLL 路径；`_load_faster_whisper_model(...)` 也在直接入口补当前 `sys.prefix` 相关 PATH。
- 验证：
  - 直接转录 `runs\\probe\\faster_whisper_replay\\sample_20s.wav`，关闭 fallback，返回 `engine=faster-whisper`、`segments=1`。
  - 短回放视频完整 CLI pipeline：`WHISPER_ENGINE=faster-whisper`、`WHISPER_MODEL=large-v3-turbo`、`ACFV_TRANSCRIBE_FALLBACK=0`，成功导出 1 个 clip；`transcribe_runtime.json` 为 2/2 chunks succeeded；contract 校验返回空错误。
