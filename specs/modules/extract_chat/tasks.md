# Extract Chat Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 输入/目录校验 | contract_input 覆盖 url/recording_dir/out_dir/retries；AC-EC-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_extract_chat_inputs_outputs` |
| 输出排序与 schema | contract_output 描述 schema_version、时间戳升序；AC-EC-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_extract_chat_inputs_outputs` |
| 重试与失败路径 | spec 描述 CLI 失败重试与日志；AC-EC-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_extract_chat_failure_paths_documented` |
