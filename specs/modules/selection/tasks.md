# Selection & Scoring Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 配置校验 | contract_input 覆盖 strategy/topk/min_score 依赖；AC-SEL-001 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_selection_inputs_outputs` |
| 排序与确定性 | contract_output 描述排序与精度；AC-SEL-002 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_selection_inputs_outputs` |
| 过滤规则 | spec 描述阈值与时长过滤；AC-SEL-003 达成 | `python -m pytest tests/integration/test_spec_presence.py::test_selection_failure_paths_documented` |
