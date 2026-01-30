# Render Clips Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 输入/选段校验 | contract_input 覆盖 segments 越界/排序/可写目录；AC-RC-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_render_clips_inputs_outputs` |
| 输出命名与确定性 | contract_output 描述命名规则/排序/schema_version；AC-RC-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_render_clips_inputs_outputs` |
| ffmpeg 错误处理 | spec 记录失败返回非零与日志；AC-RC-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_render_clips_failure_paths_documented` |
