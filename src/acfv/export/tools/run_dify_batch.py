"""批量调用 Dify (阻塞模式为主)

示例:
  python tools/run_dify_batch.py --file tasks.txt --out out.jsonl

tasks.txt 每行一个指令；使用 "|||" 分隔可选 context:
  生成一首五言绝句
  总结下面内容|||Python 是一种解释型语言...

输出 JSONL 每行结构:
  {"task":..., "context":..., "mode":..., "json":{...}, "raw": "...", "meta": {...}}

环境变量: DIFY_BASE_URL / DIFY_API_KEY
"""
from __future__ import annotations
import os, sys, argparse, json, time
from typing import List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.dify_backend_service import get_backend  # noqa


def load_tasks(path: str) -> List[tuple[str, str]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|||" in line:
                t, c = line.split("|||", 1)
                items.append((t.strip(), c.strip()))
            else:
                items.append((line, ""))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--out", default="batch_out.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="限制任务数量, 0=全部")
    args = ap.parse_args()

    tasks = load_tasks(args.file)
    if args.limit > 0:
        tasks = tasks[:args.limit]
    backend = get_backend()

    out_path = args.out
    count = 0
    with open(out_path, "w", encoding="utf-8") as w:
        for idx, (task, ctx) in enumerate(tasks, 1):
            data = backend.run_blocking(task, ctx)
            row = {
                "task": task,
                "context": ctx,
                "mode": data.get("meta", {}).get("mode"),
                "json": data.get("json", {}),
                "raw": data.get("raw_answer", ""),
                "meta": data.get("meta", {}),
            }
            w.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{idx}/{len(tasks)}] ok - latency={row['meta'].get('latency_s')}s error={row['meta'].get('error') is not None}")
            count += 1
    print(f"完成: {count} 条, 输出 -> {out_path}")


if __name__ == "__main__":
    main()
