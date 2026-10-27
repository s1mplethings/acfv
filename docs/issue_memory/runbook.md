# Issue Runbook (ACFV)

目的：记录常见问题的最快修复步骤，便于 AI/人工快速处理。

示例条目（请追加在文末）：
- ffmpeg 输出 0 字节：检查路径字符，改用 `*.tmp.mp4` 临时名；确认 ffmpeg 可执行在 PATH；重跑。
- numpy/sklearn ABI 冲突：`pip install --force-reinstall "numpy>=1.26,<2" "scikit-learn>=1.3,<2"`。
- torch 冷启动过慢：延迟导入（懒加载 tab / 仅在需要时 import）。

实际问题请同步记录到 `docs/issue_memory/problem_registry.md`。
