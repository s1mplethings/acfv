"""本地 Mock /tool 服务

启动:
  python tools/tool_mock_server.py --port 8099

Workflow 外部工具节点可指向:
  http://host.docker.internal:8099/tool  (Docker Desktop 常用)
  或直接 http://127.0.0.1:8099/tool

提供:
  POST /tool   - 回显请求体 + 时间戳
  GET  /tool   - 健康检查
"""
from __future__ import annotations
import argparse, time, json
from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.get("/tool")
def get_tool():
    return {"ok": True, "ts": time.time(), "usage": "POST JSON 获取回显"}

@app.post("/tool")
async def post_tool(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = None
    return {
        "ok": True,
        "ts": time.time(),
        "received": body,
        "hint": "这是本地 mock 响应，可在 workflow 中替换为真实业务服务"
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
