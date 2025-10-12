# Dify 集成成功复现指南

## 环境准备
1. Dify 服务运行在 Docker 中：
   - API: http://localhost:5001
   - Web: http://localhost:5173

2. 在 Dify 控制台创建应用：
   - 类型：聊天应用（不是工作流）
   - 获取 API Key：app-xxxxxxxxxx

## 代码修改

### 1. 修改 dify_backend_service.py
```python
def run_blocking(self, task_text: str, context: str = "") -> Dict[str, Any]:
    # 构造聊天消息
    message = task_text
    if context:
        message = f"Context: {context}\n\nTask: {task_text}"
    
    # 使用聊天 API 而不是工作流 API
    result = self.client.chat(message, user="gui")
    normalized = self._normalize_answer({"answer": result.answer})
    # ...

def run_streaming(self, task_text: str, context: str = "") -> Generator[str, None, None]:
    # 构造聊天消息
    message = task_text
    if context:
        message = f"Context: {context}\n\nTask: {task_text}"
    
    # 使用聊天流式 API
    for chunk in self.client.chat_stream(message, user="gui"):
        data = chunk.data
        if not data:
            continue
        yield data
```

### 2. 修改 dify_client.py（临时方案）
```python
def __init__(self, ...):
    self.base_url = (base_url or os.getenv("DIFY_BASE_URL") or "http://localhost:5001").rstrip("/")
    # 临时硬编码 API Key
    self.api_key = api_key or os.getenv("DIFY_API_KEY") or "app-你的真实API密钥"
```

## 测试步骤
1. 启动测试程序：`python tests/gui_dify_test.py`
2. 输入测试消息
3. 点击 "Run Blocking" 或 "Run Streaming"

## 关键要点
- 聊天应用使用 `/v1/chat-messages` API
- 工作流应用使用 `/v1/workflows/run` API  
- 应用类型必须与 API 调用匹配
- API Key 格式：app-xxxxxxxxxx

## 环境变量问题解决（推荐方案）
创建 .env 文件：
```
DIFY_BASE_URL=http://localhost:5001
DIFY_API_KEY=app-你的API密钥
```

并在代码中添加 dotenv 支持。
