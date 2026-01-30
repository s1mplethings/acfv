# Twitch Downloader Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 输入/凭证校验 | contract_input 描述 url/out_dir/retries/chat/client_id/token；AC-TD-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_twitch_downloader_inputs_outputs` |
| 输出存在性与命名 | contract_output 描述 video/chat 路径、schema_version、命名规则；AC-TD-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_twitch_downloader_inputs_outputs` |
| 失败重试策略 | spec 描述重试/日志/返回非零；AC-TD-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_twitch_downloader_failure_paths_documented` |
