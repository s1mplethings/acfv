# Transcribe Audio Tasks

| Task | DoD | 验证命令 |
| --- | --- | --- |
| 定义输入/输出契约并落地到 docs | contract_input / contract_output 覆盖必填字段与错误策略；traceability 更新 | `python -m pytest tests/integration/test_transcribe_audio_contract.py::test_contract_inputs_cover_required_fields` |
| 确认输出确定性与 schema_version | 输出契约含 schema_version、排序要求、时间戳精度说明；对应测试通过 | `python -m pytest tests/integration/test_transcribe_audio_contract.py::test_contract_output_has_schema_and_determinism` |
| 建立黄金与集成校验入口 | tests/golden 占位 + verify 路径包含 integration；traceability 标记状态 | `python -m pytest tests/integration/test_transcribe_audio_contract.py` / `scripts/verify.ps1` |
