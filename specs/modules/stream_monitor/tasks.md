# Stream Monitor Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 配置与输入契约 | contract_input 覆盖 targets/interval/output_dir/twitch/chat；AC-SM-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_stream_monitor_inputs_outputs` |
| 输出与命名契约 | contract_output 描述录制/命名/日志 schema_version；AC-SM-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_stream_monitor_inputs_outputs` |
| chat 抓取与错误路径 | 错误策略覆盖 chat 下载失败处理；AC-SM-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_stream_monitor_chat_requirement` |
