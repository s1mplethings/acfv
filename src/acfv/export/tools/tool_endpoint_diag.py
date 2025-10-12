"""Diagnostic script for Dify external tool endpoint connectivity.

Usage (PowerShell):
  $env:DIFY_TOOL_ENDPOINT="http://host.docker.internal:8099/tool"
  python tools/tool_endpoint_diag.py

It will:
  1. Read env DIFY_TOOL_ENDPOINT or accept --url argument.
  2. Generate variant candidate URLs (host.docker.internal -> 127.0.0.1 / localhost).
  3. For each, perform: POST (empty JSON), GET (if allowed), TCP port check.
  4. Summarize latency, status, error.

Return codes:
  0 all candidates reachable (>=1 success)
  2 no candidate succeeded
"""
from __future__ import annotations
import os, sys, json, time, socket, argparse
from typing import List, Dict
import contextlib

try:
    import requests  # type: ignore
except Exception as e:  # pragma: no cover
    print("requests is required: pip install requests", file=sys.stderr)
    sys.exit(1)

def build_candidates(url: str) -> List[str]:
    cands = [url]
    if "host.docker.internal" in url:
        cands.append(url.replace("host.docker.internal", "127.0.0.1"))
        cands.append(url.replace("host.docker.internal", "localhost"))
    return list(dict.fromkeys(cands))

def port_of(url: str) -> int | None:
    import re
    m = re.match(r"https?://[^:/]+:(\d+)", url)
    if m:
        return int(m.group(1))
    return 80 if url.startswith("http://") else 443

def host_of(url: str) -> str:
    import re
    m = re.match(r"https?://([^/:]+)", url)
    return m.group(1) if m else "localhost"

def tcp_check(host: str, port: int, timeout: float = 2.0) -> Dict[str, str]:
    t0 = time.time()
    try:
        with contextlib.closing(socket.create_connection((host, port), timeout=timeout)):
            return {"ok": True, "latency_s": round(time.time() - t0, 3)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def probe(url: str) -> Dict:
    res: Dict = {"url": url}
    host = host_of(url)
    port = port_of(url) or 80
    res["tcp"] = tcp_check(host, port)

    # POST
    try:
        t0 = time.time()
        r = requests.post(url, json={}, timeout=3)
        body = None
        try:
            body = r.json()
        except Exception:
            body = r.text[:200]
        res["post"] = {
            "status": r.status_code,
            "latency_s": round(time.time() - t0, 3),
            "body": body,
        }
    except Exception as e:
        res["post"] = {"error": str(e)}

    # GET (some endpoints may not support; ignore errors)
    try:
        t0 = time.time()
        g = requests.get(url, timeout=3)
        res["get"] = {"status": g.status_code, "latency_s": round(time.time() - t0, 3)}
    except Exception as e:
        res["get"] = {"error": str(e)}
    return res

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.getenv("DIFY_TOOL_ENDPOINT", ""), help="Tool endpoint URL")
    args = p.parse_args()
    if not args.url:
        print("Set --url or env DIFY_TOOL_ENDPOINT")
        return 2
    cands = build_candidates(args.url)
    print("Candidates:")
    for c in cands:
        print("  -", c)
    results = [probe(c) for c in cands]
    print("\nRaw Results JSON:")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    any_success = any(r.get("post", {}).get("status", 0) in (200, 201, 204) for r in results)
    print("\nSummary:")
    if any_success:
        print("✓ At least one candidate responded 2xx. Adjust workflow to use that working URL if different.")
        return 0
    else:
        print("✗ No candidate produced 2xx. Start tool service or check network mapping.")
        return 2

if __name__ == "__main__":
    code = main() or 0
    sys.exit(code)
