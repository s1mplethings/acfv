# Extract Audio Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 输入校验与采样率约束 | contract_input 覆盖路径/采样率/声道；AC-EA-001/002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_extract_audio_inputs_outputs` |
| 失败路径 | spec 描述 ffmpeg 失败返回非零与日志；AC-EA-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_extract_audio_failure_paths_documented` |
