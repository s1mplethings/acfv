# Extract Audio Traceability

| AC ID | 说明 | 测试文件 | 测试用例 | 层级 | 状态 |
| --- | --- | --- | --- | --- | --- |
| AC-EA-001 | 输入路径与音轨校验 | tests/integration/test_spec_presence.py | test_extract_audio_inputs_outputs | integration | pass |
| AC-EA-002 | 采样率/声道标准化与命名 | tests/integration/test_spec_presence.py | test_extract_audio_inputs_outputs | integration | pass |
| AC-EA-003 | ffmpeg 失败返回非零与日志 | tests/integration/test_spec_presence.py | test_extract_audio_failure_paths_documented | integration | pass |

状态需按实现与测试更新。
