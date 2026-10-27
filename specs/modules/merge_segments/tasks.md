# Merge Segments Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 输入校验 | contract_input 覆盖 start/end 合法与 merge_gap/max_duration；AC-MS-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_merge_segments_inputs_outputs` |
| 合并规则与确定性 | contract_output 描述排序/merged_from；AC-MS-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_merge_segments_inputs_outputs` |
| 超长处理 | spec 记录 max_merged_duration 策略；AC-MS-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_merge_segments_failure_paths_documented` |
