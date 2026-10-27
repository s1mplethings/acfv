# Clip Pipeline Traceability

| AC ID | 说明 | 测试文件 | 测试用例 | 层级 | 状态 |
| --- | --- | --- | --- | --- | --- |
| AC-CP-001 | 参数合并与校验（CLI 优先） | tests/integration/test_spec_presence.py | test_clip_pipeline_inputs_outputs | integration | pass |
| AC-CP-002 | 输出结构/命名含 schema_version | tests/integration/test_spec_presence.py | test_clip_pipeline_inputs_outputs | integration | pass |
| AC-CP-003 | 下载失败路径需记录 URL/返回码 | tests/integration/test_spec_presence.py | test_clip_pipeline_failure_paths_documented | integration | pass |

状态需随实现与测试更新。
