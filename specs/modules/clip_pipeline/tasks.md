# Clip Pipeline Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 参数与配置合并 | contract_input 涵盖参数优先级与校验；AC-CP-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_clip_pipeline_inputs_outputs` |
| 输出结构与命名 | contract_output 描述 clips/subtitles/segments 命名与 schema_version；AC-CP-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_clip_pipeline_inputs_outputs` |
| 失败路径处理 | 错误策略覆盖下载/渲染失败；AC-CP-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_clip_pipeline_failure_paths_documented` |
