# -*- coding: utf-8 -*-
"""
本地工具服务（给 Dify 的 HTTP 请求节点使用）
- /health: 健康检查
- /tool/echo: 简单回显，验证 POST 正常
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any

app = FastAPI(title="Local Tool for Dify", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True}

class ToolIn(BaseModel):
    user_query: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

@app.post("/tool/echo")
def tool_echo(x: ToolIn):
    return {
        "received": {
            "user_query": x.user_query,
            "context": x.context or {}
        },
        "reply": f"收到：{x.user_query or ''}"
    }
