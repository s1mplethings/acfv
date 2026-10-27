# How to use this pack

把本 zip 的内容合并到你的仓库（推荐逐文件对照合并），重点是：
- docs/ 下的 SDDAI 文档已统一 verify 口径（语义单入口 + OS 实现入口）
- specs/ 补齐了“切片输出”和“渲染输出”的契约与模块 spec
- ai_context/ 提供 Task Card / Problem Registry / Decision Log 模板
- scripts/ 提供 verify 与 contract_checks 的最小骨架（需要你按仓库实际命令替换）

建议合并后：
1) 先把 scripts/verify.* 改成你仓库真实的 test/lint 命令
2) 在 CI 中按 runner OS 调用对应 verify 入口
3) 把 analyze_segments / render_clips 的真实输出路径对齐到 contract_checks
4) 避免过短片段：pipeline 默认 `min_duration_sec=6`（见 analyze_segments 插件与 render_clips 过滤），确保生成的契约 segments/manifest 不会包含 <6s 片段；如需特殊场景可通过模块参数覆盖，但推荐保持 6s 以上以符合 docs/03_quality_gates.md 的约束。
