# Regression Baseline: v1.1.0

目标：把 v1.1.0 作为金标准，后续改动可对比、可回归。请将以下快照生成后存放本目录：

必备快照（小文本即可，禁止大视频/模型）：
- `cli_help.txt`: `python -m acfv.cli --help`
- `gui_help.txt`: `python -m acfv.cli gui --help`
- `pipeline_help.txt`: `python -m acfv.cli.pipeline clip --help`
- `layout.txt`: 运行最小 smoke（可用空/极小输入）后的目录结构树（例如 `tree runs/work`）。
- `config_defaults.json`（可选）：关键默认配置/参数概要。

生成方法示例：
```bash
git checkout v1.1.0
python -m acfv.cli --help > docs/regression/v1.1.0/cli_help.txt
python -m acfv.cli gui --help > docs/regression/v1.1.0/gui_help.txt
python -m acfv.cli.pipeline clip --help > docs/regression/v1.1.0/pipeline_help.txt
# 若需目录样例
# python -m acfv.cli.pipeline clip --url sample.mp4 --out-dir runs/regression_smoke --dry-run
# tree runs/regression_smoke > docs/regression/v1.1.0/layout.txt
```

使用方式：
- 每次改动后可与这些快照比对（help 输出是否异常、目录结构是否漂移）。
- 若金标准更新，请重新生成快照并注明 tag/commit。
