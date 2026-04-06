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
