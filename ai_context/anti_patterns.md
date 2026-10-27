# Anti-Patterns

- 为了通过测试而删除测试或弱化断言
- 修改输出契约（schema/排序/精度）而不更新 spec/contract/tests/golden
- 绕过 verify 或跳过质量门直接合并
- 发现 drift 不记录 decision_log
- 在日志或仓库中包含真实凭证
