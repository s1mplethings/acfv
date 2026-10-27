# Subtitle Generator Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 输入校验 | contract_input 覆盖 segments/format/out_dir/offset；AC-SUB-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_subtitle_generator_inputs_outputs` |
| 排序与时间偏移 | contract_output 描述排序与时间精度；AC-SUB-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_subtitle_generator_inputs_outputs` |
| 命名与 schema_version | 输出命名规则与 schema_version；AC-SUB-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_subtitle_generator_failure_paths_documented` |
