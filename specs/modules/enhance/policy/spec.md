# Policy (视角切换与梗策略) Spec

## 1) Purpose
- 负责：基于信号（关键词/场景/音量）决定视角切换（FULL/PC/V）和梗贴图/音效插入时机。
- 不负责：ASR转写、ROI检测、实际渲染。

## 2) Inputs
- `segments.json`（字幕文本）
- `rois.json`（PC/V区域）
- 场景切分结果（scenedetect输出，可选）
- 音量分析结果（可选）
- 用户偏好配置（preference_profile.json，来自RAG）
- 详见 `contract_input.md`

## 3) Outputs
- `view_events.json`：视角切换事件 `[{t0, t1, target, zoom, smooth}]`
- `overlay_events.json`：梗贴图事件 `[{t0, t1, asset, pos, scale}]`
- `sfx_events.json`：音效事件 `[{t0, t1, asset, gain_db}]`
- 详见 `contract_output.md`

## 4) Process
### 视角切换策略（MVP规则版）
1) 初始化状态：FULL
2) 逐段扫描segments：
   - 匹配强反应词（哈哈/？？/离谱）→ 切换到V（1.5-3秒）
   - PC区运动量高且无强反应词 → 切换到PC（2-5秒）
   - 场景切换附近 → FULL（0.5秒缓冲）
3) 防抖：任何视角保持 ≥1.2秒，不允许1秒内来回跳
4) 输出view_events.json

### 梗贴图策略
1) 加载meme_policy.yaml（触发词/冷却/密度）
2) 扫描segments匹配trigger_regex
3) 按cooldown和density过滤（避免过密）
4) 从assets/memes/metadata/中选择合适素材
5) 输出overlay_events.json

### 音效策略
1) 关键词命中时附加音效（如"哈哈"→笑声.mp3）
2) 检查sfx冷却时间（默认5秒）
3) 输出sfx_events.json

## 5) Configuration
- `view_min_duration`: 1.2秒（防抖）
- `reaction_keywords`: ["哈哈", "？？", "离谱", "卧槽"]
- `meme_density`: 0.0-1.0（0.3=稀疏，0.7=密集）
- `meme_cooldown`: 5秒（同一梗最小间隔）
- `sfx_cooldown`: 3秒

## 6) Performance Budget
- 10分钟视频：< 10秒策略计算时间
- 输出事件数：< 200（避免过于频繁）

## 7) Error Handling
- 缺少必需输入（segments/rois）：使用fallback策略或跳过
- 梗素材不存在：记录警告但不阻塞
- 配置非法（density>1）：clamp到合法范围

## 8) Edge Cases
- 无ROI（只有FULL）：跳过PC/V切换，保持FULL
- 无关键词命中：不输出overlay/sfx事件
- 密集触发：按cooldown和density限流

## 9) Acceptance Criteria
- AC-POLICY-001 防抖校验：相邻view事件间隔 ≥1.2秒
- AC-POLICY-002 密度控制：overlay事件密度 ≤ 配置的meme_density
- AC-POLICY-003 冷却校验：同一asset两次出现间隔 ≥ cooldown

## 10) Trace Links
- Contracts: `contract_input.md`, `contract_output.md`
- Implementation: `src/acfv/enhance/policy/view_policy.py`
- Tests: `tests/integration/test_policy_debounce.py`
