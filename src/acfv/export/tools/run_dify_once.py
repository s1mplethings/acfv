"""命令行快速调用 Dify (chat 或 workflow 自动识别)

用法示例:
  python tools/run_dify_once.py --task "解释一下梯度下降" \
      --context "机器学习" --stream

环境变量:
  DIFY_BASE_URL / DIFY_API_KEY  (必需)
  DIFY_FORCE_MODE=workflow|chat  (可选)
"""
from __future__ import annotations
import os, sys, argparse, json, time
from typing import Iterator

# 让脚本能找到 services 包
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.dify_backend_service import get_backend  # noqa


def run_blocking(task: str, context: str) -> int:
    backend = get_backend()
    data = backend.run_blocking(task, context)
    print("[MODE]", data.get("meta", {}).get("mode"))
    if data.get("meta", {}).get("error"):
        print("[ERROR]", data["meta"]["error"])
        return 1
    print("[JSON]", json.dumps(data.get("json", {}), ensure_ascii=False, indent=2))
    print("[RAW]", data.get("raw_answer", "")[:4000])
    print("[META]", data.get("meta"))
    return 0


def run_streaming(task: str, context: str) -> int:
    backend = get_backend()
    print("[STREAM MODE]", getattr(backend, 'mode', '?'))
    try:
        for piece in backend.run_streaming(task, context):
            if piece:
                print(piece, end="", flush=True)
        print("\n[END]")
    except KeyboardInterrupt:
        print("\n[用户中断]")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True, help="指令/问题")
    p.add_argument("--context", default="", help="可选上下文")
    p.add_argument("--stream", action="store_true", help="使用流式模式")
    p.add_argument("--force-mode", choices=["workflow", "chat"], help="强制模式 (覆盖自动判定)")
    args = p.parse_args()

    if args.force_mode:
        # 在导入 backend 前设置环境变量更安全；此处已导入但第一次调用 get_backend 之前仍可生效
        os.environ["DIFY_FORCE_MODE"] = args.force_mode
        print(f"[INFO] Force mode set to {args.force_mode}")

    if args.stream:
        code = run_streaming(args.task, args.context)
    else:
        code = run_blocking(args.task, args.context)
    sys.exit(code)


if __name__ == "__main__":
    main()
