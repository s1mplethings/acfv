"""FastAPI 工具调用服务 (可选启动)

环境变量:
  START_TOOL_API=1  -> 在主程序启动时自动运行
  TOOL_API_PORT=8099 -> 端口 (默认 8099)

用途:
  - Flowise / 其他编排器调用内部工具
  - 列出工具 / 执行工具 / 健康检查
"""
import os
import json
import threading
import inspect
from typing import Any, Dict, Callable, List, Optional

from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def _load_tools():
    try:
        from services import app_actions
        tool_list = app_actions.get_agent_tools()
        seen = {}
        for t in tool_list:
            name = getattr(t, '__name__', None)
            if name and name not in seen:
                seen[name] = t
        return seen
    except Exception:
        return {}


TOOLS: Dict[str, Callable] = _load_tools()


class ToolCallRequest(BaseModel):
    action: str
    args: Dict[str, Any] | None = None


API_KEY = os.environ.get("TOOL_API_KEY")

app = FastAPI(title="Tool API", version="0.2.0")

# CORS (供 Flowise / Web 前端调用)
allow_origins_env = os.environ.get("ALLOW_ORIGINS", "*")
allow_origins = [o.strip() for o in allow_origins_env.split(',')] if allow_origins_env else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _param_schema(fn: Callable) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        sig = inspect.signature(fn)
        for name, p in sig.parameters.items():
            if name.startswith('_'):  # skip private/internal
                continue
            ann = p.annotation if p.annotation is not inspect._empty else Any
            default = None if p.default is inspect._empty else p.default
            out.append({
                "name": name,
                "type": getattr(ann, '__name__', str(ann)),
                "required": p.default is inspect._empty,
                "default": default,
            })
    except Exception:
        pass
    return out


def _tool_metadata(full: bool = False):
    items = []
    for name, fn in TOOLS.items():
        doc = (fn.__doc__ or '').strip()
        first_line = doc.splitlines()[0] if doc else ''
        meta = {"name": name, "summary": first_line}
        if full:
            meta["description"] = doc
            meta["parameters"] = _param_schema(fn)
        items.append(meta)
    return items


def verify_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True

@app.get("/")
def root():
    """根路径说明。访问 /health 查看健康状态；/tools 列出工具；POST /tool 调用功能。"""
    return {
        "message": "Tool API running",
        "endpoints": ["/health", "/tools", "POST /tool"],
        "example_call": {
            "method": "POST",
            "url": "/tool",
            "json": {"action": "某个工具名", "args": {"可选参数": "值"}}
        },
        "docs": "/docs"
    }

@app.get("/health")
def health(dep: bool = Depends(verify_key)):
    return {"status": "ok", "tool_count": len(TOOLS)}

@app.get("/tools")
def list_tools(full: bool = Query(False, description="返回完整描述与参数"), dep: bool = Depends(verify_key)):
    return {"tools": _tool_metadata(full=full)}


@app.get("/spec")
def spec(dep: bool = Depends(verify_key)):
    """返回工具的简单 schema 结构，方便外部编排器自动加载。"""
    return {
        "version": "0.1",
        "tools": _tool_metadata(full=True)
    }


@app.post("/tool")
def call_tool(req: ToolCallRequest, dep: bool = Depends(verify_key)):
    action = req.action.strip()
    fn = TOOLS.get(action)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {action}")
    try:
        args = req.args or {}
        import inspect
        sig = inspect.signature(fn)
        call_kwargs = {k: v for k, v in args.items() if k in sig.parameters}
        result = fn(**call_kwargs) if call_kwargs else fn()
        raw = result
        data = None
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except Exception:
                data = {"value": result}
        else:
            data = result
        return {"success": True, "tool": action, "data": data, "raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "tool": action, "error": str(e)}


def start_background_server(host: str = "127.0.0.1", port: int = 8099):
    import uvicorn
    def _run():
        uvicorn.run(app, host=host, port=port, log_level="info")
    t = threading.Thread(target=_run, daemon=True, name="ToolAPIServer")
    t.start()
    return t


if __name__ == "__main__":
    start_background_server("0.0.0.0", int(os.environ.get("TOOL_API_PORT", 8099)))
    threading.Event().wait()
