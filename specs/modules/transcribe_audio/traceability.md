# Transcribe Audio Traceability

| AC ID | 说明 | 测试文件 | 测试用例 | 层级 | 状态 |
| --- | --- | --- | --- | --- | --- |
| AC-TA-001 | 输入契约覆盖必填与错误策略 | tests/integration/test_transcribe_audio_contract.py | test_contract_inputs_cover_required_fields | integration | pass |
| AC-TA-002 | 输出契约含 schema_version、排序、确定性说明 | tests/integration/test_transcribe_audio_contract.py | test_contract_output_has_schema_and_determinism | integration | pass |
| AC-TA-003 | 字幕输出存在性声明 | tests/integration/test_transcribe_audio_contract.py | test_contract_output_mentions_subtitles | integration | pass |

说明：实际运行级别（unit/e2e）需后续补充音频样本与 golden；状态需随实现更新。
