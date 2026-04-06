# ACFV 安全与敏感信息审计报告

日期: 2025-10-15
分支: fix/entrypoint

## 1. 概述
本报告审计仓库中可能包含的敏感信息（API Key、密钥、令牌、访问凭证、个人路径等），并提供隔离与安全处理建议，避免上传到公共 GitHub。

## 2. 发现的敏感或潜在敏感文件

| 文件路径 | 类型 | 敏感级别 | 说明 | 建议处理 |
|----------|------|----------|------|----------|
| interest_rating/dify_key.txt | 明文密钥 | 高 | 包含看似真实的 sk- 前缀私钥 | 立即移出仓库，改名为 `dify_key.txt.example` |
| interest_rating/.env | 环境变量文件 | 高 | 包含 DIFY_API_KEY, SECRET_KEY 等真实值 | 不要提交；保留 `.env.example` 模板 |
| interest_rating/dify_local.json | 本地服务配置 | 中 | 包含 `api_key`（似乎是本地用） | 移到本地 secrets 目录或改成 example |
| config.txt (根与 interest_rating/config/config.txt) | 应用运行配置 | 中 | 包含 twitch_client_id/twitch_oauth_token（目前为空） | 保留，但确保不填真实凭证再提交 |
| src/acfv/processing/config_manager.py | Token 加载逻辑 | 中 | 读取 `config.json` 可能含 token | 确保 `config.json` 不进入版本库，只提交 `config.json.example` |
| interest_rating/best.pt | 模型权重 | 中 | 可能受版权/体积/许可限制 | 若非公开授权，移入 `artifacts/` 并加 ignore |
| logs/**, processing.log | 运行日志 | 低 | 可能含路径或临时信息 | 忽略日志目录 |
| interest_rating/cache/** | 缓存 | 低 | 可能含临时派生数据 | 忽略缓存目录 |
| interest_rating/thumbnails/** | 派生文件 | 低 | 无敏感内容但不必提交 | 忽略目录 |

## 3. 高风险明文内容详情

### 3.1 dify_key.txt
```
sk-kakino42nightsunomithx4me1
```
操作：立即删除或移动到 `secrets/` 并添加到 `.gitignore`。

### 3.2 .env 中的敏感字段示例
```
DIFY_API_KEY=app-zFPMFt1Xx0tUm4v1Ugyy03HN
SECRET_KEY=sk-kakino42nightsunomithx4me1
```
操作：改为 `.env.example`：
```
DIFY_API_KEY=YOUR_DIFY_API_KEY_HERE
SECRET_KEY=CHANGE_ME_SECRET_KEY
```

## 4. 建议添加到 .gitignore 的条目
在现有 `.gitignore` 基础上追加：
```
# ACFV sensitive additions
interest_rating/.env
interest_rating/dify_key.txt
interest_rating/dify_local.json
interest_rating/config/config.txt   # 若含真实值，可改为 example
config.txt                          # 根目录运行态配置，改为 runtime，不提交
secrets/
artifacts/secrets/
*.secret.json
*.local.json
*.key
*.pem
models/
*.pt
cache/
logs/
thumbnails/
```

## 5. 推荐的目录重构与隔离
```
secrets/
  dify_key.txt           (本地，不提交)
  dify_local.json        (或改名 dify_local.json.example)
  huggingface_token.txt  (如需要)
  twitch_credentials.json
```
提交时只包含 `secrets/README.md` 和各 `*.example` 模板。

## 6. 模板文件示例
### 6.1 `.env.example`
```
DIFY_BASE_URL=http://localhost:5001
DIFY_API_KEY=YOUR_DIFY_API_KEY_HERE
SECRET_KEY=CHANGE_ME_SECRET_KEY
LOG_LEVEL=INFO
```
### 6.2 `config.json.example`
```
{
  "huggingface_token": "your_huggingface_token_here"
}
```
### 6.3 `twitch_credentials.json.example`
```
{
  "twitch_client_id": "",
  "twitch_oauth_token": "",
  "twitch_username": ""
}
```

## 7. 行动清单 (更新后)
| 动作 | 优先级 | 负责人 | 状态 |
|------|--------|--------|------|
| 删除或移动 dify_key.txt | 高 | 你 | 已替换为占位 ✔ |
| 重命名 .env -> .env.example 并清理真实值 | 高 | 你 | 已清理, 文件仍命名 .env (可后续重命名) ✔ |
| 添加 secrets/ 目录和示例文件 | 中 | 已创建 ✔ |
| 将 best.pt 移入 artifacts/secrets/ 并 ignore | 中 | 已迁移 ✔ |
| 更新 .gitignore 增加敏感条目 | 高 | 已更新 ✔ |
| 创建 secrets/README.md | 中 | 已创建 ✔ |
| 添加 pre-commit 检测配置 | 高 | 已添加 ✔ |
| 自定义快速扫描脚本 tools/scan_secrets.py | 高 | 已添加 ✔ |

## 8. Pre-Commit 与扫描结果

已添加 `.pre-commit-config.yaml`：

包含 hooks:
1. detect-secrets (需要生成 `.secrets.baseline`)
2. acfv-scan-secrets (自定义快速模式扫描 `sk-`、`api_key=` 等)

初始化步骤:
```
pip install pre-commit detect-secrets
pre-commit install
detect-secrets scan > .secrets.baseline
git add .secrets.baseline
git commit -m "chore: add secrets baseline"
```

当前快速脚本执行输出显示若干“潜在”匹配，多数来自第三方打包/依赖文件（例如 botocore service json 中的 `sk-networking` 等非密钥标记，或 panel.json 中的 MAPBOX_API_KEY 字段名）。这些是误报，不是实际密钥值：

示例误报片段：
```
interest_rating/dist/.../botocore/data/ecs/...: sk-networking
interest_rating/dist/.../panel/dist/panel.json: ApiKey: MAPBOX_API_KEY
```

仍需人工确认的条目：
1. interest_rating/services/dify_client.py 与 src/acfv/ingest/services/dify_client.py 中 `api_key = backup_api_key` —— 看似占位符，但建议改为从环境变量或 secrets 文件读取。
2. interest_rating/dify_key.txt 当前应改名为 example 或移除（已替换占位）。

下一步改进：
- 针对 `dist/` 或打包第三方文件添加忽略（调整扫描脚本过滤目录）。
- 将 dify_client 中的硬编码占位改为 `os.getenv("DIFY_API_KEY")` 或读取 `secrets/dify_key.txt`。

## 9. 后续自动化建议
- 使用 pre-commit 钩子扫描 `sk-` / `API_KEY=` 等模式
- 引入 `detect-secrets` 或 `git-secrets` 工具
- CI 中增加敏感信息扫描（失败 -> 阻止推送）

## 10. 结论 (更新)
仓库原先暴露的密钥（dify_key.txt、dify_local.json 中的 api_key）已替换为占位符。仍需要：
1. 将 `interest_rating/.env` 重命名并清理真实值
2. 评估并迁移 `best.pt` 到忽略目录
3. 确认没有其他残留的本地密钥文件。

---
目前已执行：隔离目录、占位替换、pre-commit 配置、快速扫描脚本、模型权重迁移。剩余改进点：
1. 将 `.env` 重命名为 `.env.example`（保留本地真实 `.env` 不提交）。
2. dify_client 中替换硬编码占位访问方式。
3. 调整扫描脚本忽略 `dist/`、二进制和大型第三方数据目录以减少误报。

如果需要，我可以继续自动：
1. 重命名文件与更新引用。
2. 修改 dify_client 读取 secrets 机制。
3. 优化扫描脚本过滤规则。