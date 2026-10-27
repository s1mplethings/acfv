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

### 2026-04-10 长视频仍受 stage barrier / 高频 runtime 重写影响，局部并发不能形成端到端流水
- 现象：`gpu_asr_pool.max_workers` 与 `render_pool.max_workers` 已存在，但长视频仍表现为转录整体完成后才进入后续选择/渲染；runtime item 更新频繁重写 `transcribe_runtime.json` / `render_runtime.json`，Windows 并发渲染时可能放大 IO 与锁竞争。
- 触发：2.1.0 长视频主线执行，尤其是多 chunk ASR + 多 clip render。
- 原因判断：
  - `modular.runner` 按 module artifact 串行执行，形成外层强 stage barrier。
  - `transcribe_audio` 插件过去等整段 transcript 返回后才拆 chunk transcript，无法让下游消费局部结果。
  - ASR 子进程内 chunk loop 是 `extract -> transcribe -> next`，音频切片和 GPU 转写没有重叠。
  - runtime summary JSON 每次 item 状态变化都全量重写。
- 解决方案：
  - 保留 canonical 10-stage 语义，在 `transcribe_audio` stage-local dispatcher 上增加 streaming window fast path：chunk 成功后写 `work/chunks/<chunk_id>/transcript.json`，记录 incremental merge / clip work item 事件，并投喂 `render_pool`。
  - `steps/transcribe_audio/impl.py` 使用 `io_pool` 预取 audio chunk，单 GPU worker 连续消费准备好的 chunk。
  - `render_clips` 最终阶段复用 streaming fast path 已产出的目标文件，仍由完整 `clip_manifest.json` / `export_results.json` 做最终汇总。
  - `runtime.py` 增加 `work/runtime/events.jsonl`，summary JSON 改为周期刷新 + finalize 强制刷新。
- 验证：
  - `python -m pytest -q tests\\integration\\test_phase3_runtime_state.py tests\\integration\\test_unified_pipeline_contract.py tests\\integration\\test_render_clips_priority.py` 通过。
  - 新增测试确认 chunk0 完成后 render 可在 chunk1 完成前启动，`events.jsonl` 含 `incremental_merge_done` / `clip_work_item_queued`，且 `audio_chunk_manifest.json` 不含执行态字段。

### 2026-04-10 verify 通过但无法证明 streaming 更快或流程更对
- 现象：`verify.ps1`、pytest、contract checks 都能通过，但这些质量门不能直接回答 TTFCk、TTFC、首个 clip 是否早于完整 transcribe、early render 是否被最终阶段复用、runtime 目录是否被辅助文件污染等问题。
- 触发：2.1.0 streaming execution 改造完成后，需要证明真实长视频流程更合理。
- 原因判断：原有测试偏单元/contract 回归，缺少统一 benchmark meta、事件时间线分析、artifact/runtime 分离复检、资源采样和 JSON/MD 报告。
- 解决方案：
  - 新增 `scripts/benchmark_streaming.py`，支持 `run` 和 `collect` 两种模式。
  - 统一输出 `var/benchmarks/<run_id>/meta.json`、`results.json`、`timeline.json`、`report.md`。
  - 自动分析 `events.jsonl` 得到 TTFCk / TTFC / TAT / TTR / E2E 和 `first_clip_before_all_transcribe_done`。
  - 自动校验 contract artifact 不含 runtime-only 字段，且 `work/runtime/` 只包含 `transcribe_runtime.json`、`render_runtime.json`、`events.jsonl`。
  - 把 streaming fast path 的临时 render seed manifest 移到 `work/streaming/`，避免污染 runtime 目录。
- 验证：
  - `python -m pytest -q tests\\integration\\test_benchmark_streaming.py` 通过。
  - `python scripts\\benchmark_streaming.py collect --case-id ... --run-dir ...` 可对已有 run 生成 benchmark 报告。

### 2026-04-11 streaming fast path 重复窗口会制造假并发并浪费 render/CPU/IO
- 现象：真实长视频运行中，同一时间窗反复出现 `incremental_merge_done`、`clip_work_item_queued`，并生成多个不同 `clip_id` 指向同一 `(start,end)` 范围，导致 render 重复做工、runtime/event 变脏、GUI 观察面更乱。
- 触发：`transcribe_audio` fast path 收到重复 chunk 成功回调，或同一逻辑窗口被多次 merge 扫描命中。
- 原因判断：streaming fast path 之前只靠递增 `clip_id/rank` 标识临时 work item，没有稳定窗口 identity，也没有“已生成/已入队/已完成”检查；`runtime.py` 对相同 item 的重复更新也会反复写 `item_state_changed`。
- 解决方案：
  - `transcribe_audio` fast path 基于归一化 `(start_ms,end_ms)` 建立稳定窗口 identity。
  - 第一层在 work-item 生成处去重：重复 chunk result / 重复窗口只记 dedup 事件，不再创建新 clip work item。
  - 第二层在 render submit 前再检查窗口状态，命中时写 `render_enqueue_skipped_duplicate`，拒绝重复进入 render queue。
  - `runtime.py` 对相同 item 的重复状态更新按幂等处理，避免 event/runtime summary 被重复成功事件撑脏。
- 验证：
  - `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; python -m pytest tests\\integration\\test_phase3_runtime_state.py -q`
  - 用例覆盖重复窗口只渲染一次、render enqueue guard 生效、`render_reuse_existing_output` 仍可观测。

### 2026-04-10 直接运行 pytest 可能被本机 pytest-qt 插件抢先加载失败
- 现象：未设置仓库 verify 环境时直接执行 `python -m pytest ...`，本机 `pytestqt` 插件自动加载 `PyQt5.QtCore`，可能报 `ImportError: DLL load failed while importing QtCore`。
- 触发：PowerShell 中直接运行 pytest，且当前 Python 环境存在 pytest-qt 但 Qt DLL 搜索路径不完整。
- 原因判断：这是本机测试插件自动加载问题，不是 ACFV 测试本身失败；仓库 `scripts/verify.ps1` 已设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。
- 解决方案：按 verify 方式运行测试：`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; python -m pytest ...`。
- 验证：`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; python -m pytest tests\\unit\\test_gui_job_controller.py -q` 通过。

### 2026-04-12 本机 `openai-whisper` 的 `small.pt` 缓存损坏会拖慢转录并回退到 tiny
- 现象：直接运行 `transcribe_audio(...)` 且指定 `model_size='small'` 时，`whisper` 警告 `small.pt exists, but the SHA256 checksum does not match`，随后重新下载失败并触发代码内 tiny 回退。
- 触发：CPU 环境下用 `engine='openai-whisper'` 转录 `var\\bench\\chunk0_15s.wav`。
- 原因判断：本机 `C:\\Users\\sunom\\.cache\\whisper\\small.pt` 已损坏；当前实现会在模型加载失败时降级到 `tiny`，所以会同时出现“等待更久”和“效果没变好”。
- 解决方案：删除损坏的 `small.pt` 后重新下载，或改装/切换到 `faster-whisper` / `hf-whisper`；测速时若只想验证链路，可显式指定 `model_size='tiny'` 避免误判。
- 验证：
  - `transcribe_audio(...)` 指定 `small` 时日志出现 checksum mismatch，并最终返回 `engine='openai-whisper'` 但文本效果接近 tiny。
  - `transcribe_audio(...)` 指定 `tiny` 时 15 秒样本可稳定完成，耗时约 `3.8s`（冷）/ `2.5s`（同进程热）。

### 2026-04-12 长回放 `faster-whisper + medium + cuda` 可能在单个 chunk 上卡死，GUI 只会重复打印最后 checkpoint
- 现象：真实回放 run 中，日志长时间重复 `transcribe_chunks 45/172 chunk_0044 done`，但进度不再前进；`transcribe_runtime.json` 停在 `completed_chunks=45`，最后诊断事件是 `chunk_transcribe_start`，没有后续 `ok/error`。
- 触发：GUI 处理 `E:\\boardcasts\\DARKWOOD_-_SARUEI_FOR_10_OFF_gg_-_CHECK_OUT_BEYOND_TH_c20396_2025-11-02_13-06-31_26078238.mp4`，使用 `faster-whisper / medium / cuda / split=120`。
- 原因判断：
  - 单独抽取的 `chunk_45.wav` 用新进程可在约 `11s` 内正常转完，说明音频 chunk 本身不是坏文件。
  - 根因更像是长时间复用同一个 `faster-whisper/CUDA` 子进程后，native 推理在某个 chunk 上挂死；父进程只轮询 checkpoint，所以会反复打印最后一条已知状态。
- 解决方案：
  - 在父进程 `_run_transcribe_subprocess(...)` 增加 `ACFV_TRANSCRIBE_CHUNK_TIMEOUT_SEC` watchdog；默认单 chunk 超时 `180s`。
  - `run_transcribe_subprocess_guarded(...)` 遇到 `stalled` 先重启同配置子进程，再考虑 fallback；默认 `ACFV_TRANSCRIBE_STALL_RESTARTS=1`。
  - `transcribe_audio` 子进程支持从 `chunk_result_dir/chunk_XXXX/transcript.json` 断点续跑，重启后跳过已完成 chunk，不从头开始。
- 验证：
  - 单独转录 `run_004\\work\\chunks\\_stage\\chunk_45.wav`：`11.0s` 完成，`segments=12`。
  - 单测覆盖 `stalled` 时先重启同 payload、以及已存在 chunk result 时复用缓存结果。

### 2026-04-13 弹幕 HTML 存在但 GUI 分析显示“弹幕文件不存在”
- 现象：分析阶段日志显示 `📺 弹幕文件: ❌ 不存在`，但视频同目录下实际存在 `<video>_chat.html`；`run/work/chat.json` 只有空值，后续分析退化为只看转录。
- 触发：GUI 处理本地回放，`ENABLE_CHAT_SENTIMENT_ANALYSIS=False`，同时本机 `transformers -> PIL` 链路里的 `PIL._imaging` DLL 缺失。
- 原因判断：
  - `steps/extract_chat/impl.py` 之前在模块顶层直接 `from transformers import pipeline`。
  - 即使聊天情感分析已关闭，导入 `extract_chat` 时仍会触发 `transformers` 导入；而 `transformers` 又会连带导入 `PIL.Image`。
  - 当 `PIL._imaging` 缺失时，`extract_chat` 模块整体导入失败，modular `extract_chat` plugin 只能回退成空聊天结果。
- 解决方案：
  - 把 `transformers` 改成 `_build_sentiment_pipeline(...)` 内按需导入。
  - 关闭逐条聊天情感分析时，不再依赖 `transformers/PIL`，仅用 `BeautifulSoup` 解析 HTML 并写出 `work/chat.json`。
- 验证：
  - 真实文件 `E:\\boardcasts\\DARKWOOD_-_SARUEI_FOR_10_OFF_gg_-_CHECK_OUT_BEYOND_TH_c20396_2025-11-02_13-06-31_26078238_chat.html` 可提取 `7612` 条聊天。
  - 单测 `tests\\unit\\test_extract_chat_impl.py` 通过，覆盖“禁用情感分析时仍可解析 HTML”。

### 2026-04-13 长回放在固定 chunk 上反复卡住时，单进程 chunk 间显存/内存累积可能放大 `ctranslate2/CUDA` 挂死概率
- 现象：转录能连续完成几十到上百个 chunk，但在某个固定 chunk（如 `chunk_0090`）进入 `chunk_transcribe_start` 后长时间无返回，最终被 watchdog 以 `stalled during chunk ... for 180s` 杀掉。
- 触发：GUI 长回放转录，`faster-whisper + medium + cuda + split=120`。
- 原因判断：
  - 根因仍在 native 推理层，但长时间复用同一个子进程会让临时 chunk wav、Python 对象和 CUDA cache 持续累积。
  - 即使单个坏 chunk 不致命，累计的显存碎片/缓存压力也会提高后续挂死概率。
- 解决方案：
  - 在 `steps/transcribe_audio/impl.py` 的 chunk 循环内，每个 chunk 完成后立即删除临时 wav。
  - 同时执行 `gc.collect()`，CUDA 路径再执行 `torch.cuda.empty_cache()` 和 `torch.cuda.ipc_collect()`。
  - 进一步在 `faster-whisper` 长回放中增加“分批子进程回收”：默认每 `60` 个新 chunk 主动结束当前子进程，父进程立即用同 payload 重启，并复用 `work/chunks/chunk_XXXX/transcript.json` 继续后续 chunk，避免单个 native 进程长期存活到 `chunk_0090` 左右再退化。
- 验证：
  - 单测覆盖 `_transcribe_with_splitting(...)` 会对每个 chunk 调用统一清理钩子。
  - 真实文件 `chunk_0090.wav` 单独在新进程中 GPU/CPU 均可在约 `10s` 内完成，说明卡点不在 chunk 文件本身，而在长寿命转录子进程。

### 2026-04-13 `faster-whisper` 模型未缓存且 Hugging Face 访问异常时，GUI 会长时间重复显示 50% 进度
- 现象：终端或日志持续重复 `progress 50/100 (MaxRetryError(... huggingface.co ... SSLEOFError ...))`，看起来像任务一直在跑，但实际上还没开始转录第一个 chunk。
- 触发：GUI 重新开始处理本地回放，网络曾中断或当前环境无法稳定访问 `huggingface.co`，而 `faster-whisper-medium` 本地缓存又不可用。
- 原因判断：
  - `FasterWhisperModel(...)` 会在模型未缓存时调用 `huggingface_hub.snapshot_download(...)`。
  - 子进程已把 `transcribe_error` 写入 checkpoint，但父进程还在轮询同一个 checkpoint，并每隔 15 秒重复打印旧的 50% 进度信息。
- 解决方案：
  - `steps/transcribe_audio/impl.py` 现在先尝试 `download_model(..., local_files_only=True)` 查本地缓存；如果缓存存在，直接从本地路径加载，不访问 Hugging Face。
  - 若模型未缓存且 Hugging Face 访问失败，会把错误改写成明确的“模型未缓存/网络不可用”提示。
  - 父进程一旦读到 `transcribe_error` checkpoint，会立即终止子进程并抛出错误，不再反复打印同一条 50% 日志。
- 验证：
  - 单测覆盖“优先使用本地 faster-whisper 缓存”和“读到 `transcribe_error` checkpoint 后立即失败”。

### 2026-04-14 `optional_analysis` 在 Windows GBK 终端上可能被 emoji 进度文本直接打死
- 现象：分析阶段已经完成大部分工作，但一进入超快特征提取就报 `gbk codec can't encode character '\u26a1'`，GUI 弹出 `optional_analysis failed`。
- 触发：Windows 控制台编码为 GBK/CP936，`steps/analyze_segments/impl.py` 启用 `tqdm`，并使用 `⚡超快特征提取`、`⚡超快特征计算` 这类带 emoji 的进度文本。
- 原因判断：
  - 常规日志通过 `main_logging` 可容错，但 `tqdm` 会直接向控制台流写文本。
  - 当控制台编码不支持 emoji 时，`tqdm`/阶段名写入触发 `UnicodeEncodeError`，导致分析流程被异常打断。
- 解决方案：
  - 在 `steps/analyze_segments/impl.py` 增加控制台文本降级函数，先按当前流编码把不可写字符替换掉，再喂给 `tqdm` 和阶段进度回调。
  - 不改文件输出和业务逻辑，只修控制台/进度显示通道。
- 补充：
  - 项目里还有旧 `features/modules/core.LogManager` 会重置 root logger；如果它继续挂普通 `logging.StreamHandler(sys.stdout)`，后续任意 `✅/❌` 日志仍可能再次触发 GBK 编码错误。
  - 现已统一改为复用安全 stream handler，并在 `main_logging` 底层直接处理 `UnicodeEncodeError`。
- 验证：
  - 单测覆盖 GBK 流下会把 `⚡` 安全替换，并确认 `ultra_fast_parallel_extraction(...)` 给 `tqdm`/回调的文本不再含原始 emoji。

### 2026-04-16 GUI/重定向控制台下 `tqdm` 仍可能抛 `OSError: [Errno 22] Invalid argument`，导致 `optional_analysis` 失败
- 现象：GUI 处理长回放时，`screen_detect / screen_understanding / speaker / subtitle` 已经完成，但任务在 `optional_analysis` 阶段直接失败；弹窗摘要只有 `[Errno 22] Invalid argument`。
- 触发：Windows GUI 或 stdout/stderr 被重定向的环境里，`steps/analyze_segments/impl.py` 的 `ultra_fast_parallel_extraction(...)` / `parallel_feature_extraction_with_checkpoint_original(...)` 继续使用 `tqdm` 更新控制台进度条。
- 原因判断：
  - `main_logging` 已能兜住普通 `logging` 输出，但 `tqdm` 的 `update()/close()` 仍会直接写控制台流。
  - 当流处于无效状态、伪终端、被 GUI 接管或底层句柄异常时，Windows 可能直接抛 `OSError(22, "Invalid argument")`。
  - 这类异常会中断分析主链，进而表现为 `optional_analysis failed`，但实际不是业务分析本身失败。
- 解决方案：
  - 给 `tqdm` 初始化、`update()`、`close()` 全部加 best-effort 包装，异常时只记 warning，不允许再打断 clip 主链。
  - 维持原有进度回调；仅在控制台进度条不可用时自动降级为空实现。
- 验证：
  - `tests\unit\test_analyze_segments_logging.py` 新增 `test_ultra_fast_parallel_extraction_tolerates_broken_tqdm_stream`，模拟 `OSError(22)` 后仍能正常返回特征结果。
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests\unit\test_analyze_segments_logging.py tests\unit\test_main_logging.py` 通过。

### 2026-04-28 环境变量 `OPENAI_BASE_URL` 会污染 `provider=disabled` 合同测试
- 现象：执行 `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` 时，`tests/integration/test_provider_contracts.py::test_llm_provider_contract_normalizes_config[payload2-disabled-]` 失败，断言 `resolved.base_url == ''`，实际拿到 `https://api.gptsapi.net/v1`。
- 触发：当前 shell/环境中存在全局 `OPENAI_BASE_URL`（或等价 API 基址变量）时运行 pytest。
- 原因判断：测试用例输入是 `providers.llm.default=disabled`，但配置解析仍从环境变量回填了 base_url，导致 disabled 分支断言被外部环境污染。
- 解决方案：运行 verify 前清空该变量，或在隔离环境执行。示例（PowerShell）：`Remove-Item Env:OPENAI_BASE_URL -ErrorAction Ignore`。
- 验证：清空变量后重跑 `python -m pytest -q tests/integration/test_provider_contracts.py`，`provider=disabled` 用例应恢复通过。

### 2026-10-07 WSL2 虚拟磁盘缺失导致 POSIX verify 无法启动
- 现象：从 Windows 调用 Ubuntu 执行 `bash scripts/verify.sh` 时，命令在进入发行版前失败。
- 触发命令：`wsl.exe -d Ubuntu -- bash -lc "... && bash scripts/verify.sh"`。
- 原因：WSL 报 `MountDisk/HCS/ERROR_FILE_NOT_FOUND`，其发行版 `ext4.vhdx` 无法挂载；仓库脚本未开始执行。
- 解决方案：由用户修复或重新注册该 WSL 发行版后复跑 POSIX gate；不要为此修改仓库依赖或脚本。
- 替代验证：Windows first-class gate `scripts/verify.ps1`、compileall、三个 CLI smoke、209 项 pytest 与 contract checks 均通过。

### 2026-10-07 真实 Twitch 录制正常但 Library 没有创建 Recording
- 现象：真实 Twitch 检测和 FFmpeg 分段均正常，10 分钟内产生 9 个 CLOSED segment，但 Library 中 Recording、转写和 Moment 均为空。
- 触发：`StreamMonitorService` 把 `recording_started` 事件交给 `StreamLibraryBridge`。
- 原因：监控事件使用无时区的 `datetime.utcnow()`；SQLModel 的 datetime 类型拒绝该值。事件分发又只以 DEBUG 记录 hook 异常，默认日志中看起来像静默停止。
- 解决方案：事件改用 timezone-aware UTC 时间；hook 异常提升为 ERROR/exception 日志，保留完整堆栈。
- 验证：分段监控单测断言所有事件均带 UTC offset；真实片段将用修复后的 bridge 重新处理并记录 Evidence。

### 2026-10-07 Live incremental ASR 在 base Python 中回退 CPU，隔离 CUDA 子进程又产生持续队列压力
- 现象：RTX 4050 可见，但 base Python 是 CPU-only PyTorch，live segment 默认在 CPU 转写；改走已安装的 `clip` CUDA 环境后，每段独立子进程约 91 秒，超过 60 秒分段到达间隔。
- 原因：CUDA 环境探测超时仅 10 秒；并且从所选 `python.exe` 推导环境根时多取了一层父目录，未把 `clip/Lib/site-packages/torch/lib` 加入 DLL 搜索路径。
- 解决方案：CUDA 环境探测容限提高到 30 秒；正确使用 `python.exe` 所在目录作为环境根，并为当前进程注册 CUDA DLL 目录，使 live ASR 可以复用同一 GPU 模型且保持 `gpu_asr_pool=1`。
- 验证：真实 Twitch 60 秒 TS 片段在 RTX 4050 / faster-whisper medium 上首段 34.26 秒、复用模型后次段 7.79 秒；显存观测峰值约 1859 MiB。对应 RTF 为 0.571 和 0.130。

### 2026-10-07 Segment 处理失败会遗留 active session 并污染下一次直播
- 现象：closed segment 的 ASR future 抛错后，录制结束事件在等待 future 时提前退出；bridge 内仍保留旧 Recording 和 LiveProcessingService。下一次同频道开播可能把旧 Recording 重新标为 RECORDING。
- 原因：future 异常发生在 `_active`、`_live` 和 `_segment_futures` 清理之前，且只等待到首个失败 future。
- 解决方案：排空所有 segment futures、收集异常并无条件清理 session state；清理完成后再报告聚合错误。失败 Recording 仍先持久化为 FAILED。
- 预防与验证：`test_segment_failure_cleans_active_session_before_next_capture` 覆盖失败状态、三类内存状态清理，以及下一次 capture 创建独立 Recording。

### 2026-10-07 Library 导入真实媒体后 duration 一直为空
- 现象：本地录播成功注册且路径可访问，但 `Recording.duration_ms` 为 `None`；Library GUI 无法显示时长，ClipProposal 也无法按录播末尾裁剪边界。
- 原因：注册逻辑只读取文件大小与 mtime，从未探测容器 duration；capture 完成时也没有刷新媒体元数据。
- 解决方案：Library scanner 增加独立、可失败降级的 ffprobe duration 探测；本地导入和 capture 完成路径同时刷新 duration、大小和 mtime。
- 预防与验证：单测覆盖 import 与 capture completion；隔离数据库实际注册本机 10 个录播，重启后 10 条记录及 52.431 小时时长完整保留。

### 2026-10-07 Monitor 正常 stop 可能遗留 FFmpeg 并把受控停止误报为失败
- 现象：`run()` 先取消 watcher，`_record_once()` 的 finally 随即从 `_active` 移除 FFmpeg；后续 `_terminate_recordings()` 看不到该进程。即使进程被外部停止，非零退出也统一记录为 `recording_failed`。
- 原因：关停顺序与 capture lifecycle 相反，且没有区分 controlled stop 与 unexpected exit。
- 解决方案：先终止 active capture 并等待 watcher 收尾，再取消超时 watcher；stop event 下的非零退出会关闭最终 segment、concat 并发出带 `controlled_stop=true` 的 `recording_finished`。无 stop event 的退出仍是 FAILED。
- 预防与验证：`test_controlled_stop_finishes_recording_instead_of_reporting_failure` 覆盖最终文件、事件分类和无 failure 事件。

### 2026-10-07 受控停止的五秒 watcher 超时会取消真实 finalization
- 现象：15 分钟真实 Twitch 运行完成 15 个 segment 和 22 个 provisional Moment 后，监控只发出 `shutdown`，没有 `recording_finished`；Library 的 Recording 永久停在 `RECORDING`。
- 原因：`run()` 终止 FFmpeg 后只给 watcher 五秒收尾。真实路径还要关闭最终 segment、等待单 worker ASR 队列、拼接媒体并触发 Moment finalization，超过五秒时 watcher 会在完成事件发出前被取消。
- 解决方案：FFmpeg 终止后完整等待所有 watcher 完成受控收尾；仅在 watcher 完成后发出 `shutdown`。watcher 的异常被收集并记录，不再用固定五秒超时换取静默数据状态漂移。
- 预防与验证：`test_run_waits_for_slow_controlled_finalization_before_shutdown` 模拟超过五秒的队列排空，并断言 `recording_finished` 严格先于 `shutdown`。

### 2026-10-07 下一个 segment 已创建不代表前一个 segment 已完成刷盘
- 现象：真实 Twitch 运行中，`segment_000000.ts` 最终经 ffprobe 为 59.999 秒，但 closed 事件刚发出时 ASR 只读到 40.064 秒；后续 segment 也出现只转写 50 秒的情况，导致静默丢失尾部 transcript 和 Moment。
- 原因：segment watcher 看到下一个文件后立即发布前一个文件。Windows 下 FFmpeg 创建下一文件时，前一 TS 仍可能有缓冲数据尚未完成写入；消费者与最终 flush 发生竞态。
- 解决方案：前一文件的 size 和 mtime 必须连续两次轮询稳定后才发布；FFmpeg 退出后的最终扫描仍可直接发布，因为此时进程已完成全部写入。
- 预防与验证：`test_segment_is_not_published_until_previous_file_is_stable` 在下一文件存在后继续修改前一文件，确认不会提前发布 partial media。

### 2026-10-07 首个 live segment 才初始化 ASR 运行时导致冷启动 TTFS 超标
- 现象：15 分钟真实直播首段从关闭到 searchable 需要约 71 秒，首个内容事件到 LIVE_SESSION 可检索约 139 秒，超过 120 秒 gate；后续暖段通常只需约 8 秒。
- 原因：转写模块导入、OpenMP/CUDA 环境初始化和 transcribe Python 探测全部延迟到首段关闭以后，浪费了首个 segment 正在录制的 60 秒窗口。
- 解决方案：`recording_started` 后立即把 best-effort ASR warmup 放入同一个单 worker 队列，保证它严格先于首段任务且不增加 GPU worker 数；设置项目既有的 `KMP_DUPLICATE_LIB_OK` 防止 FAISS 已加载时后导入 PyTorch 触发本机 OpenMP abort。
- 预防与验证：回归覆盖 runtime discovery 和 `warmup → segment → finalize` 顺序；修复后的真实 Twitch 查询在开始录制约 97 秒时已可检索，恢复到 120 秒目标内。

### 2026-10-07 GUI 环境选择偏好 CUDA 却未验证 Product Layer 依赖
- 现象：`python -m acfv.cli gui run` 自动切换到 `D:\anaconda\envs\clip\python.exe`，窗口只显示 `ACFV (Fallback GUI)`；错误为 `No module named 'sqlmodel'`，Creator/Library/Conversation/Clip 全部无法进入。
- 原因：环境 probe 只检查 PyQt5、ASR 和 CUDA，并以 CUDA 高分选择环境；没有验证完整 GUI 导入必需的 Product Layer persistence 依赖。
- 解决方案：GUI 环境 probe 增加 `sqlmodel`，候选环境必须同时具备 PyQt5 和 sqlmodel 才能被选中；CUDA 仍只在满足 GUI 基线的候选之间作为性能偏好。
- 预防与验证：`test_pick_better_python_rejects_cuda_env_missing_gui_dependencies` 覆盖“CUDA 环境更快但缺少 sqlmodel”不得重启过去；真实 GUI smoke 使用 base Python 继续验证。

### 2026-10-07 live ASR 条目越过 closed segment 边界并与下一段重叠
- 现象：真实 transcript 中，segment 8 的最后一条从 540s 延伸到 542s，而 segment 9 的首条从 540s 开始，合并后出现 2s 不同文本重叠。
- 原因：增量转写只增加 segment offset，没有用 manifest 的 `start_ms/end_ms` 约束 ASR 输出；模型段尾 overshoot 会进入 Moment 和 index。
- 解决方案：绝对时间转换将证据裁剪到 closed segment 区间，裁剪后零长度条目丢弃。
- 预防与验证：`test_transcript_entries_are_bounded_to_closed_segment_timeline` 构造段尾 overshoot 和下一段首条，断言合并结果相接且无重叠；live E2E 同时通过。

### 2026-10-07 Creator 更新校验不完整且 Source enabled 没有 canonical service 写路径
- 现象：Creator 可被更新为空显示名，或把 slug 改成已占用值后才由数据库抛底层约束错误；`Source.enabled` 已持久化但 Product Layer 没有启停方法。
- 原因：`update_creator` 没有执行 create 路径已有的归一化、必填和唯一性检查；Source 状态只有 model，没有 service mutation。
- 解决方案：更新时 trim 并拒绝空名称，slug 冲突转成明确 `ValueError`；增加 `LibraryService.set_source_enabled`。
- 预防与验证：单测覆盖 Unicode rename、空名称、重复 slug、Source disable/enable、未知 Source 和重启持久化。

### 2026-10-08 exFAT 构建盘耗尽后跨卷迁移无法使用 junction，缓存音频路径失效
- 现象：真实 Library 构建写满 E 盘；10,087,616,962 字节派生产物迁移到 F 盘后，PowerShell 创建跨卷 junction 返回“函数不正确”，ASR 续跑仍读取缓存 artifact 中的 E 盘绝对音频路径。
- 触发：E 盘为 exFAT、F 盘为 NTFS；使用 `--build-root F:\ACFV-Derived\real_library_build_20261007` 恢复已迁移 run。
- 原因：exFAT 不支持所需的 NTFS junction；提取音频 artifact payload 会持久化原始绝对路径，run 目录迁移后路径过期。
- 解决方案：构建与验证显式传入 F 盘 `--build-root`；转写插件发现缓存路径不存在时，只按同名文件重定位到当前 run 的 `work/audio`，保留既有 chunk checkpoints。
- 预防与验证：集成测试覆盖迁移后的精确重定位；42 项 builder/transcribe/runtime 相关测试通过，真实 recording 8 继续验证 29 个缓存 chunk 复用。

### 2026-10-08 已迁移 run 被残留旧目录遮蔽，REUSE 后完整性检查误报 transcript 缺失
- 现象：构建审计能找到 F 盘已迁移 run，但数据库仍记录 E 盘旧 `artifact_root`；旧空目录存在时，REUSE 后的完整性检查把 7 个已完成录播误报为 `missing transcript`。
- 原因：审计优先选择数据库路径，只在该目录完全不存在时才使用显式 `--build-root`；后置检查又直接读取旧 `recording.artifact_root`。
- 解决方案：显式 build root 下存在稳定 run 时始终优先使用它，后置检查同样优先使用本次 run 目录；数据库路径只作为兼容回退。
- 预防与验证：`test_audit_prefers_explicit_build_root_after_run_relocation` 覆盖“旧目录仍存在、真实 transcript 已迁移”的场景；定向测试 5 项通过，真实重启审计恢复为 9 READY、0 failed。
- 环境备注：长时任务在 Windows PTY 中曾出现 `logging.StreamHandler.flush()` 的 `OSError(22)` 噪声；改为把构建输出重定向到 `var/real_library_build_continued.log` 后，业务进程和检查点正常续跑。该日志属于忽略的运行产物，不提交。

### 2026-10-08 ffmpeg 静音检测被 Unicode 媒体路径触发的 GBK 解码错误中断
- 现象：最终真实剪辑验证时，`subprocess` 的 stderr reader 以系统 GBK 解码 ffmpeg 输出，遇到特殊字符文件名后抛 `UnicodeDecodeError`；`stderr` 变为 `None`，静音解析又触发 `TypeError`。
- 原因：验证器使用 `text=True` 但未指定编码，Windows 因而采用区域默认编码；真实媒体路径并不保证可由该编码表示。
- 解决方案：ffmpeg/ffprobe 捕获输出统一显式使用 UTF-8 并以 replacement 容错；静音解析同时接受空 stderr，避免诊断通道故障中断质量验证。
- 预防与验证：新增 Unicode 媒体路径回归，断言 `encoding=utf-8`、`errors=replace` 且空 stderr 安全处理；真实库验证定向测试 6 项通过。

### 2026-10-08 隔离恢复验证未释放 SQLite engine，Windows 无法清理临时数据库
- 现象：隔离副本已完成重建、检索、剪辑与反馈持久化，但离开 `TemporaryDirectory` 时删除 `library.db` 报 `WinError 32`。
- 原因：首次启动与模拟重启创建的两个 `LibraryService` 各自持有 SQLAlchemy engine；Windows 不允许删除仍被连接池占用的 SQLite 文件。
- 解决方案：隔离验证使用 `try/finally`，先 dispose 重启实例，再 dispose 原实例，之后才退出临时目录。
- 预防与验证：新增真实 SQLite 文件 dispose 后可删除的 Windows 回归；真实库验证定向测试 7 项通过。

### 2026-10-08 Hybrid retrieval 的 FTS SQLite context 未显式 close，临时索引在 Windows 被锁定
- 现象：主 Library engine 已 dispose 后，隔离恢复目录仍因 `index/moments_fts.db` 的 `WinError 32` 无法清理。
- 原因：`sqlite3.Connection` 的 context manager 只管理事务，不保证在退出时关闭连接；FTS rebuild/search 依赖对象析构释放文件句柄。
- 解决方案：FTS rebuild 与 lexical search 使用 `contextlib.closing` 包装连接，事务 context 保留在其内部，确保函数退出前关闭句柄。
- 预防与验证：新增 rebuild + search 后立即递归删除 index 目录的 Windows 回归；hybrid retrieval 与真实验证定向测试 11 项通过。

### 2026-10-09 长时 embedding 完成后 exFAT 目标目录瞬时返回 WinError 433
- 现象：e5-base 对 24,351 条 retrieval representation 完成约 20 分钟 CPU 编码后，在最终创建/确认 `moment_index_v4_base` 目录时返回 `WinError 433: 指定的设备不存在`；目录稍后可正常读取和写入。
- 触发：使用相对 E 盘路径执行长时 index rebuild，最终由 `faiss_index.build_index` 再次调用 `Path.mkdir(..., exist_ok=True)`。
- 原因：E 盘在最终落盘瞬间出现设备可用性抖动；模型编码本身无错误，剩余空间约 12.2 GB。
- 解决方案：重试时使用已验证的绝对目标路径；保留已完成的 small 索引作为可回滚路径，不覆盖任何已有 index generation。
- 验证方式：对绝对目录做独立 write probe 后删除；重试完成后校验 manifest、FAISS/NumPy 文件、查询 smoke 与 bundle receipt。

### 2026-10-10 pytest 自动加载损坏的 Qt 插件导致收集前失败
- 现象：直接运行 `python -m pytest` 时，系统环境自动加载 `pytest-qt`，随后 `PyQt5.QtCore` 因 DLL 缺失在测试收集前报错。
- 原因：全局 pytest entry point 与当前 Python/Qt 二进制环境不匹配；失败发生在 ACFV 测试代码导入前。
- 解决方案：沿用仓库正式 verify 的隔离设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，仅加载测试明确需要的插件。
- 验证方式：相同解释器下定向测试从收集前崩溃恢复为 38 项通过；正式 `scripts/verify.ps1` 已内置该设置。

### 2026-10-10 ASS 未声明设计分辨率导致字幕在 1080p 成片中异常放大
- 现象：配置为 40px 的字幕在 1080p 截图中占据画面大半，并遮挡游戏 HUD。
- 原因：ASS `[Script Info]` 缺少 `PlayResX/PlayResY`，libass 使用低分辨率默认坐标系后按视频尺寸放大字体。
- 解决方案：所有 ASS writer 声明 1280x720 设计分辨率和明确 WrapStyle；底部存在 HUD 的目标样本使用既有 top-caption safe-area preset。
- 验证方式：单测断言 ASS 分辨率头；真实成片重新 burn-in 并检查开头、中间、结尾三张截图。

### 2026-10-10 Argos runtime 已安装但没有语言包，双语字幕不可直接宣称 Ready
- 现象：`argostranslate` Python 包可以导入，但 installed packages 为空，English→Chinese 调用没有可用模型。
- 原因：Argos runtime 与语言模型分开分发；存在 backend 代码不等于翻译能力已经就绪。
- 解决方案：从 Argos 官方 package index 安装 `en_zh` 1.9，并在生成前执行真实句子 smoke；服务仍将缺包或空翻译映射为 `TRANSLATION_UNAVAILABLE`，禁止复制源文冒充翻译。
- 验证方式：真实翻译 `There is something behind me!` 得到中文文本；四个固定事件版本 untranslated count 均为 0。

### 2026-10-11 Conda libmamba 插件版本漂移在每个 Python/PowerShell 启动时打印警告
- 现象：命令启动时打印 `conda-libmamba-solver ... libmambapy has no attribute QueryFormat`，但目标 Python 进程继续运行并返回正确退出码。
- 原因：base Conda 的 solver plugin 与 `libmambapy` 二进制版本不匹配；问题发生在 shell 初始化，不属于 ACFV 运行逻辑。
- 解决方案：本轮不修改用户全局 Conda。验证以子进程退出码、pytest/verify 结果和实际产物为准；环境维护时应让 `conda-libmamba-solver` 与 `libmambapy` 成对升级或回退。
- 验证方式：相同警告存在时，定向测试、真实 Qwen/Argos 翻译、FFmpeg render 和正式 verify 均独立检查退出码。

### 2026-10-11 当前 base Python 的 PyTorch 为 CPU-only
- 现象：`torch.cuda.is_available()` 为 false，multilingual E5 全量新增 embedding 在 CPU 上耗时过长。
- 原因：当前解释器安装 `torch 2.8.0+cpu`，与机器是否存在 NVIDIA GPU 无关。
- 解决方案：本轮使用 representation identity + exact text 的 embedding reuse，只编码 3,315 个变化项；不修改 ASR 模型选择或用户全局 Python 环境。
- 验证方式：v5 manifest 记录 reused=23,856、encoded=3,315，固定检索集随后完整重跑。

### 2026-10-10 覆盖率插件暴露全局 editable 路径与 NumPy 重载冲突
- 现象：为新增字幕模块执行全套 `pytest-cov` 时，覆盖率插件触发 NumPy 二次加载，继而让 transformers/accelerate 在收集阶段访问当前 NumPy 不存在的 `np.dtypes.UInt32DType`；关闭插件后的正式全量测试连续两轮均为 352 passed。首次隔离插件重跑还发现全局 editable 安装仍指向 `E:\Cliper\acfv`，而不是本次工作树。
- 原因：系统 Python 同时存在全局 editable ACFV、coverage import hook 及不兼容的 NumPy/transformers 组合；问题发生在测试收集环境，不在产品执行路径。
- 解决方案：正式回归继续使用仓库 `verify` 的插件隔离；覆盖率审计显式设置 `PYTHONPATH=E:\Cliper\acfv-mvp-product\src`，只加载 `pytest_cov` 并运行本次变更的相关测试集。
- 验证方式：聚焦覆盖率 29 passed，核心新增/修改模块合计 81%；标准 `pytest -q` 与 `scripts/verify.ps1` 两轮均 PASS。新环境应优先使用仓库虚拟环境或重新安装当前工作树，避免全局 editable 漂移。

## 2026-10-11 — Standalone final-ASR benchmark could not locate cuDNN 8 DLL

- 现象：`D:\anaconda\envs\clip\python.exe scripts/build_asr_quality_review.py --device cuda`
  在首个 faster-whisper 模型推理时报 `Could not locate cudnn_ops_infer64_8.dll`。
- 原因：DLL 已存在于该环境的 `Library\bin`，但直接运行独立 benchmark 时该目录未进入
  Windows DLL 搜索路径；正式转录主线原本会执行自己的 runtime-path 初始化。
- 解决方案：benchmark 启动时把当前 Python 环境的 `Library\bin` 加入 `PATH`，并调用
  `os.add_dll_directory`；不复制或替换 CUDA/cuDNN 文件。
- 验证：重新运行相同命令，要求三模型都产生逐样本文本和运行时间；失败仍原样写入 comparison。

## 2026-10-11 — Final-ASR 候选模型与 WhisperX 环境限制

- 现象：`medium` 与 `large-v3` 可在固定 30 段集上完成；`distil-large-v3` 和 `large-v3-turbo` 的模型下载长期停在 0 bytes。当前 WhisperX 3.4.3 要求 NumPy >=2.0.2，而 clip 环境固定为 NumPy 1.26.4。
- 原因：模型缓存下载链路不可用；WhisperX 与当前已验证的 CUDA/科学计算环境存在依赖冲突。
- 解决方案：本轮不改全局 NumPy/CUDA，也不伪造候选结果。最终成片显式使用已实测的 `large-v3`，timing backend 使用可靠的 faster-whisper word timestamps；未运行模型保留为 `MODEL_UNAVAILABLE_DOWNLOAD_STALLED`，待独立环境补测。
- 验证：ASR bundle 固定保留 30 份 audio、medium/large-v3 实际文本、两个不可用候选状态及人工评审栏；metadata 明确 VAD 与 word timestamps。

## 2026-10-11 — 长事件整段 Source Correction 导致本地 Qwen 超时

- 现象：约 6 分钟事件的完整 final-ASR 文本一次性送入 Qwen 后，多次达到 90 秒超时并占用 Ollama 队列。
- 原因：保守修正器没有限制单次上下文大小；HTTP 超时不能立即取消已经进入本地模型的生成。
- 解决方案：超过 3,000 字符时不截断、不部分改写，完整保留 raw aligned transcript，并记录 `UNCERTAIN_REFINER_INPUT_TOO_LONG`；短事件仍执行上下文修正。批处理支持复用已经完成的 transcript/成片。
- 验证：超长输入单测确认模型不会被调用；真实 Q8 事件能够越过修正阶段继续完成字幕与渲染。
## 2026-10-11 — Language calibration 基线 commit 对象与 G 盘不可用

- 现象：任务指定的 evidence commit `ae63f6f7f80e363f15f49fb78b871d9ea028455a` 不在恢复仓库 object store；G 盘仍离线，无法从原 Library 路径读取固定集。
- 原因：当前工作仓库来自先前卷掉线后的可验证快照，历史对象并未完整复制；外接卷状态不属于仓库控制范围。
- 解决方案：从 `C:\Users\sunom\.codex\deliverables\acfv-final-language-quality-hardening\final-language-quality-review-pack.zip` 恢复原始 12-Clip artifact，并在分支可用父提交 `753add2` 上继续；不伪造 ancestry、不改写 main。
- 验证：构建器硬断言同一固定集为 12 Clips、1184 words、22 low-confidence words、29 local re-decodes、25 entity findings、30 broken suspects；任一数量漂移即失败。

## 2026-10-11 — 直接 pytest 未设置 src 路径时导入全局 editable ACFV

- 现象：直接调用 `pytest` 时 conftest 从旧 `E:\Cliper\acfv-mvp-product` 映射加载，随后报 `No module named acfv`。
- 原因：系统 Python 的全局 editable/source mapping 不指向当前 F 盘恢复工作树，且当前仓库未附带独立 `.venv`。
- 解决方案：与 `scripts/verify.ps1` 一致，验证前显式将当前仓库 `src` 置于 `PYTHONPATH`，并设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。
- 验证：同一解释器完整测试恢复为 474 passed；正式 verify 继续使用仓库内置环境隔离。

## 2026-10-15 — clip 环境未安装 pytest-cov

- 现象：在 `D:\anaconda\envs\clip\python.exe` 中显式加载 `pytest_cov` 运行聚焦覆盖率时，pytest 在收集前报告 `No module named 'pytest_cov'`。
- 原因：该 GPU/媒体环境没有安装可选覆盖率插件；产品依赖和正式 verify 不要求它。
- 解决方案：不临时修改共享环境或依赖事实源；以定向回归和仓库统一 `scripts/verify.ps1` 为本轮硬验收，并在 TestReceipt 中记录覆盖率工具不可用。
- 验证：VOD 下载生命周期定向回归 39 项通过；最终代码状态连续两轮 verify 均为 591 passed，contract checks PASS。

## 2026-10-16 — Creator-Adaptive 验证结果无法输出到 Windows GBK 控制台

- 现象：真实 CUDA 验证已写完 SQLite 与 JSON 产物后，CLI 在打印包含 `✨` 的转录文本时抛出 `UnicodeEncodeError: 'gbk' codec can't encode character`，进程因此返回非零。
- 原因：JSON 文件明确使用 UTF-8，但 CLI 的标准输出继承了 Windows GBK 编码，且使用了 `ensure_ascii=False`。
- 解决方案：CLI 汇总输出改为 `ensure_ascii=True`；证据文件仍保持 UTF-8 原文，不改变验证数据或阈值。
- 验证方式：在相同 Windows 非 UTF-8 shell 中重跑真实 Creator-Adaptive 验证，要求进程退出码为 0、CUDA 推理产物完整且输出可解析为 JSON。

## 2026-10-16 — Creator-Adaptive v3 独立进程加载了不完整的 cuDNN 搜索路径

- 现象：长时验证第二个真实 CUDA 工作负载在 `cudnn64_8.dll` 内以 `0xc0000409` 崩溃，并先报告找不到 `cudnn_ops_infer64_8.dll`。
- 原因：所需 cuDNN 8 组件已安装在当前 Conda 环境的 `Library\bin`，但 `run_creator_adaptive_v3.py` 没有像其他独立 CUDA 验证入口那样注册该 DLL 目录，导致先加载了 ctranslate2 自带的入口 DLL却找不到配套组件。
- 解决方案：进程启动时把当前 Python 环境的 `Library\bin` 放到 `PATH` 首位并通过 `os.add_dll_directory` 注册；保留返回的目录句柄到进程结束，不复制或替换 DLL。
- 验证方式：重跑同一 Creator-Adaptive v3 真实 CUDA 工作负载，要求无 DLL 警告、退出码为 0、所有阶段证据完整；随后执行定向回归与双轮 verify。

## 2026-10-27 — GitHub-hosted Actions runner 被账户 billing lock 阻止

- 现象：publication push 对应的 `verify-linux` 与 `verify-windows` job 均在 3–4 秒内失败，`steps=[]`、`runner_id=0`、`runner_name` 为空；GitHub check-run annotations 明确报告 `The job was not started because your account is locked due to a billing issue.`。
- 原因：GitHub 账户 billing lock 阻止 hosted runner 分配；失败发生在任何 checkout、依赖安装、pytest 或 repository code 执行之前。
- 解决方案：仓库侧只修复独立存在的 workflow YAML/严格失败语义并完成 actionlint、YAML parse 和本地 verify；不得禁用 workflow 或伪造 green。账户所有者需要在 GitHub Billing 中解除锁定，然后通过 `workflow_dispatch` 重新运行 publication verify。
- 验证方式：解除锁定后确认 Linux/Windows job 均获得非空 runner 与 steps，并以 `success` 结束；保存 run、job、runner、step 和 SHA receipt。
