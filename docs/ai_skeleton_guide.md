# AI骨架使用指南

## 概述

AI骨架（AISkeleton）是ACFV项目中用于智能内容生成的统一框架，提供自动库检查、多种AI后端支持和错误处理能力。

## 核心特性

### 1. 自动库管理
- **启动时检查**：初始化时自动检测必需的AI库
- **自动安装**：缺失库时自动尝试安装
- **降级处理**：安装失败时提供错误信息和替代方案

### 2. 多后端支持
- **OpenAI API**：云端高质量生成（需要API密钥）
- **Transformers**：本地模型离线生成
- **扩展性**：易于添加新的AI后端

### 3. 统一接口
- **简单调用**：`get_ai_recommendation(context)` 一键生成
- **结构化输入**：支持视频上下文、用户偏好等参数
- **错误处理**：生成失败时返回None并记录日志

## 使用方法

### 基本使用

```python
from src.acfv.enhance.rag import get_ai_recommendation

# 准备上下文
context = {
    'video_title': '游戏实况剪辑',
    'duration': 180,  # 秒
    'user_preferences': ['搞笑', '字幕特效', '梗图']
}

# 生成推荐
recommendation = get_ai_recommendation(context)
if recommendation:
    print(f"AI推荐: {recommendation}")
else:
    print("AI生成失败，请检查库安装")
```

### 高级使用

```python
from src.acfv.enhance.rag.ai_skeleton import AISkeleton

# 创建自定义实例
ai = AISkeleton()

# 检查就绪状态
if ai.is_ready():
    recommendation = ai.generate_recommendation(context)
else:
    print("AI库未就绪")
```

## 配置要求

### 必需库
- `openai>=1.0.0`：OpenAI API客户端
- `transformers>=4.20.0`：Hugging Face模型库
- `torch>=1.9.0`：PyTorch深度学习框架

### 可选配置
- **OpenAI API密钥**：环境变量 `OPENAI_API_KEY`
- **本地模型路径**：自定义transformers模型路径

## 集成到GUI

AI骨架已集成到增强面板中：

1. **测试按钮**：点击"🧠 测试AI推荐"按钮测试功能
2. **自动检查**：启动时自动检查库状态
3. **错误提示**：GUI中显示生成结果或错误信息

## 扩展开发

### 添加新AI后端

```python
class AISkeleton:
    def _generate_with_new_backend(self, context):
        """实现新的AI后端"""
        # 检查库
        if not self._libraries_loaded.get('new_lib'):
            return None

        # 实现生成逻辑
        # ...

    def generate_recommendation(self, context):
        # 添加新的后端检查
        if self._libraries_loaded.get('new_lib'):
            return self._generate_with_new_backend(context)
        # 现有逻辑...
```

### 自定义提示词

```python
def _build_prompt(self, context):
    """自定义提示词构建"""
    prompt = f"为视频《{context['video_title']}》生成推荐..."

    # 添加自定义逻辑
    if context.get('style') == 'formal':
        prompt += " 请使用正式语气。"
    elif context.get('style') == 'casual':
        prompt += " 请使用轻松语气。"

    return prompt
```

## 故障排除

### 常见问题

1. **库安装失败**
   - 检查网络连接
   - 手动运行 `pip install openai transformers torch`
   - 使用国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple`

2. **OpenAI API调用失败**
   - 检查API密钥是否正确设置
   - 确认账户余额充足
   - 检查网络连接到OpenAI服务

3. **本地模型加载慢**
   - 首次使用需要下载模型（~1-2GB）
   - 考虑使用更小的模型如`gpt2-medium`
   - 启用模型缓存以提高后续启动速度

### 日志调试

启用详细日志查看AI骨架工作状态：

```python
import logging
logging.getLogger('src.acfv.enhance.rag.ai_skeleton').setLevel(logging.DEBUG)
```

## 性能考虑

- **初始化时间**：首次运行时库检查和安装可能需要时间
- **生成时间**：
  - OpenAI API：~2-5秒（网络依赖）
  - 本地Transformers：~5-15秒（硬件依赖）
- **内存占用**：本地模型加载时增加~1-4GB内存

## 测试

运行AI骨架单元测试：

```bash
pytest tests/unit/test_ai_skeleton.py -v
```

测试覆盖：
- 库检查和自动安装
- 多后端生成逻辑
- 错误处理和降级
- 提示词构建

## 未来扩展

- [ ] 支持更多AI后端（Claude、Gemini等）
- [ ] 模型微调和自定义训练
- [ ] 缓存机制减少重复生成
- [ ] 批量生成优化
- [ ] 多语言支持