# RAG (用户偏好检索) Spec

## 1) Purpose
- 负责：根据用户输入/历史偏好检索合适的梗素材、字幕风格，输出结构化配置。
- 不负责：实际渲染、策略执行。

## 2) Inputs
- `user_profile.json`（用户输入：偏好标签、禁用项、密度要求）
- 素材库metadata（assets/memes/metadata/*.json）
- 字幕风格库（assets/styles/*.yaml）
- 详见 `contract_input.md`

## 3) Outputs
- `preference_profile.json`：结构化偏好配置
  - meme_density: 0.0-1.0
  - preferred_tags: ["反转", "尴尬", ...]
  - subtitle_style_profile: "clean" / "bold" / "meme"
  - ban_assets: [...]
  - keyword_boost: {"离谱": 1.3}
- 详见 `contract_output.md`

## 4) Process
1) 加载user_profile.json
2) 构建素材库索引（FAISS/Chroma）：
   - 素材metadata的tags/trigger_regex作为文档
   - 使用sentence-transformers生成embedding
3) 检索：
   - 输入用户偏好标签（如"搞笑"/"反转"）
   - 返回top-k相似素材
4) **AI增强生成**：
   - 使用AI骨架（AISkeleton）检查并加载AI库（OpenAI/transformers）
   - 根据上下文生成个性化推荐
   - 融合检索结果与AI生成内容
5) 过滤：
   - 移除ban_assets
   - 应用keyword_boost
6) 输出preference_profile.json

## 4.1) AI骨架 (AISkeleton)
- **自动库检查**：启动时检查openai/transformers/torch等库，自动安装缺失包
- **多后端支持**：
  - OpenAI API：云端生成高质量推荐
  - Transformers：本地模型离线生成
- **生成逻辑**：基于视频上下文（标题、时长、用户偏好）构建提示词，生成推荐文本
- **错误处理**：库缺失时降级到规则匹配，生成失败时返回None

## 5) Configuration
- `rag_backend`: llamaindex / langchain
- `vector_store`: faiss / chroma
- `embedding_model`: sentence-transformers/all-MiniLM-L6-v2
- `top_k`: 10（检索数量）

## 6) Performance Budget
- 索引构建：< 10秒（100个素材）
- 检索：< 1秒（单次查询）
- 内存占用：< 2GB

## 7) Error Handling
- user_profile.json缺失：使用默认配置
- 向量库初始化失败：fallback到基于规则的匹配
- embedding模型下载失败：提示检查网络

## 8) Edge Cases
- 空素材库：返回空preferred_tags
- 用户无偏好输入：使用默认风格
- ban_assets包含所有素材：警告并允许部分解禁

## 9) Acceptance Criteria
- AC-RAG-001 格式校验：输出的preference_profile.json符合schema
- AC-RAG-002 检索准确性：top-k结果包含用户偏好标签相关素材
- AC-RAG-003 过滤有效：ban_assets中的素材不出现在输出中

## 10) Trace Links
- Contracts: `contract_input.md`, `contract_output.md`
- Implementation: `src/acfv/enhance/rag/retrieve_profile.py`
- Tests: `tests/integration/test_rag_retrieval.py`
